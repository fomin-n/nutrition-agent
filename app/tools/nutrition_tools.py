import logging
from dataclasses import dataclass
from functools import lru_cache

from app.llm.client import get_settings, reveal_secret
from app.schemas.nutrition import (
    CandidateValidationResult,
    NutritionCandidate,
    NutritionPer100g,
    NutritionValues,
)
from app.tools.cache import JsonFileCache
from app.tools.fallback_nutrition import lookup_fallback_food, normalize_food_query
from app.tools.fatsecret_client import FatSecretAuthClient, FatSecretClient
from app.tools.food_query import NormalizedFoodQuery, normalize_food_description
from app.tools.nutrition_ranking import rank_candidates
from app.tools.nutrition_validation import validate_candidate
from app.tools.open_food_facts_client import OpenFoodFactsClient
from app.tools.usda_client import UsdaClient, data_types_for_query_kind

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CandidateSelection:
    selected: NutritionCandidate | None
    candidates: list[NutritionCandidate]
    validations: list[CandidateValidationResult]


class NutritionSourceRouter:
    def __init__(
        self,
        *,
        usda: UsdaClient | None = None,
        fatsecret: FatSecretClient | None = None,
        open_food_facts: OpenFoodFactsClient | None = None,
    ) -> None:
        self.usda = usda
        self.fatsecret = fatsecret
        self.open_food_facts = open_food_facts

    def retrieve_candidates(self, query: NormalizedFoodQuery, *, include_fallback: bool = True) -> list[NutritionCandidate]:
        candidates: list[NutritionCandidate] = []
        for provider in self._provider_order(query):
            if provider == "fatsecret":
                candidates.extend(self._fatsecret_candidates(query))
            elif provider == "usda":
                candidates.extend(self._usda_candidates(query))
            elif provider == "open_food_facts":
                candidates.extend(self._open_food_facts_candidates(query))
            elif provider == "fallback" and include_fallback:
                fallback = _fallback_candidate(query)
                if fallback is not None:
                    candidates.append(fallback)
        ranked = rank_candidates(_dedupe_candidates(candidates), query)
        LOGGER.info(
            "Nutrition retrieval query_kind=%s canonical=%r result_count=%d top_source=%s top_id=%s",
            query.query_kind,
            query.canonical_query,
            len(ranked),
            ranked[0].source if ranked else None,
            ranked[0].source_id if ranked else None,
        )
        return ranked

    def best_candidate(self, query: NormalizedFoodQuery) -> NutritionCandidate | None:
        return self.select_candidate(query).selected

    def select_candidate(self, query: NormalizedFoodQuery) -> CandidateSelection:
        candidates = self.retrieve_candidates(query)
        validations = [validate_candidate(candidate, query) for candidate in candidates]
        selected = next(
            (
                candidate
                for candidate, validation in zip(candidates, validations, strict=True)
                if validation.accepted
            ),
            None,
        )
        return CandidateSelection(selected=selected, candidates=candidates, validations=validations)

    def _provider_order(self, query: NormalizedFoodQuery) -> list[str]:
        if query.query_kind in {"branded_product", "restaurant_menu_item"}:
            return ["fatsecret", "usda", "open_food_facts", "fallback"]
        if query.query_kind in {"standard_prepared_dish", "user_composite_meal", "photo_derived_food"}:
            return ["usda", "fatsecret", "fallback"]
        return ["usda", "fatsecret", "fallback"]

    def _fatsecret_candidates(self, query: NormalizedFoodQuery) -> list[NutritionCandidate]:
        if self.fatsecret is None or not self.fatsecret.enabled:
            return []
        search_results: list[NutritionCandidate] = []
        for search_query in provider_search_queries(query):
            search_results.extend(
                self.fatsecret.search_foods(
                    search_query,
                    max_results=8,
                    region=query.region,
                    language=query.language,
                )
            )
        search_results = _dedupe_candidates(search_results)
        detailed: list[NutritionCandidate] = []
        for candidate in search_results[:3]:
            if candidate.source_id:
                detail = self.fatsecret.get_food(
                    candidate.source_id,
                    region=query.region,
                    language=query.language,
                )
                detailed.append(detail or candidate)
            else:
                detailed.append(candidate)
        detailed.extend(search_results[3:])
        return detailed

    def _usda_candidates(self, query: NormalizedFoodQuery) -> list[NutritionCandidate]:
        if self.usda is None or not self.usda.enabled:
            return []
        candidates: list[NutritionCandidate] = []
        for search_query in provider_search_queries(query):
            candidates.extend(
                self.usda.search_foods(
                    search_query,
                    data_types=data_types_for_query_kind(query.query_kind),
                    page_size=10,
                    require_details=True,
                )
            )
        return _dedupe_candidates(candidates)

    def _open_food_facts_candidates(self, query: NormalizedFoodQuery) -> list[NutritionCandidate]:
        if self.open_food_facts is None:
            return []
        return self.open_food_facts.search_products(query.canonical_query, page_size=5)


