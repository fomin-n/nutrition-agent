from difflib import SequenceMatcher

from app.schemas.nutrition import NutritionCandidate
from app.tools.fallback_nutrition import normalize_food_query
from app.tools.food_query import NormalizedFoodQuery

SOURCE_PRIORITY: dict[str, dict[str, float]] = {
    "generic_ingredient": {
        "usda": 0.35,
        "fatsecret": 0.18,
        "open_food_facts": 0.05,
        "fallback": 0.18,
        "generic_fallback": -0.25,
    },
    "standard_prepared_dish": {
        "usda": 0.30,
        "fatsecret": 0.22,
        "open_food_facts": 0.04,
        "fallback": 0.08,
        "generic_fallback": -0.25,
    },
    "branded_product": {
        "fatsecret": 0.35,
        "open_food_facts": 0.24,
        "usda": 0.18,
        "fallback": -0.08,
        "generic_fallback": -0.30,
    },
    "restaurant_menu_item": {
        "fatsecret": 0.35,
        "usda": 0.12,
        "open_food_facts": 0.02,
        "fallback": -0.05,
        "generic_fallback": -0.30,
    },
    "user_composite_meal": {
        "usda": 0.22,
        "fatsecret": 0.16,
        "fallback": 0.10,
        "open_food_facts": 0.02,
        "generic_fallback": -0.25,
    },
    "photo_derived_food": {
        "usda": 0.24,
        "fatsecret": 0.16,
        "fallback": 0.10,
        "open_food_facts": 0.02,
        "generic_fallback": -0.25,
    },
}


def rank_candidates(
    candidates: list[NutritionCandidate],
    query: NormalizedFoodQuery,
) -> list[NutritionCandidate]:
    ranked = [_score_candidate(candidate, query) for candidate in candidates]
    return sorted(ranked, key=lambda item: item.match_score or 0.0, reverse=True)


def _score_candidate(candidate: NutritionCandidate, query: NormalizedFoodQuery) -> NutritionCandidate:
    components: dict[str, float] = {}
    candidate_name = normalize_food_query(candidate.name)
    query_name = normalize_food_query(query.canonical_query)

    components["name"] = _name_score(candidate_name, query_name)
    components["source"] = SOURCE_PRIORITY.get(query.query_kind, {}).get(candidate.source, 0.0)
    components["brand"] = _brand_score(query, candidate)
    components["restaurant"] = _restaurant_score(query, candidate)
    components["region"] = _optional_exact_score(query.region, candidate.region, positive=0.06, missing=0.0)
    components["serving"] = 0.08 if _has_metric_grams(candidate) else -0.04
    components["macro_complete"] = 0.16 if candidate.values_per_100g and candidate.values_per_100g.has_required_macros() else -0.25
    components["type"] = _type_score(query, candidate)
    components["missing_tokens"] = _missing_token_penalty(query, candidate)
    components["preparation"] = _preparation_penalty(query, candidate)
    total = sum(components.values())
    return candidate.model_copy(update={"match_score": round(total, 4), "score_components": components})


def _name_score(candidate_name: str, query_name: str) -> float:
    if not candidate_name or not query_name:
        return 0.0
    if candidate_name == query_name:
        return 0.34
    if query_name in candidate_name or candidate_name in query_name:
        return 0.26
    candidate_tokens = set(candidate_name.split())
    query_tokens = set(query_name.split())
    if not candidate_tokens or not query_tokens:
        return 0.0
    token_overlap = len(candidate_tokens & query_tokens) / len(query_tokens)
    similarity = SequenceMatcher(a=candidate_name, b=query_name).ratio()
    return max(0.18 * token_overlap, 0.16 * similarity)


def _optional_exact_score(
    expected: str | None,
    actual: str | None,
    *,
    positive: float,
    missing: float,
) -> float:
    if not expected:
        return 0.0
    if not actual:
        return missing
    return positive if normalize_food_query(expected) == normalize_food_query(actual) else -positive


def _brand_score(query: NormalizedFoodQuery, candidate: NutritionCandidate) -> float:
    if not query.brand:
        return 0.0
    expected = normalize_food_query(query.brand)
    haystack = normalize_food_query(" ".join(part for part in (candidate.brand, candidate.name, candidate.description) if part))
    return 0.18 if expected in haystack else -0.08


def _restaurant_score(query: NormalizedFoodQuery, candidate: NutritionCandidate) -> float:
    if not query.restaurant:
        return 0.0
    haystack = normalize_food_query(" ".join(part for part in (candidate.brand, candidate.name, candidate.description) if part))
    expected = normalize_food_query(query.restaurant)
    return 0.18 if expected in haystack else -0.08


def _missing_token_penalty(query: NormalizedFoodQuery, candidate: NutritionCandidate) -> float:
    haystack = normalize_food_query(" ".join(part for part in (candidate.brand, candidate.name, candidate.description) if part))
    excluded = {"and", "with", "the", "for", "per", "во", "со", "с", "и", "g", "г"}
    if query.brand:
        excluded.update(normalize_food_query(query.brand).split())
    if query.restaurant:
        excluded.update(normalize_food_query(query.restaurant).split())
    tokens = [
        token
        for token in normalize_food_query(query.canonical_query).split()
        if len(token) > 2 and not token.isdigit() and token not in excluded
    ]
    missing = [token for token in tokens if token not in haystack]
    if not missing:
        return 0.0
    primary_penalty = 0.24 if tokens and tokens[0] in missing else 0.0
    secondary_missing = [token for token in missing if not tokens or token != tokens[0]]
    return -min(0.36, primary_penalty + 0.06 * len(secondary_missing))


def _preparation_penalty(query: NormalizedFoodQuery, candidate: NutritionCandidate) -> float:
    haystack = normalize_food_query(" ".join(part for part in (candidate.name, candidate.description) if part))
    query_text = normalize_food_query(" ".join(part for part in (query.canonical_query, query.preparation) if part))
    unrequested_terms = {
        "dehydrated",
        "powder",
        "dried",
        "baked",
        "breaded",
        "microwaved",
        "fried",
        "canned",
        "candied",
        "sweetened",
        "imitation",
    }
    hits = [term for term in unrequested_terms if term in haystack and term not in query_text]
    return -min(0.24, 0.08 * len(hits))


def _has_metric_grams(candidate: NutritionCandidate) -> bool:
    unit = normalize_food_query(candidate.metric_serving_unit or "")
    return candidate.metric_serving_amount is not None and unit in {"g", "gram", "grams"}


def _type_score(query: NormalizedFoodQuery, candidate: NutritionCandidate) -> float:
    if query.query_kind == "branded_product":
        return 0.10 if candidate.food_type == "branded" else -0.06
    if query.query_kind == "restaurant_menu_item":
        return 0.10 if candidate.food_type in {"restaurant", "branded"} else -0.04
    if query.query_kind == "standard_prepared_dish":
        data_type = str(candidate.metadata.get("data_type", "")).lower()
        if "survey" in data_type or "fndds" in data_type:
            return 0.12
        return 0.06 if candidate.food_type == "prepared" else 0.0
    if query.query_kind == "generic_ingredient":
        data_type = str(candidate.metadata.get("data_type", "")).lower()
        if "foundation" in data_type or "sr legacy" in data_type:
            return 0.12
        return 0.06 if candidate.food_type == "generic" else 0.0
    return 0.0
