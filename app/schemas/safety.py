from typing import Literal

from pydantic import BaseModel, Field

from app.i18n import LanguageCode

SafetyCategory = Literal[
    "safe",
    "off_topic",
    "unsafe",
    "prompt_injection",
    "medical",
    "hacking",
]

RouteName = Literal[
    "off_topic",
    "unsafe",
    "needs_clarification",
    "text_meal",
    "dish_photo",
    "image_with_text",
    "packaged_food",
]

Confidence = Literal["low", "medium", "high"]


class ModerationDecision(BaseModel):
    allowed: bool = True
    category: SafetyCategory = "safe"
    reason: str = ""


class ScopeDecision(BaseModel):
    route: RouteName
    is_food_related: bool = False
    is_unsafe: bool = False
    needs_clarification: bool = False
    reason: str = ""
    clarification_question: str | None = None
    confidence: Confidence = "medium"
    language: LanguageCode = "unknown"


class Refusal(BaseModel):
    reason: str = Field(..., min_length=1)
    user_message: str = Field(..., min_length=1)
