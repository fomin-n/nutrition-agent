import re

from app.graph.nodes.calculator import calculate_totals
from app.graph.state import NutritionGraphState
from app.i18n import (
    default_clarification_question,
    localize_clarification_question,
    response_language,
    state_language,
)
from app.schemas.nutrition import MealUnderstanding, NutritionTotals
from app.schemas.outputs import FinalEstimate
from app.schemas.safety import Confidence


def synthesize_answer(state: NutritionGraphState) -> NutritionGraphState:
    meal = state.get("meal")
    totals = state.get("totals")
    language = state_language(state)
    failures = state.get("retrieval_failures", [])
    if failures:
        foods = ", ".join(failure.ingredient_name for failure in failures[:3])
        if language == "ru":
            text = (
                f"Не удалось найти надежные данные о питательной ценности для: {foods}. "
                "Уточните бренд, размер порции или пришлите фото этикетки."
            )
        else:
            text = (
                f"I couldn't find reliable nutrition data for: {foods}. "
                "Please provide the brand, serving size, or a photo of the nutrition label."
            )
        return {
            "final_estimate": FinalEstimate(
                text=text,
                confidence="low",
                is_clarification=True,
            )
        }
    if meal is None or totals is None or not meal.ingredients:
        question = localize_clarification_question(
            meal.clarification_question if meal else None,
            language,
        )
        if not question:
            question = default_clarification_question(language)
        if language == "ru":
            text = f"Нужно еще немного информации для надежной оценки: {question}"
        else:
            text = f"I need one more detail to estimate this reliably: {question}"
        return {
            "final_estimate": FinalEstimate(
                text=text,
                confidence="low",
                is_clarification=True,
            )
        }

    confidence = _combined_confidence(meal, totals)
    items = state.get("ingredient_nutrition", [])
    normalized = state.get("normalized_input")
    if len(items) >= 2 and _is_comparison_request(normalized.text if normalized else ""):
        return {
            "final_estimate": FinalEstimate(
                text=_format_calorie_comparison(items, language=language, confidence=confidence),
                confidence=confidence,
                is_refusal=False,
                is_clarification=False,
            )
        }
    assumptions = meal.assumptions or [
        f"{item.ingredient_name}: {round(item.grams_min)}-{round(item.grams_max)} g."
        for item in state.get("ingredient_nutrition", [])
    ]
    text = _format_estimate(totals, assumptions, confidence, language=language)
    return {
        "final_estimate": FinalEstimate(
            text=text,
            confidence=confidence,
            is_refusal=False,
            is_clarification=False,
            totals=totals,
        )
    }


def _format_estimate(
    totals: NutritionTotals,
    assumptions: list[str],
    confidence: Confidence,
    *,
    language: str = "en",
) -> str:
    language = response_language(language)
    assumption_lines = "\n".join(f"* {assumption}" for assumption in assumptions[:8])
    if not assumption_lines:
        assumption_lines = (
            "* Приняты стандартные видимые или указанные порции."
            if language == "ru"
            else "* Standard visible/mentioned portions."
        )
    if language == "ru":
        return (
            f"Оценка калорий: {totals.calories_kcal.min:.0f}-{totals.calories_kcal.max:.0f} ккал\n"
            f"Белки: {totals.protein_g.min:.0f}-{totals.protein_g.max:.0f} г\n"
            f"Жиры: {totals.fat_g.min:.0f}-{totals.fat_g.max:.0f} г\n"
            f"Углеводы: {totals.carbs_g.min:.0f}-{totals.carbs_g.max:.0f} г\n"
            "Основные допущения:\n"
            f"{assumption_lines}\n"
            f"Уверенность: {_confidence_label(confidence, language)}"
        )
    return (
        f"Estimated calories: {totals.calories_kcal.min:.0f}-{totals.calories_kcal.max:.0f} kcal\n"
        f"Protein: {totals.protein_g.min:.0f}-{totals.protein_g.max:.0f} g\n"
        f"Fat: {totals.fat_g.min:.0f}-{totals.fat_g.max:.0f} g\n"
        f"Carbs: {totals.carbs_g.min:.0f}-{totals.carbs_g.max:.0f} g\n"
        "Main assumptions:\n"
        f"{assumption_lines}\n"
        f"Confidence: {confidence}"
    )


def _confidence_label(confidence: Confidence, language: str) -> str:
    if language != "ru":
        return confidence
    return {"low": "низкая", "medium": "средняя", "high": "высокая"}[confidence]


def _combined_confidence(meal: MealUnderstanding, totals: NutritionTotals) -> Confidence:
    if totals.warnings:
        return "low"
    return meal.confidence


def _is_comparison_request(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    patterns = (
        r"\bгде\s+больше\s+калор",
        r"\bв\s+чем\s+больше\s+калор",
        r"\bчто\s+калорийн",
        r"\bwhich\s+(?:one\s+)?has\s+more\s+calor",
        r"\bwhat\s+has\s+more\s+calor",
        r"\bmore\s+calories",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)


def _format_calorie_comparison(items, *, language: str, confidence: Confidence) -> str:
    rows = []
    for item in items:
        item_totals = calculate_totals([item])
        midpoint = (item_totals.calories_kcal.min + item_totals.calories_kcal.max) / 2
        rows.append((item.matched_food_name, item.grams_min, item.grams_max, item_totals, midpoint))

    top_midpoint = max(row[4] for row in rows)
    winners = [row for row in rows if top_midpoint - row[4] <= max(10, top_midpoint * 0.05)]
    language = response_language(language)
    if language == "ru":
        lines = ["Сравнение калорийности:"]
        for name, grams_min, grams_max, item_totals, _ in rows:
            weight = _format_weight(grams_min, grams_max, "г")
            calories = _format_range(item_totals.calories_kcal.min, item_totals.calories_kcal.max)
            lines.append(f"* {name} ({weight}): {calories} ккал")
        if len(winners) > 1:
            lines.append("Калорийность примерно одинаковая с учетом округления и различий между рынками.")
        else:
            lines.append(f"Больше калорий в {winners[0][0]}.")
        lines.append(f"Уверенность: {_confidence_label(confidence, language)}")
        return "\n".join(lines)

    lines = ["Calorie comparison:"]
    for name, grams_min, grams_max, item_totals, _ in rows:
        weight = _format_weight(grams_min, grams_max, "g")
        calories = _format_range(item_totals.calories_kcal.min, item_totals.calories_kcal.max)
        lines.append(f"* {name} ({weight}): {calories} kcal")
    if len(winners) > 1:
        lines.append("They are approximately equal after rounding and market variation.")
    else:
        lines.append(f"{winners[0][0]} has more calories.")
    lines.append(f"Confidence: {confidence}")
    return "\n".join(lines)


def _format_weight(minimum: float, maximum: float, unit: str) -> str:
    if minimum == maximum:
        return f"{minimum:.0f} {unit}"
    return f"{minimum:.0f}-{maximum:.0f} {unit}"


def _format_range(minimum: float, maximum: float) -> str:
    if minimum == maximum:
        return f"{minimum:.0f}"
    return f"{minimum:.0f}-{maximum:.0f}"
