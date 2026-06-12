
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.safety import Confidence

FoodSource = Literal["fatsecret", "usda", "open_food_facts", "fallback", "generic_fallback"]
FoodType = Literal["generic", "branded", "restaurant", "prepared", "composite", "unknown"]


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


class NutritionValues(BaseModel):
    calories_kcal: float | None = Field(default=None, ge=0)
    protein_g: float | None = Field(default=None, ge=0)
    carbohydrate_g: float | None = Field(default=None, ge=0)
    fat_g: float | None = Field(default=None, ge=0)
    fiber_g: float | None = Field(default=None, ge=0)
    sugar_g: float | None = Field(default=None, ge=0)
    sodium_mg: float | None = Field(default=None, ge=0)

    def has_required_macros(self) -> bool:
        return None not in (self.calories_kcal, self.protein_g, self.carbohydrate_g, self.fat_g)


class CandidateScore(BaseModel):
    total: float = 0.0
    components: dict[str, float] = Field(default_factory=dict)


class NutritionCandidate(BaseModel):
    source: FoodSource
    source_id: str | None = None
    name: str
    brand: str | None = None
    food_type: FoodType = "unknown"
    description: str | None = None
    region: str | None = None
    language: str | None = None
    serving_description: str | None = None
    serving_amount: float | None = Field(default=None, ge=0)
    serving_unit: str | None = None
    metric_serving_amount: float | None = Field(default=None, ge=0)
    metric_serving_unit: str | None = None
    calories_kcal: float | None = Field(default=None, ge=0)
    protein_g: float | None = Field(default=None, ge=0)
    carbohydrate_g: float | None = Field(default=None, ge=0)
    fat_g: float | None = Field(default=None, ge=0)
    fiber_g: float | None = Field(default=None, ge=0)
    sugar_g: float | None = Field(default=None, ge=0)
    sodium_mg: float | None = Field(default=None, ge=0)
    values_per_100g: NutritionValues | None = None
    source_confidence: Confidence = "medium"
    match_score: float | None = None
    score_components: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_per_100g(self) -> NutritionPer100g | None:
        values = self.values_per_100g
        if values is None or not values.has_required_macros():
            return None
        return NutritionPer100g(
            food_name=self.name,
            calories_kcal=float(values.calories_kcal or 0),
            protein_g=float(values.protein_g or 0),
            fat_g=float(values.fat_g or 0),
            carbs_g=float(values.carbohydrate_g or 0),
            source=self.source,
            source_id=self.source_id,
        )


class IngredientNutrition(BaseModel):
    ingredient_name: str
    matched_food_name: str
    grams_min: float = Field(..., ge=0)
    grams_max: float = Field(..., ge=0)
    per_100g: NutritionPer100g
    source: str
    warning: str | None = None
    candidate: NutritionCandidate | None = None


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
