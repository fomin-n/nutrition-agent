import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class EvalCase(BaseModel):
    id: str
    text: str
    expected: str
    category: str


def load_adversarial_cases(path: str | Path | None = None) -> list[EvalCase]:
    dataset_path = Path(path) if path else Path(__file__).with_name("adversarial_cases.yaml")
    raw: list[dict[str, Any]] = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    return [EvalCase.model_validate(item) for item in raw]


class NutritionGroundTruth(BaseModel):
    calories_kcal: float = Field(..., gt=0)
    protein_g: float | None = Field(default=None, ge=0)
    fat_g: float | None = Field(default=None, ge=0)
    carbs_g: float | None = Field(default=None, ge=0)


class NutritionSourceMetadata(BaseModel):
    dataset: str
    dataset_url: str
    csv_url: str
    license: str
    license_url: str
    restaurant: str
    item: str


class NutritionEvalCase(BaseModel):
    id: str
    input_text: str
    expected_ingredients: list[str] = Field(default_factory=list)
    ground_truth: NutritionGroundTruth
    source: NutritionSourceMetadata


def load_nutrition_cases(path: str | Path | None = None) -> list[NutritionEvalCase]:
    dataset_path = Path(path) if path else Path(__file__).with_name("fastfood_tiny_sample.jsonl")
    cases: list[NutritionEvalCase] = []
    for line_number, line in enumerate(dataset_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {dataset_path}:{line_number}") from exc
        cases.append(NutritionEvalCase.model_validate(raw))
    return cases
