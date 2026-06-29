import logging
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

LOGGER = logging.getLogger(__name__)


def synthesize_answer(state: NutritionGraphState) -> NutritionGraphState:
    LOGGER.info(
        "Deterministic answer synthesis critic_iteration=%d feedback_count=%d",
        state.get("critic_iteration", 0),
        len(state.get("critic_feedback", [])),
    )
    meal = state.get("meal")
    totals = state.get("totals")
    language = state_language(state)
    failures = state.get("retrieval_failures", [])
    items = state.get("ingredient_nutrition", [])
    if failures and not _has_usable_partial_estimate(items, failures):
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

    confidence = _combined_confidence(meal, totals, has_failures=bool(failures))
    normalized = state.get("normalized_input")
    normalized_text = normalized.text if normalized and normalized.text else ""
    if len(items) >= 2 and _is_comparison_request(normalized_text):
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
    if failures:
        foods = ", ".join(failure.ingredient_name for failure in failures[:3])
        assumptions = [
            *assumptions,
            (
                f"Частичная оценка: надежные данные не найдены для {foods}; "
                "их вклад не включен в итог."
                if language == "ru"
                else f"Partial estimate: reliable data was unavailable for {foods}; "
                "their contribution is not included."
            ),
        ]
    text = _format_estimate(totals, assumptions, confidence, language=language)
    if confidence == "low":
        text = f"{text}\n{_optional_refinement_note(language)}"
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
    assumption_lines = "\n".join(f"• {assumption}" for assumption in assumptions)
    if not assumption_lines:
        assumption_lines = (
            "• Приняты стандартные видимые или указанные порции."
            if language == "ru"
            else "• Standard visible/mentioned portions."
        )
    calories = _format_range(totals.calories_kcal.min, totals.calories_kcal.max)
    protein = _format_range(totals.protein_g.min, totals.protein_g.max)
    fat = _format_range(totals.fat_g.min, totals.fat_g.max)
    carbs = _format_range(totals.carbs_g.min, totals.carbs_g.max)
    confidence_line = _format_confidence(confidence, language)
    if language == "ru":
        return (
            f"🔥 Калории: {calories} ккал\n\n"
            f"Белки: {protein} г  •  Жиры: {fat} г  •  Углеводы: {carbs} г\n\n"
            "📋 Допущения:\n"
            f"{assumption_lines}\n\n"
            f"{confidence_line}"
        )
    return (
        f"🔥 Calories: {calories} kcal\n\n"
        f"Protein: {protein} g  •  Fat: {fat} g  •  Carbs: {carbs} g\n\n"
        "📋 Assumptions:\n"
        f"{assumption_lines}\n\n"
        f"{confidence_line}"
    )


def _confidence_label(confidence: Confidence, language: str) -> str:
    if language != "ru":
        return {"low": "Low", "medium": "Medium", "high": "High"}[confidence]
    return {"low": "низкая", "medium": "средняя", "high": "высокая"}[confidence]


def _format_confidence(confidence: Confidence, language: str) -> str:
    prefix = {"low": "🔴", "medium": "🟡", "high": "🟢"}[confidence]
    label = _confidence_label(confidence, language)
    if language == "ru":
        return f"{prefix} Уверенность: {label}"
    return f"{prefix} Confidence: {label}"


def _combined_confidence(
    meal: MealUnderstanding,
    totals: NutritionTotals,
    *,
    has_failures: bool = False,
) -> Confidence:
    if totals.warnings or has_failures:
        return "low"
    return meal.confidence


def _has_usable_partial_estimate(items: list, failures: list) -> bool:
    return bool(items and len(items) >= len(failures))


def _optional_refinement_note(language: str) -> str:
    if language == "ru":
        return "💡 Для более точной оценки можно указать вес порции, рецепт и добавки."
    return "💡 For a more precise estimate, provide the portion weight, recipe, and additions."


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
        lines = ["🔥 Сравнение калорийности", ""]
        for name, grams_min, grams_max, item_totals, _ in rows:
            weight = _format_weight(grams_min, grams_max, "г")
            calories = _format_range(item_totals.calories_kcal.min, item_totals.calories_kcal.max)
            lines.append(f"• {name} ({weight}): {calories} ккал")
        lines.append("")
        if len(winners) > 1:
            lines.append("Итог: калорийность примерно одинаковая с учетом округления и различий между рынками.")
        else:
            lines.append(f"Итог: больше калорий в {winners[0][0]}.")
        lines.append(_format_confidence(confidence, language))
        return "\n".join(lines)

    lines = ["🔥 Calorie comparison", ""]
    for name, grams_min, grams_max, item_totals, _ in rows:
        weight = _format_weight(grams_min, grams_max, "g")
        calories = _format_range(item_totals.calories_kcal.min, item_totals.calories_kcal.max)
        lines.append(f"• {name} ({weight}): {calories} kcal")
    lines.append("")
    if len(winners) > 1:
        lines.append("Result: they are approximately equal after rounding and market variation.")
    else:
        lines.append(f"Result: {winners[0][0]} has more calories.")
    lines.append(_format_confidence(confidence, language))
    return "\n".join(lines)


def _format_weight(minimum: float, maximum: float, unit: str) -> str:
    if minimum == maximum:
        return f"{minimum:.0f} {unit}"
    return f"{minimum:.0f}–{maximum:.0f} {unit}"


def _format_range(minimum: float, maximum: float) -> str:
    if minimum == maximum:
        return f"{minimum:.0f}"
    return f"{minimum:.0f}–{maximum:.0f}"
