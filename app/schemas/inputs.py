from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.i18n import LanguageCode


class UserInput(BaseModel):
    """Raw request entering the graph."""

    text: str | None = Field(default=None, description="User text or photo caption.")
    image_path: str | None = Field(default=None, description="Temporary local image path.")
    image_mime_type: str | None = Field(default=None, description="Best-effort image MIME type.")
    source: Literal["telegram", "cli", "test", "phoenix_eval"] = "telegram"

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.strip().split())
        return cleaned or None

    @field_validator("image_path")
    @classmethod
    def validate_image_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return str(Path(value))


class NormalizedInput(BaseModel):
    text: str | None = None
    image_path: str | None = None
    image_mime_type: str | None = None
    has_text: bool = False
    has_image: bool = False
    language: LanguageCode = "unknown"
