import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, replace

from app.graph.state import NutritionGraphState
from app.llm.client import get_settings
from app.schemas.nutrition import (
    CandidateDiagnostic,
    IngredientEstimate,
    IngredientNutrition,
    NutritionCandidate,
    NutritionValues,
    RetrievalDiagnostic,
    RetrievalFailure,
)
from app.tools.fallback_nutrition import (
    contains_water_reference,
    is_component_class_prior_name,
    is_high_variance_fallback_name,
    is_plain_water_query,
    lookup_component_class_prior,
)
from app.tools.food_normalization import detect_preparation, find_food_mentions
from app.tools.food_query import normalize_food_description
from app.tools.food_vocabulary import load_food_vocabulary
from app.tools.meal_validation import clarification_meal, validate_meal
from app.tools.nutrition_tools import (
    CandidateSelection,
    NutritionSourceRouter,
    candidate_from_per_100g,
    get_default_router,
    provider_search_queries,
)
from app.tools.nutrition_validation import validate_candidate
from app.tools.provider_utils import redacted_text

LOGGER = logging.getLogger(__name__)
_LOCALIZED_FOOD_NAMES = {
    language: dict(names)
    for language, names in load_food_vocabulary().localized_food_names.items()
}


@dataclass(frozen=True)
class LookupOutcome:
    item: IngredientNutrition | None
    failure: RetrievalFailure | None
    diagnostic: RetrievalDiagnostic


