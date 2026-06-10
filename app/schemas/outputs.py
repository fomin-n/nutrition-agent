from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.nutrition import NutritionTotals
from app.schemas.safety import Confidence


class FinalEstimate(BaseModel):
    text: str = Field(..., min_length=1)
    confidence: Confidence = "medium"
    is_refusal: bool = False
    is_clarification: bool = False
    totals: NutritionTotals | None = None


CriticAction = Literal["accept", "clarify", "refuse", "revise"]


class CriticResult(BaseModel):
    action: CriticAction = "accept"
    issues: list[str] = Field(default_factory=list)
    revised_text: str | None = None
    clarification_question: str | None = None

