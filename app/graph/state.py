from typing import TypedDict

from app.schemas.inputs import NormalizedInput, UserInput
from app.schemas.nutrition import IngredientNutrition, MealUnderstanding, NutritionTotals
from app.schemas.outputs import CriticResult, FinalEstimate
from app.schemas.safety import ModerationDecision, ScopeDecision


class NutritionGraphState(TypedDict, total=False):
    user_input: UserInput | dict
    normalized_input: NormalizedInput
    input_moderation: ModerationDecision
    scope_decision: ScopeDecision
    meal: MealUnderstanding
    ingredient_nutrition: list[IngredientNutrition]
    totals: NutritionTotals
    final_estimate: FinalEstimate
    critic_result: CriticResult
    errors: list[str]
    use_llm: bool