class NutritionRetriever:
    def __init__(self, router: NutritionSourceRouter | None = None) -> None:
        self.router = router or get_default_router()

    def lookup(
        self,
        ingredient: IngredientEstimate,
        *,
        source_route: str | None = None,
        language: str | None = None,
    ) -> IngredientNutrition | None:
        return self.lookup_with_diagnostics(
            ingredient,
            source_route=source_route,
            language=language,
        ).item

    def lookup_with_diagnostics(
        self,
        ingredient: IngredientEstimate,
        *,
        source_route: str | None = None,
        language: str | None = None,
        request_id: str | None = None,
        raw_input: str | None = None,
    ) -> LookupOutcome:
        query = normalize_food_description(
            ingredient.name,
            language=language,
            source_route=source_route,
        )
        preparation = detect_preparation(ingredient.preparation or "") or detect_preparation(ingredient.name)
        if load_food_vocabulary().food_roles.get(query.canonical_query) == "fat":
            preparation = None
        query = replace(query, preparation=preparation)
        if preparation == "fried":
            roles = load_food_vocabulary().food_roles
            oil_separate = ingredient.origin == "composite_allocation" or any(roles.get(m.canonical_name) == "fat" for m in find_food_mentions(raw_input or ""))
            query = replace(query, frying_oil_in_meal=oil_separate)
        modified_water_context = bool(
            query.food_category == "plain_water"
            and raw_input
            and contains_water_reference(raw_input)
            and not is_plain_water_query(raw_input)
        )
        if modified_water_context:
            query = normalize_food_description(
                raw_input or ingredient.name,
                language=language,
                source_route=source_route,
            )
        if ingredient.observed_label is not None:
            label = ingredient.observed_label
            factor = 1.0 if label.basis == "per_100g" else 100.0 / float(label.serving_grams or 100)
            observed = NutritionCandidate(
                source="observed_label", source_id="label", name=ingredient.name,
                serving_id=label.basis, source_confidence=ingredient.confidence,
                values_per_100g=NutritionValues(
                    calories_kcal=label.calories_kcal * factor, protein_g=label.protein_g * factor,
                    fat_g=label.fat_g * factor, carbohydrate_g=label.carbs_g * factor,
                ), metadata={"basis": label.basis, "serving_grams": label.serving_grams},
            )
            validation = validate_candidate(observed, query)
            selection = CandidateSelection(
                selected=observed if validation.accepted else None,
                candidates=[observed], validations=[validation], arbitration_path="observed_label",
            )
        else:
            selection = self.router.select_candidate(query)
        selected = selection.selected
        warning: str | None = None
        fallback_path: str | None = None
        if selected is not None and selected.source == "fallback":
            if selected.metadata.get("preparation_assumption"):
                warning = (
                    "Принята жарка без панировки; масло учтено отдельно." if query.frying_oil_in_meal
                    else "Принята жарка без панировки с 5% масла по массе готовой порции."
                ) if language == "ru" else (
                    "Assumed unbreaded frying; oil is counted separately." if query.frying_oil_in_meal
                    else "Assumed unbreaded frying with oil at 5% of cooked serving mass."
                )
            if is_component_class_prior_name(selected.name):
                fallback_path = "component_class_prior_backfill"
                warning = _component_class_prior_warning(
                    ingredient.name,
                    selected.name,
                    language=language,
                )
            else:
                fallback_path = "explicit_category_or_food_fallback"
        if selected is None:
            class_prior = lookup_component_class_prior(
                ingredient.name
            ) or lookup_component_class_prior(query.canonical_query)
            if class_prior is not None:
                selected = candidate_from_per_100g(
                    class_prior.as_nutrition(),
                    source="fallback",
                    name_override=class_prior.name,
                )
                validation = validate_candidate(selected, query)
                selection.candidates.append(selected)
                selection.validations.append(validation)
                if not validation.accepted:
                    selected = None
                fallback_path = "component_class_prior_backfill"
                warning = _component_class_prior_warning(
                    ingredient.name,
                    class_prior.name,
                    language=language,
                )

        # All sources, including injected routers and class priors, cross this boundary.
        if selected is not None and not validate_candidate(selected, query).accepted:
            selected = None
            fallback_path = None

        settings = get_settings()
        raw_context = None
        if settings.nutrition_diagnostics_include_raw:
            limit = settings.nutrition_diagnostics_max_payload_chars
            raw_context = {
                "user_input": redacted_text(raw_input or "")[:limit],
                "candidate_metadata": [
                    _public_candidate_debug(candidate).metadata
                    for candidate in selection.candidates
                ],
            }
        diagnostic = RetrievalDiagnostic(
            request_id=request_id,
            ingredient_name=ingredient.name,
            canonical_query=query.canonical_query,
            query_kind=query.query_kind,
            food_category=query.food_category,
            product_variant=query.product_variant,
            product_type=query.product_type,
            component_origin=ingredient.origin,
            amount_min_g=ingredient.grams_min,
            amount_max_g=ingredient.grams_max,
            provider_queries=provider_search_queries(query),
            candidates=[
                CandidateDiagnostic(
                    identity=candidate.stable_identity,
                    source=candidate.source,
                    source_id=candidate.source_id,
                    serving_id=candidate.serving_id,
                    name=candidate.name,
                    score=candidate.match_score,
                    score_components=candidate.score_components,
                    values_per_100g=candidate.values_per_100g,
                    validation=validation,
                )
                for candidate, validation in zip(
                    selection.candidates,
                    selection.validations,
                    strict=True,
                )
            ],
            selected_identity=selected.stable_identity if selected else None,
            arbitration_path=selection.arbitration_path,
            arbitration_reasons=list(selection.arbitration_reasons),
            fallback_path=fallback_path,
            raw_context=raw_context,
        )
        LOGGER.info(
            "Nutrition retrieval request_id=%s candidates=%d selected_identity=%s path=%s",
            request_id, len(diagnostic.candidates), diagnostic.selected_identity,
            diagnostic.arbitration_path,
        )

        if selected is None:
            failure = RetrievalFailure(
                ingredient_name=ingredient.name,
                canonical_query=query.canonical_query,
                reason="no_semantically_valid_candidate",
                grams_min=ingredient.grams_min,
                grams_max=ingredient.grams_max,
                component_origin=ingredient.origin,
            )
            LOGGER.warning(
                "Nutrition retrieval failed request_id=%s reason=%s",
                request_id,
                failure.reason,
            )
            return LookupOutcome(item=None, failure=failure, diagnostic=diagnostic)

        per_100g = selected.to_per_100g()
        if per_100g is None:
            failure = RetrievalFailure(
                ingredient_name=ingredient.name,
                canonical_query=query.canonical_query,
                reason="selected_candidate_missing_per_100g_values",
                grams_min=ingredient.grams_min,
                grams_max=ingredient.grams_max,
                component_origin=ingredient.origin,
            )
            return LookupOutcome(item=None, failure=failure, diagnostic=diagnostic)

        LOGGER.info(
            "Nutrition selected request_id=%s source=%s source_id=%s score=%s",
            request_id,
            selected.source,
            selected.source_id,
            selected.match_score,
        )
        grams_min = ingredient.grams_min
        grams_max = ingredient.grams_max
        if selected.source == "fallback" and is_component_class_prior_name(per_100g.food_name):
            grams_min, grams_max = _widen_component_prior_grams(grams_min, grams_max)
            warning = warning or _component_class_prior_warning(
                ingredient.name,
                per_100g.food_name,
                language=language,
            )
            fallback_path = fallback_path or "component_class_prior_backfill"
        elif _should_widen_high_variance_fallback(
            selected.source,
            per_100g.food_name,
            grams_min,
            grams_max,
        ):
            grams_min, grams_max = _widen_high_variance_fallback_grams(grams_min, grams_max)
            warning = warning or _high_variance_fallback_warning(ingredient.name, language=language)
        elif _should_widen_provider_prepared_dish(selected.source, query.query_kind, grams_min, grams_max):
            grams_min, grams_max = _widen_provider_prepared_dish_grams(grams_min, grams_max)
            warning = warning or _provider_prepared_dish_warning(ingredient.name, language=language)
        factor_min = grams_min / ingredient.grams_min if ingredient.grams_min else 1.0
        factor_max = grams_max / ingredient.grams_max
        if selected.metadata.get("preparation_assumption"):
            factor_min, factor_max = min(factor_min, 0.8), max(factor_max, 1.2)
        diagnostic.source_factor_min = factor_min
        diagnostic.source_factor_max = factor_max
        item = IngredientNutrition(
            ingredient_name=ingredient.name,
            matched_food_name=per_100g.food_name,
            grams_min=ingredient.grams_min,
            grams_max=ingredient.grams_max,
            source_factor_min=factor_min,
            source_factor_max=factor_max,
            per_100g=per_100g,
            source=per_100g.source,
            warning=warning,
            candidate=_public_candidate_debug(selected),
        )
        return LookupOutcome(item=item, failure=None, diagnostic=diagnostic)


