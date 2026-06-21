from app.graph.state import NutritionGraphState
from app.i18n import default_clarification_question, largest_portions_question, state_language
from app.schemas.outputs import CriticResult, FinalEstimate


def critic(state: NutritionGraphState) -> NutritionGraphState:
    final = state.get("final_estimate")
    totals = state.get("totals")
    meal = state.get("meal")
    language = state_language(state)
    issues: list[str] = []

    if final is None:
        return {"critic_result": CriticResult(action="refuse", issues=["missing final answer"])}

    if final.is_refusal or final.is_clarification:
        return {"critic_result": CriticResult(action="accept")}

    if meal and meal.needs_clarification:
        return {
            "critic_result": CriticResult(
                action="clarify",
                issues=["meal parser requested clarification"],
                clarification_question=meal.clarification_question
                or default_clarification_question(language),
            )
        }

    if totals is None:
        return {
            "critic_result": CriticResult(
                action="clarify",
                issues=["missing deterministic totals"],
                clarification_question=default_clarification_question(language),
            )
        }

    calories = totals.calories_kcal
    valid_zero_calorie_product = any(
        diagnostic.food_category == "zero_sugar_soft_drink"
        and diagnostic.selected_identity is not None
        for diagnostic in state.get("retrieval_diagnostics", [])
    )
    if calories.max <= 0 and not valid_zero_calorie_product:
        return {
            "critic_result": CriticResult(
                action="clarify",
                issues=["zero calorie estimate"],
                clarification_question=default_clarification_question(language),
            )
        }

    width = calories.max - calories.min
    ratio = calories.max / max(calories.min, 1)
    if width > 900 or ratio > 2.3:
        return {
            "critic_result": CriticResult(
                action="clarify",
                issues=["estimate range is too wide"],
                clarification_question=largest_portions_question(language),
            )
        }

    for label, macro_range in (
        ("protein", totals.protein_g),
        ("fat", totals.fat_g),
        ("carbs", totals.carbs_g),
    ):
        if macro_range.max < macro_range.min:
            issues.append(f"{label} range is inverted")

    if issues:
        return {"critic_result": CriticResult(action="revise", issues=issues, revised_text=final.text)}
    return {"critic_result": CriticResult(action="accept")}


def route_after_critic(state: NutritionGraphState) -> str:
    result = state.get("critic_result", CriticResult())
    if result.action == "clarify":
        return "ask_clarification"
    if result.action == "refuse":
        return "refuse"
    return "output_moderation"


def apply_critic_revision(state: NutritionGraphState) -> NutritionGraphState:
    result = state.get("critic_result")
    final = state.get("final_estimate")
    if result and result.revised_text and final:
        return {"final_estimate": FinalEstimate(**{**final.model_dump(), "text": result.revised_text})}
    return {}
