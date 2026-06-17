from app.schemas.nutrition import CandidateValidationResult, NutritionCandidate
from app.tools.food_query import NormalizedFoodQuery


def validate_candidate(
    candidate: NutritionCandidate,
    query: NormalizedFoodQuery,
) -> CandidateValidationResult:
    values = candidate.values_per_100g
    reasons: list[str] = []
    if values is None or not values.has_required_macros():
        return CandidateValidationResult(accepted=False, reasons=["missing_required_per_100g_values"])

    calories = float(values.calories_kcal or 0)
    protein = float(values.protein_g or 0)
    fat = float(values.fat_g or 0)
    carbs = float(values.carbohydrate_g or 0)

    if calories > 1000:
        reasons.append("calories_above_plausible_per_100g_limit")
    if any(macro > 100 for macro in (protein, fat, carbs)):
        reasons.append("macro_above_100g_per_100g")
    if candidate.source == "generic_fallback" and (
        query.query_kind == "branded_product" or query.food_category != "unknown"
    ):
        reasons.append("generic_fallback_not_allowed_for_product_or_category")

    name = candidate.name.lower()
    zero_terms = ("zero", "diet", "sugar free", "sugar-free", "без сахара", "зеро")
    candidate_looks_zero = any(term in name for term in zero_terms) or (calories <= 10 and carbs <= 2)
    if query.product_variant == "regular" and candidate_looks_zero:
        reasons.append("regular_query_matched_zero_sugar_candidate")
    if query.product_variant == "zero_sugar" and not candidate_looks_zero:
        reasons.append("zero_sugar_query_matched_regular_candidate")

    if query.food_category == "sugary_soft_drink":
        if protein > 1:
            reasons.append("soft_drink_protein_above_limit")
        if fat > 1:
            reasons.append("soft_drink_fat_above_limit")
        if not 20 <= calories <= 100:
            reasons.append("sugary_soft_drink_calories_out_of_range")
        if not 3 <= carbs <= 20:
            reasons.append("sugary_soft_drink_carbs_out_of_range")
        macro_energy = protein * 4 + fat * 9 + carbs * 4
        if macro_energy and carbs * 4 / macro_energy < 0.9:
            reasons.append("soft_drink_energy_not_primarily_carbohydrate")
    elif query.food_category == "zero_sugar_soft_drink":
        if protein > 1 or fat > 1:
            reasons.append("zero_sugar_soft_drink_has_protein_or_fat")
        if calories > 10 or carbs > 2:
            reasons.append("zero_sugar_soft_drink_energy_or_carbs_above_limit")

    return CandidateValidationResult(accepted=not reasons, reasons=reasons)
