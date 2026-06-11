from app.graph.state import NutritionGraphState
from app.i18n import default_clarification_question, response_language, state_language
from app.schemas.nutrition import MealUnderstanding, NutritionTotals
from app.schemas.outputs import FinalEstimate
from app.schemas.safety import Confidence


def synthesize_answer(state: NutritionGraphState) -> NutritionGraphState:
    meal = state.get("meal")
    totals = state.get("totals")
    language = state_language(state)
    if meal is None or totals is None or not meal.ingredients:
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