@lru_cache(maxsize=1)
def get_default_router() -> NutritionSourceRouter:
    settings = get_settings()
    cache = JsonFileCache(settings.nutrition_cache_dir)
    usda = UsdaClient(reveal_secret(settings.usda_api_key), cache) if settings.enable_usda else None
    fatsecret = None
    if settings.enable_fatsecret:
        auth_client = FatSecretAuthClient(
            client_id=reveal_secret(settings.fatsecret_client_id),
            client_secret=reveal_secret(settings.fatsecret_client_secret),
        )
        fatsecret = FatSecretClient(auth_client=auth_client)
    open_food_facts = OpenFoodFactsClient(cache) if settings.enable_open_food_facts else None
    return NutritionSourceRouter(usda=usda, fatsecret=fatsecret, open_food_facts=open_food_facts)


def search_fatsecret_foods(
    query: str,
    *,
    page: int = 0,
    max_results: int = 20,
    region: str | None = None,
    language: str | None = None,
) -> list[NutritionCandidate]:
    router = get_default_router()
    if router.fatsecret is None:
        return []
    return router.fatsecret.search_foods(query, page=page, max_results=max_results, region=region, language=language)


def get_fatsecret_food(
    food_id: str,
    *,
    region: str | None = None,
    language: str | None = None,
) -> NutritionCandidate | None:
    router = get_default_router()
    if router.fatsecret is None:
        return None
    return router.fatsecret.get_food(food_id, region=region, language=language)


def search_usda_foods(query: str, *, query_kind: str = "generic_ingredient") -> list[NutritionCandidate]:
    router = get_default_router()
    if router.usda is None:
        return []
    return router.usda.search_foods(
        query,
        data_types=data_types_for_query_kind(query_kind),
        page_size=10,
        require_details=True,
    )


def get_usda_food(fdc_id: str) -> NutritionCandidate | None:
    router = get_default_router()
    if router.usda is None:
        return None
    return router.usda.get_food(fdc_id)


def retrieve_nutrition_candidates(
    query: str,
    *,
    language: str | None = None,
    source_route: str | None = None,
) -> list[NutritionCandidate]:
    normalized = normalize_food_description(query, language=language, source_route=source_route)
    return get_default_router().retrieve_candidates(normalized)


def _fallback_candidate(query: NormalizedFoodQuery) -> NutritionCandidate | None:
    per_100g = lookup_fallback_food(query.canonical_query) or lookup_fallback_food(query.original)
    if per_100g is None:
        return None
    return candidate_from_per_100g(per_100g, source="fallback")


def provider_search_queries(query: NormalizedFoodQuery) -> list[str]:
    queries = [query.canonical_query]
    normalized = normalize_food_query(query.canonical_query)
    if " with " in f" {normalized} ":
        primary = normalized.split(" with ", maxsplit=1)[0].strip()
        if primary:
            queries.append(primary)
    if query.brand:
        brand_tokens = set(normalize_food_query(query.brand).split())
        tokens = [
            token
            for token in normalized.split()
            if token not in brand_tokens and not token.isdigit() and token not in {"g", "г", "kg", "кг"}
        ]
        product_only = " ".join(tokens).strip()
        if product_only:
            queries.append(product_only)
    result: list[str] = []
    seen: set[str] = set()
    for item in queries:
        key = normalize_food_query(item)
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def generic_fallback_candidate(name: str) -> NutritionCandidate:
    return candidate_from_per_100g(
        NutritionPer100g(
            food_name="generic mixed food",
            calories_kcal=180,
            protein_g=8,
            fat_g=7,
            carbs_g=20,
            source="generic_fallback",
            source_id="generic_mixed_food",
        ),
        source="generic_fallback",
        name_override=name,
    )


def candidate_from_per_100g(
    per_100g: NutritionPer100g,
    *,
    source: str | None = None,
    name_override: str | None = None,
) -> NutritionCandidate:
    return NutritionCandidate(
        source=source or per_100g.source,
        source_id=per_100g.source_id,
        name=name_override or per_100g.food_name,
        food_type="generic" if (source or per_100g.source) in {"fallback", "generic_fallback"} else "unknown",
        metric_serving_amount=100,
        metric_serving_unit="g",
        serving_description="per 100 g",
        calories_kcal=per_100g.calories_kcal,
        protein_g=per_100g.protein_g,
        fat_g=per_100g.fat_g,
        carbohydrate_g=per_100g.carbs_g,
        values_per_100g=NutritionValues(
            calories_kcal=per_100g.calories_kcal,
            protein_g=per_100g.protein_g,
            fat_g=per_100g.fat_g,
            carbohydrate_g=per_100g.carbs_g,
        ),
        source_confidence="medium",
    )


def _dedupe_candidates(candidates: list[NutritionCandidate]) -> list[NutritionCandidate]:
    seen: set[tuple[str, str | None, str]] = set()
    result: list[NutritionCandidate] = []
    for candidate in candidates:
        key = (candidate.source, candidate.source_id, candidate.name.lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result
