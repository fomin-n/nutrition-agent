from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ObservedNutritionLabel(BaseModel):
    """Transcribed label numbers, not model-estimated nutrition or meal totals."""

    model_config = ConfigDict(allow_inf_nan=False)
    basis: Literal["per_100g", "per_serving"]
    serving_grams: float | None = Field(default=None, gt=0, le=2500)
    calories_kcal: float = Field(ge=0, le=10000)
    protein_g: float = Field(ge=0, le=2500)
    fat_g: float = Field(ge=0, le=2500)
    carbs_g: float = Field(ge=0, le=2500)

    @model_validator(mode="after")
    def serving_basis_requires_mass(self) -> "ObservedNutritionLabel":
        if self.basis == "per_serving" and self.serving_grams is None:
            raise ValueError("a per-serving label requires a readable serving mass")
        return self


class PackagingObservation(BaseModel):
    is_food: bool
    product_name: str | None = Field(default=None, max_length=240)
    label: ObservedNutritionLabel | None = None
    confidence: Literal["low", "medium", "high"] = "low"
