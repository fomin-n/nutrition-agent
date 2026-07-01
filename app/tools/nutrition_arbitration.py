from dataclasses import dataclass

from app.schemas.nutrition import CandidateValidationResult, NutritionCandidate
from app.tools.food_query import NormalizedFoodQuery


@dataclass(frozen=True)
class ArbitrationDecision:
    selected_index: int | None
    path: str
    reasons: tuple[str, ...]


def arbitrate_candidate(
    candidates: list[NutritionCandidate],
    validations: list[CandidateValidationResult],
    query: NormalizedFoodQuery,
) -> ArbitrationDecision:
    accepted_indices = [
        index for index, validation in enumerate(validations) if validation.accepted
    ]
    if not accepted_indices:
        return ArbitrationDecision(None, "no_accepted_candidate", ())

    first_index = accepted_indices[0]
    first = candidates[first_index]
    fallback_index = next(
        (
            index
            for index in accepted_indices
            if candidates[index].source == "fallback"
        ),
        None,
    )
    if fallback_index is None:
        return ArbitrationDecision(first_index, "first_valid_no_fallback", ())

    if first.source == "fallback":
        return ArbitrationDecision(first_index, "fallback_ranked_first", ())

    if query.query_kind in {"branded_product", "restaurant_menu_item"}:
        return ArbitrationDecision(first_index, "provider_kept_for_product_identity", ())

    reasons = _weak_provider_reasons(first, candidates[fallback_index], query)
    if reasons:
        return ArbitrationDecision(
            fallback_index,
            "fallback_selected_over_weak_provider",
            tuple(reasons),
        )
    return ArbitrationDecision(first_index, "provider_kept_after_arbitration", ())


def _weak_provider_reasons(
    provider: NutritionCandidate,
    fallback: NutritionCandidate,
    query: NormalizedFoodQuery,
) -> list[str]:
    components = provider.score_components
    reasons: list[str] = []
    score = provider.match_score or 0.0
    name_score = components.get("name", 0.0)
    if score < 0.72:
        reasons.append("provider_match_score_below_threshold")
    if components.get("missing_tokens", 0.0) < 0:
        reasons.append("provider_missing_query_tokens")
    if components.get("preparation", 0.0) < 0:
        reasons.append("provider_preparation_mismatch")
    if components.get("type", 0.0) < 0:
        reasons.append("provider_type_mismatch")
    if _source_is_soft_for_query(provider, query) and score < 0.9:
        reasons.append("provider_source_soft_for_query_kind")
    if name_score < 0.34 and _large_nutrition_disagreement(provider, fallback):
        reasons.append("provider_disagrees_with_grounded_fallback")
    return reasons


def _source_is_soft_for_query(candidate: NutritionCandidate, query: NormalizedFoodQuery) -> bool:
    if query.query_kind == "generic_ingredient":
        return candidate.source in {"fatsecret", "open_food_facts"}
    if query.query_kind == "standard_prepared_dish":
        return candidate.source == "open_food_facts"
    if query.query_kind in {"user_composite_meal", "photo_derived_food"}:
        return candidate.source == "open_food_facts"
    return False


def _large_nutrition_disagreement(
    provider: NutritionCandidate,
    fallback: NutritionCandidate,
) -> bool:
    provider_values = provider.values_per_100g
    fallback_values = fallback.values_per_100g
    if provider_values is None or fallback_values is None:
        return False
    provider_calories = float(provider_values.calories_kcal or 0)
    fallback_calories = float(fallback_values.calories_kcal or 0)
    if fallback_calories and abs(provider_calories - fallback_calories) / fallback_calories > 0.35:
        return True
    for attr in ("protein_g", "fat_g", "carbohydrate_g"):
        provider_value = float(getattr(provider_values, attr) or 0)
        fallback_value = float(getattr(fallback_values, attr) or 0)
        if fallback_value <= 1:
            if provider_value - fallback_value > 8:
                return True
        elif abs(provider_value - fallback_value) / fallback_value > 1.0:
            return True
    return False
