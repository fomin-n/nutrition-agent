from typing import TypedDict

from app.schemas.inputs import NormalizedInput, UserInput
from app.schemas.nutrition import (
    IngredientNutrition,
    MealUnderstanding,
    NutritionTotals,
    RetrievalDiagnostic,
    RetrievalFailure,
)
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
    critic_history: list[CriticResult]
    critic_feedback: list[str]
    critic_iteration: int
    errors: list[str]
    use_llm: bool
    memory_context: dict
    request_id: str
    retrieval_failures: list[RetrievalFailure]
    retrieval_diagnostics: list[RetrievalDiagnostic]
