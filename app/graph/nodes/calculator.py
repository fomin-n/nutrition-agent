import json
import logging

from app.graph.state import NutritionGraphState
from app.schemas.nutrition import IngredientNutrition, MacroRange, NutritionTotals

LOGGER = logging.getLogger(__name__)


def calculate_totals(items: list[IngredientNutrition]) -> NutritionTotals:
    calories_min = calories_max = 0.0
    protein_min = protein_max = 0.0
    fat_min = fat_max = 0.0
    carbs_min = carbs_max = 0.0
    warnings: list[str] = []

    for item in items:
        per_100g = item.per_100g
        min_factor = item.grams_min / 100.0
        max_factor = item.grams_max / 100.0
        calories_min += per_100g.calories_kcal * min_factor
        calories_max += per_100g.calories_kcal * max_factor
        protein_min += per_100g.protein_g * min_factor
        protein_max += per_100g.protein_g * max_factor
        fat_min += per_100g.fat_g * min_factor
        fat_max += per_100g.fat_g * max_factor
        carbs_min += per_100g.carbs_g * min_factor
        carbs_max += per_100g.carbs_g * max_factor
        if item.warning:
            warnings.append(item.warning)

    macro_kcal_min = 4 * protein_min + 9 * fat_min + 4 * carbs_min
    macro_kcal_max = 4 * protein_max + 9 * fat_max + 4 * carbs_max
    if calories_max > 0 and macro_kcal_max > 0:
        lower_ratio = abs(calories_min - macro_kcal_min) / max(calories_min, macro_kcal_min, 1)
        upper_ratio = abs(calories_max - macro_kcal_max) / max(calories_max, macro_kcal_max, 1)
        if lower_ratio > 0.25 or upper_ratio > 0.25:
            warnings.append("Calories differ materially from macro-derived energy; verify source data.")

    return NutritionTotals(
        calories_kcal=MacroRange(min=_round_calories(calories_min), max=_round_calories(calories_max)),
        protein_g=MacroRange(min=round(protein_min), max=round(protein_max)),
        fat_g=MacroRange(min=round(fat_min), max=round(fat_max)),
        carbs_g=MacroRange(min=round(carbs_min), max=round(carbs_max)),
        warnings=dedupe(warnings),
    )


def calculate_macros(state: NutritionGraphState) -> NutritionGraphState:
    items = state.get("ingredient_nutrition", [])
    totals = calculate_totals(items)
    failures = state.get("retrieval_failures", [])
    if items and failures:
        totals = totals.model_copy(
            update={
                "warnings": dedupe(
                    [
                        *totals.warnings,
                        "Partial estimate: one or more ingredients could not be resolved reliably.",
                    ]
                )
            }
        )
    diagnostics = [
        diagnostic.model_copy(update={"calculated_totals": totals.model_dump()})
        for diagnostic in state.get("retrieval_diagnostics", [])
    ]
    LOGGER.info(
        "Nutrition calculation diagnostic=%s",
        json.dumps(
            {
                "request_id": state.get("request_id"),
                "selected_identities": [
                    diagnostic.selected_identity
                    for diagnostic in diagnostics
                    if diagnostic.selected_identity
                ],
                "totals": totals.model_dump(),
                "retrieval_failure_count": len(failures),
            },
            ensure_ascii=True,
        ),
    )
    return {"totals": totals, "retrieval_diagnostics": diagnostics}


def _round_calories(value: float) -> int:
    if value <= 0:
        return 0
    return int(round(value / 10.0) * 10)


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