def retrieve_nutrition(state: NutritionGraphState) -> NutritionGraphState:
    meal = state.get("meal")
    if meal is None:
        return {"ingredient_nutrition": []}
    if meal.needs_clarification:
        return {
            "meal": meal.model_copy(update={"ingredients": []}),
            "ingredient_nutrition": [],
            "retrieval_failures": [],
            "retrieval_diagnostics": [],
        }

    normalized = state.get("normalized_input")
    scope = state.get("scope_decision")
    failures = validate_meal(
        meal, normalized.text or "" if normalized else "",
        allow_observed_label=bool(normalized and normalized.has_image and scope and scope.route == "packaged_food"),
    )
    if failures:
        LOGGER.warning("Meal rejected request_id=%s reasons=%s", state.get("request_id"), failures)
        return {
            "meal": clarification_meal(normalized.language if normalized else "en"),
            "ingredient_nutrition": [],
            "retrieval_failures": [],
        }

    scope = state.get("scope_decision")
    normalized = state.get("normalized_input")
    source_route = scope.route if scope else None
    language = normalized.language if normalized else None
    retriever = NutritionRetriever()
    settings = get_settings()
    started = time.perf_counter()
    outcomes = _lookup_ingredients(
        retriever,
        meal.ingredients,
        source_route=source_route,
        language=language,
        request_id=state.get("request_id"),
        raw_input=normalized.text if normalized else None,
        max_workers=settings.nutrition_retrieval_max_workers,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    LOGGER.info(
        "Nutrition ingredient retrieval complete request_id=%s ingredient_count=%d "
        "worker_count=%d duration_ms=%.1f",
        state.get("request_id"),
        len(meal.ingredients),
        min(settings.nutrition_retrieval_max_workers, len(meal.ingredients)),
        elapsed_ms,
    )
    return {
        "ingredient_nutrition": [outcome.item for outcome in outcomes if outcome.item is not None],
        "retrieval_failures": [outcome.failure for outcome in outcomes if outcome.failure is not None],
        "retrieval_diagnostics": [outcome.diagnostic for outcome in outcomes],
    }


def _widen_component_prior_grams(minimum: float, maximum: float) -> tuple[float, float]:
    midpoint = (minimum + maximum) / 2
    if midpoint <= 0:
        return minimum, maximum
    half_width = max((maximum - minimum) / 2, midpoint * 0.4)
    return round(max(1.0, midpoint - half_width), 1), round(midpoint + half_width, 1)


def _component_class_prior_warning(
    ingredient_name: str,
    prior_name: str,
    *,
    language: str | None,
) -> str:
    if language == "ru":
        return (
            f"{ingredient_name}: использован широкий типовой профиль \"{prior_name}\"; "
            "уверенность снижена."
        )
    return (
        f"{ingredient_name}: used a broad \"{prior_name}\" class prior; "
        "confidence reduced."
    )


def _should_widen_provider_prepared_dish(
    source: str,
    query_kind: str,
    grams_min: float,
    grams_max: float,
) -> bool:
    return source != "fallback" and query_kind == "standard_prepared_dish" and grams_min == grams_max


def _should_widen_high_variance_fallback(
    source: str,
    food_name: str,
    grams_min: float,
    grams_max: float,
) -> bool:
    if source != "fallback" or not is_high_variance_fallback_name(food_name):
        return False
    midpoint = (grams_min + grams_max) / 2
    return midpoint > 0 and (grams_max - grams_min) / midpoint < 0.50


def _widen_high_variance_fallback_grams(minimum: float, maximum: float) -> tuple[float, float]:
    midpoint = (minimum + maximum) / 2
    half_width = max((maximum - minimum) / 2, midpoint * 0.35)
    return round(max(1.0, midpoint - half_width), 1), round(midpoint + half_width, 1)


def _high_variance_fallback_warning(ingredient_name: str, *, language: str | None) -> str:
    display_name = _LOCALIZED_FOOD_NAMES.get(language or "", {}).get(ingredient_name, ingredient_name)
    if language == "ru":
        return f"{display_name}: диапазон расширен для вариативного готового блюда."
    return f"{display_name}: widened range for high-variance prepared dish."


def _widen_provider_prepared_dish_grams(minimum: float, maximum: float) -> tuple[float, float]:
    midpoint = (minimum + maximum) / 2
    half_width = max((maximum - minimum) / 2, midpoint * 0.12)
    return round(max(1.0, midpoint - half_width), 1), round(midpoint + half_width, 1)


def _provider_prepared_dish_warning(ingredient_name: str, *, language: str | None) -> str:
    if language == "ru":
        return (
            f"{ingredient_name}: диапазон расширен для готового блюда, "
            "так как найден один справочный ряд."
        )
    return (
        f"{ingredient_name}: widened range for prepared dish because one provider row was used."
    )


def _lookup_ingredients(
    retriever: NutritionRetriever,
    ingredients: list[IngredientEstimate],
    *,
    source_route: str | None,
    language: str | None,
    request_id: str | None,
    raw_input: str | None,
    max_workers: int,
) -> list[LookupOutcome]:
    if len(ingredients) <= 1 or max_workers == 1:
        return [
            _lookup_ingredient_safely(
                retriever,
                ingredient,
                source_route=source_route,
                language=language,
                request_id=request_id,
                raw_input=raw_input,
            )
            for ingredient in ingredients
        ]

    worker_count = min(max_workers, len(ingredients))
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="nutrition-retrieval",
    ) as executor:
        futures: list[Future[LookupOutcome]] = []
        for ingredient in ingredients:
            context = copy_context()
            futures.append(
                executor.submit(
                    context.run,
                    _lookup_ingredient_safely,
                    retriever,
                    ingredient,
                    source_route=source_route,
                    language=language,
                    request_id=request_id,
                    raw_input=raw_input,
                )
            )
        return [future.result() for future in futures]


