
from pydantic import BaseModel, Field, model_validator

from app.schemas.safety import Confidence


class IngredientEstimate(BaseModel):
    name: str = Field(..., min_length=1)
    grams_min: float = Field(..., ge=0)
    grams_max: float = Field(..., ge=0)
    preparation: str | None = None
    notes: str | None = None
    confidence: Confidence = "medium"

    @model_validator(mode="after")
    def validate_range(self) -> "IngredientEstimate":
        if self.grams_max < self.grams_min:
            self.grams_min, self.grams_max = self.grams_max, self.grams_min
        if self.grams_min == 0 and self.grams_max == 0:
            raise ValueError("ingredient gram range cannot be all zero")
        return self


class MealUnderstanding(BaseModel):
    dish_name: str | None = None
    ingredients: list[IngredientEstimate] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"
    needs_clarification: bool = False
    clarification_question: str | None = None


class NutritionPer100g(BaseModel):
    food_name: str
    calories_kcal: float = Field(..., ge=0)
    protein_g: float = Field(..., ge=0)
    fat_g: float = Field(..., ge=0)
    carbs_g: float = Field(..., ge=0)
    source: str
    source_id: str | None = None


class IngredientNutrition(BaseModel):
    ingredient_name: str
    matched_food_name: str
    grams_min: float = Field(..., ge=0)
    grams_max: float = Field(..., ge=0)
    per_100g: NutritionPer100g
    source: str
    warning: str | None = None


class MacroRange(BaseModel):
    min: float = Field(..., ge=0)
    max: float = Field(..., ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> "MacroRange":
        if self.max < self.min:
            self.min, self.max = self.max, self.min
        return self


class NutritionTotals(BaseModel):
    calories_kcal: MacroRange
    protein_g: MacroRange
    fat_g: MacroRange
    carbs_g: MacroRange
    warnings: list[str] = Field(default_factory=list)


