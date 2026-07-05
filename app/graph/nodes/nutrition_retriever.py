import json
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass

from app.graph.state import NutritionGraphState
from app.llm.client import get_settings
from app.schemas.nutrition import (
    CandidateDiagnostic,
    IngredientEstimate,
    IngredientNutrition,
    NutritionCandidate,
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
from app.tools.food_query import normalize_food_description
from app.tools.nutrition_tools import (
    NutritionSourceRouter,
    candidate_from_per_100g,
    generic_fallback_candidate,
    get_default_router,
    provider_search_queries,
)
from app.tools.nutrition_validation import validate_candidate
from app.tools.provider_utils import redacted_text

LOGGER = logging.getLogger(__name__)


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
        selection = self.router.select_candidate(query)
        selected = selection.selected
        warning: str | None = None
        fallback_path: str | None = None
        if (
            selected is None
            and not modified_water_context
            and query.query_kind in {"user_composite_meal", "photo_derived_food"}
        ):
            generic = generic_fallback_candidate(ingredient.name)
            validation = validate_candidate(generic, query)
            selection.candidates.append(generic)
            selection.validations.append(validation)
            if validation.accepted:
                selected = generic
                fallback_path = "generic_mixed_food_for_composite_or_photo"
                warning = f"No source match for {ingredient.name}; used a generic composite-food fallback."
        if selected is not None and selected.source == "fallback":
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
                fallback_path = "component_class_prior_backfill"
                warning = _component_class_prior_warning(
                    ingredient.name,
                    class_prior.name,
                    language=language,
                )

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
        LOGGER.info("Nutrition retrieval diagnostic=%s", json.dumps(diagnostic.model_dump(), ensure_ascii=True))

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
                "Nutrition retrieval failed request_id=%s canonical=%r reason=%s",
                request_id,
                query.canonical_query,
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
            "Nutrition selected ingredient=%r canonical=%r source=%s source_id=%s score=%s",
            ingredient.name,
            query.canonical_query,
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
        item = IngredientNutrition(
            ingredient_name=ingredient.name,
            matched_food_name=per_100g.food_name,
            grams_min=grams_min,
            grams_max=grams_max,
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
    if language == "ru":
        return f"{ingredient_name}: диапазон расширен для вариативного готового блюда."
    return f"{ingredient_name}: widened range for high-variance prepared dish."


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
    except Exception:
        LOGGER.exception(
            "Nutrition ingredient lookup raised request_id=%s ingredient=%r",
            request_id,
            ingredient.name,
        )
        return _unexpected_failure_outcome(
            ingredient,
            source_route=source_route,
            language=language,
            request_id=request_id,
        )
    finally:
        LOGGER.info(
            "Nutrition ingredient lookup complete request_id=%s ingredient=%r duration_ms=%.1f",
            request_id,
            ingredient.name,
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