def _lookup_ingredient_safely(
    retriever: NutritionRetriever,
    ingredient: IngredientEstimate,
    *,
    source_route: str | None,
    language: str | None,
    request_id: str | None,
    raw_input: str | None,
) -> LookupOutcome:
    started = time.perf_counter()
    try:
        return retriever.lookup_with_diagnostics(
            ingredient,
            source_route=source_route,
            language=language,
            request_id=request_id,
            raw_input=raw_input,
        )
    except Exception as exc:
        LOGGER.error(
            "Nutrition ingredient lookup raised request_id=%s error_type=%s",
            request_id,
            type(exc).__name__,
        )
        return _unexpected_failure_outcome(
            ingredient,
            source_route=source_route,
            language=language,
            request_id=request_id,
        )
    finally:
        LOGGER.info(
            "Nutrition ingredient lookup complete request_id=%s duration_ms=%.1f",
            request_id,
            (time.perf_counter() - started) * 1000,
        )


def _unexpected_failure_outcome(
    ingredient: IngredientEstimate,
    *,
    source_route: str | None,
    language: str | None,
    request_id: str | None,
) -> LookupOutcome:
    try:
        query = normalize_food_description(
            ingredient.name,
            language=language,
            source_route=source_route,
        )
        canonical_query = query.canonical_query
        query_kind: str = query.query_kind
        food_category = query.food_category
        product_variant = query.product_variant
        product_type = query.product_type
        queries = provider_search_queries(query)
    except Exception:
        canonical_query = ingredient.name.strip().casefold()
        query_kind = "unknown"
        food_category = "unknown"
        product_variant = "unknown"
        product_type = None
        queries = []

    failure = RetrievalFailure(
        ingredient_name=ingredient.name,
        canonical_query=canonical_query,
        reason="unexpected_retrieval_error",
        grams_min=ingredient.grams_min,
        grams_max=ingredient.grams_max,
        component_origin=ingredient.origin,
    )
    diagnostic = RetrievalDiagnostic(
        request_id=request_id,
        ingredient_name=ingredient.name,
        canonical_query=canonical_query,
        query_kind=query_kind,
        food_category=food_category,
        product_variant=product_variant,
        product_type=product_type,
        amount_min_g=ingredient.grams_min,
        amount_max_g=ingredient.grams_max,
        provider_queries=queries,
    )
    return LookupOutcome(item=None, failure=failure, diagnostic=diagnostic)


def _public_candidate_debug(candidate: NutritionCandidate) -> NutritionCandidate:
    return candidate.model_copy(
        update={
            "metadata": {
                key: value
                for key, value in candidate.metadata.items()
                if key in {"data_type", "food_category", "quantity", "categories", "publication_date"}
            }
        }
    )
