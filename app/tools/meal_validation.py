"""Shared semantic boundary for local, text, product and vision extraction."""

from app.i18n import LanguageCode, default_clarification_question
from app.schemas.nutrition import MealUnderstanding
from app.tools.food_normalization import (
    UNIT_GRAMS,
    estimate_portion,
    extract_quantity_mentions,
    extract_total_portion_grams,
    find_food_mentions,
    is_mass_quantity,
)


def validate_meal(
    meal: MealUnderstanding, text: str = "", *, allow_observed_label: bool = False
) -> list[str]:
    if meal.needs_clarification:
        return []
    failures = []
    if not meal.ingredients:
        failures.append("no_ingredients")
    if len(meal.ingredients) > 12:
        failures.append("too_many_ingredients")
    for item in meal.ingredients:
        if item.observed_label is not None and not allow_observed_label:
            failures.append("nutrition_label_requires_packaging_image")
        midpoint = (item.grams_min + item.grams_max) / 2
        if item.grams_max > 2500 or midpoint > 2000:
            failures.append("implausible_ingredient_weight")
        if item.grams_min > 0 and item.grams_max / item.grams_min > 6:
            failures.append("implausibly_wide_ingredient_range")
    mentions = find_food_mentions(text)
    total = extract_total_portion_grams(text, mentions)
    quantities = extract_quantity_mentions(text)
    masses = [q for q in quantities if is_mass_quantity(q)]
    if len(meal.ingredients) == 1 and len(masses) == 1:
        total = masses[0].amount * UNIT_GRAMS[masses[0].unit]
    if total is not None:
        midpoint_sum = sum((item.grams_min + item.grams_max) / 2 for item in meal.ingredients)
        if not 0.70 * total <= midpoint_sum <= 1.30 * total:
            failures.append("component_weights_do_not_match_total")
    # Independent occurrences must survive parsing, whether kept separate or aggregated.
    for canonical in {m.canonical_name for m in mentions}:
        repeated = [m for m in mentions if m.canonical_name == canonical]
        if len(repeated) < 2:
            continue
        portions = [estimate_portion(text, m, mentions) for m in repeated]
        if all(p.explicit for p in portions):
            expected = sum((p.grams_min + p.grams_max) / 2 for p in portions)
            actual = sum(
                (i.grams_min + i.grams_max) / 2
                for i in meal.ingredients
                if any(m.canonical_name == canonical for m in find_food_mentions(i.name))
            )
            if not 0.9 * expected <= actual <= 1.1 * expected:
                failures.append("repeated_food_quantity_lost")
    return sorted(set(failures))


def clarification_meal(language: LanguageCode) -> MealUnderstanding:
    return MealUnderstanding(
        needs_clarification=True,
        confidence="low",
        clarification_question=default_clarification_question(language),
    )
