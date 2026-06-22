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
CriticSource = Literal["deterministic", "llm"]


class CriticResult(BaseModel):
    action: CriticAction = "accept"
    issues: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    source: CriticSource = "deterministic"
    iteration: int = Field(default=0, ge=0)
