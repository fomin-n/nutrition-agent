from app.schemas.nutrition import CandidateValidationResult, NutritionCandidate
from app.tools.fallback_nutrition import is_plain_water_query, normalize_food_query
from app.tools.food_query import NormalizedFoodQuery, product_profile_for_canonical


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

    candidate_haystack = normalize_food_query(
        " ".join(
            part
            for part in (candidate.name, candidate.brand, candidate.description)
            if part
        )
    )
    if query.restaurant:
        expected_restaurant = normalize_food_query(query.restaurant)
        if expected_restaurant not in candidate_haystack:
            reasons.append("restaurant_identity_mismatch")
    if query.food_category == "chocolate_bar":
        expected_product = normalize_food_query(query.canonical_query)
        profile = product_profile_for_canonical(query.canonical_query)
        identity_aliases = (profile.canonical_product, *profile.aliases) if profile else (query.canonical_query,)
        if not any(normalize_food_query(alias) in candidate_haystack for alias in identity_aliases):
            reasons.append("chocolate_bar_product_identity_mismatch")
        if not 300 <= calories <= 650:
            reasons.append("chocolate_bar_calories_out_of_range")
        if protein > 20 or not 5 <= fat <= 50 or not 30 <= carbs <= 85:
            reasons.append("chocolate_bar_macros_out_of_range")
        variant_terms = ("ice cream", "protein", "white", "brownie", "dark chocolate")
        if any(term in candidate_haystack and term not in expected_product for term in variant_terms):
            reasons.append("unrequested_chocolate_bar_variant")

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

    if query.food_category == "plain_water":
        if not is_plain_water_query(candidate_haystack):
            reasons.append("plain_water_identity_or_additive_mismatch")
        if calories > 1 or any(macro > 0.5 for macro in (protein, fat, carbs)):
            reasons.append("plain_water_has_calories_or_macros")

    canonical = normalize_food_query(query.canonical_query)
    if canonical == "beef cooked":
        processed_terms = ("salami", "sausage", "cured", "corned", "jerky", "luncheon")
        if any(term in candidate_haystack for term in processed_terms):
            reasons.append("plain_beef_matched_processed_meat")
        if protein < 12 or fat > 35 or carbs > 8:
            reasons.append("plain_beef_macros_out_of_range")
    elif canonical == "potato boiled":
        excluded_terms: tuple[str, ...] = ("fried", "fries", "chips", "salad", "mashed", "gratin")
        if any(term in candidate_haystack for term in excluded_terms):
            reasons.append("boiled_potato_preparation_mismatch")
        if not 45 <= calories <= 150 or fat > 3 or not 8 <= carbs <= 35:
            reasons.append("boiled_potato_macros_out_of_range")
    elif canonical == "milk":
        excluded_terms = (
            "almond",
            "coconut",
            "condensed",
            "crackers",
            "evaporated",
            "goat",
            "malted",
            "oat",
            "powder",
            "soy",
        )
        if any(term in candidate_haystack for term in excluded_terms):
            reasons.append("ordinary_milk_identity_mismatch")
        if not 35 <= calories <= 90 or not 2 <= protein <= 5 or fat > 6 or not 3 <= carbs <= 8:
            reasons.append("ordinary_milk_macros_out_of_range")
    elif canonical in {"borscht", "borscht with sour cream"}:
        if "borscht" not in candidate_haystack and "borsch" not in candidate_haystack:
            reasons.append("borscht_identity_mismatch")
        if not 30 <= calories <= 120 or protein > 10 or fat > 10 or carbs > 20:
            reasons.append("meat_borscht_macros_out_of_range")

    accepted = not reasons
    valid_zero_calories = accepted and query.food_category in {
        "plain_water",
        "zero_sugar_soft_drink",
    }
    return CandidateValidationResult(
        accepted=accepted,
        reasons=reasons,
        valid_zero_calories=valid_zero_calories,
    )
