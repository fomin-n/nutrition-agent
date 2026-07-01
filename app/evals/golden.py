import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ExpectedBehavior = Literal["estimate", "clarify", "refuse"]
InputKind = Literal["single_turn", "conversation"]

DEFAULT_GOLDEN_DATASET = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "datasets"
    / "nutrition_agent_phoenix_eval_datasets_v2.jsonl"
)


class GoldenTurn(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str | None = None
    image_path: str | None = None
    image_mime_type: str | None = None
    source: str = "phoenix_eval"


class GoldenInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: InputKind
    user_input: GoldenTurn | None = None
    turns: list[GoldenTurn] = Field(default_factory=list)
    use_llm: bool = False
    language: str

    @model_validator(mode="after")
    def validate_kind_payload(self) -> "GoldenInput":
        if self.kind == "single_turn" and self.user_input is None:
            raise ValueError("single_turn input requires user_input")
        if self.kind == "conversation" and not self.turns:
            raise ValueError("conversation input requires at least one turn")
        return self


class GoldenOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    expected_behavior: ExpectedBehavior
    reference_answer: str | None = None
    nutrition: dict[str, Any] | None = None
    acceptable_range: dict[str, float] | None = None
    checks: dict[str, Any] = Field(default_factory=dict)
    expected_effective_text_after_followup: str | None = None
    expected_memory_assertions: dict[str, bool] = Field(default_factory=dict)


class GoldenMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(..., min_length=1)
    language: str | None = None
    category: str | None = None
    difficulty: str | None = None
    tags: list[str] = Field(default_factory=list)


class GoldenExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: GoldenInput
    output: GoldenOutput
    metadata: GoldenMetadata
    splits: list[str] = Field(..., min_length=1)


def load_golden_examples(
    path: str | Path = DEFAULT_GOLDEN_DATASET,
    *,
    split: str | None = None,
    tags: Sequence[str] = (),
) -> list[GoldenExample]:
    dataset_path = Path(path)
    examples: list[GoldenExample] = []
    for line_number, line in enumerate(dataset_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            example = GoldenExample.model_validate(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"Invalid golden JSONL at {dataset_path}:{line_number}: {exc}") from exc
        examples.append(example)

    ids = [example.metadata.id for example in examples]
    duplicates = sorted({example_id for example_id in ids if ids.count(example_id) > 1})
    if duplicates:
        raise ValueError(f"Duplicate golden example IDs: {', '.join(duplicates)}")

    required_tags = set(tags)
    return [
        example
        for example in examples
        if (split is None or split in example.splits)
        and required_tags.issubset(set(example.metadata.tags))
    ]


def evaluate_answer(
    example: GoldenExample,
    answer: str,
    *,
    parsed_nutrition_override: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    actual_behavior = classify_answer_behavior(answer)
    checks = example.output.checks
    contain_key = (
        "final_answer_must_contain_any"
        if example.input.kind == "conversation"
        else "must_contain_any"
    )
    not_contain_key = (
        "final_answer_must_not_contain_any"
        if example.input.kind == "conversation"
        else "must_not_contain_any"
    )
    must_contain = [str(value) for value in checks.get(contain_key, [])]
    must_not_contain = [str(value) for value in checks.get(not_contain_key, [])]
    answer_folded = _normalize_text_match(answer)
    contained = [value for value in must_contain if _normalize_text_match(value) in answer_folded]
    forbidden = [value for value in must_not_contain if _normalize_text_match(value) in answer_folded]
    parsed_nutrition = parsed_nutrition_override or parse_nutrition_ranges(answer)
    numeric = _evaluate_numeric_ranges(example.output.acceptable_range, parsed_nutrition)
    numeric_metrics = evaluate_numeric_magnitude(example.output.nutrition, parsed_nutrition)

    failed_checks: list[str] = []
    unknown_checks: list[str] = []
    if actual_behavior != example.output.expected_behavior:
        failed_checks.append(
            f"behavior: expected {example.output.expected_behavior}, got {actual_behavior}"
        )
    if must_contain and not contained:
        failed_checks.append(f"must_contain_any: none of {must_contain!r} found")
    if forbidden:
        failed_checks.append(f"must_not_contain_any: found {forbidden!r}")
    if numeric["required_calorie_check"] == "fail":
        failed_checks.append("calories: predicted range does not overlap acceptable range")
    elif numeric["required_calorie_check"] == "unknown":
        unknown_checks.append("calories: answer could not be parsed")

    status = "fail" if failed_checks else "unknown" if unknown_checks else "pass"

    return {
        "expected_behavior": example.output.expected_behavior,
        "actual_behavior": actual_behavior,
        "text_checks": {
            "must_contain_any": must_contain,
            "matched": contained,
            "must_not_contain_any": must_not_contain,
            "forbidden_matches": forbidden,
        },
        "parsed_nutrition": parsed_nutrition,
        "numeric_checks": numeric,
        "numeric_metrics": numeric_metrics,
        "failed_checks": failed_checks,
        "unknown_checks": unknown_checks,
        "status": status,
        "passed": status == "pass",
    }


def classify_answer_behavior(answer: str) -> Literal["estimate", "clarify", "refuse", "unknown"]:
    folded = answer.casefold()
    refusal_markers = (
        "can't help",
        "cannot help",
        "can’t help",
        "не могу помочь",
        "с этим запросом я не могу",
    )
    clarification_markers = (
        "need one more detail",
        "please clarify",
        "what foods are in",
        "нужно еще немного информации",
        "нужно ещё немного информации",
        "уточните",
        "пришлите описание",
        "опишите блюдо",
    )
    if any(marker in folded for marker in refusal_markers):
        return "refuse"
    if any(marker in folded for marker in clarification_markers):
        return "clarify"
    if (
        "kcal" in folded
        or "ккал" in folded
        or "estimated calories" in folded
        or "оценка калорий" in folded
        or "calories:" in folded
        or "калории:" in folded
    ):
        return "estimate"
    return "unknown"


def parse_nutrition_ranges(answer: str) -> dict[str, dict[str, float]]:
    labels = {
        "calories_kcal": ("calories", "estimated calories", "калории", "оценка калорий"),
        "protein_g": ("protein", "белки"),
        "fat_g": ("fat", "жиры"),
        "carbs_g": ("carbs", "углеводы"),
    }
    parsed: dict[str, dict[str, float]] = {}
    number_range = (
        r"(?P<minimum>\d+(?:[.,]\d+)?)"
        r"(?:"
        r"\s*(?:±|\+/-|\+\/-)\s*(?P<delta>\d+(?:[.,]\d+)?)"
        r"|"
        r"\s*[-–—]\s*(?P<maximum>\d+(?:[.,]\d+)?)"
        r")?"
    )
    for nutrient, nutrient_labels in labels.items():
        label_pattern = "|".join(re.escape(label) for label in nutrient_labels)
        match = re.search(rf"(?:{label_pattern})\s*:\s*{number_range}", answer, re.IGNORECASE)
        if match is None:
            continue
        minimum = float(match.group("minimum").replace(",", "."))
        delta_group = match.group("delta")
        if delta_group:
            delta = float(delta_group.replace(",", "."))
            parsed[nutrient] = {"min": max(0.0, minimum - delta), "max": minimum + delta}
            continue
        maximum_group = match.group("maximum")
        maximum = float(maximum_group.replace(",", ".")) if maximum_group else minimum
        parsed[nutrient] = {"min": min(minimum, maximum), "max": max(minimum, maximum)}
    return parsed


def evaluate_numeric_magnitude(
    nutrition: dict[str, Any] | None,
    parsed: dict[str, dict[str, float]],
) -> dict[str, dict[str, float | bool | None]]:
    if not nutrition:
        return {}
    metrics: dict[str, dict[str, float | bool | None]] = {}
    for nutrient in ("calories_kcal", "protein_g", "fat_g", "carbs_g"):
        actual = _float_or_none(nutrition.get(nutrient))
        predicted = parsed.get(nutrient)
        metrics[nutrient] = _numeric_metric(actual, predicted)
    return metrics


def _numeric_metric(
    actual: float | None,
    predicted: dict[str, float] | None,
) -> dict[str, float | bool | None]:
    if actual is None or predicted is None:
        return {
            "actual": actual,
            "predicted_min": None,
            "predicted_max": None,
            "predicted_midpoint": None,
            "absolute_error": None,
            "percentage_error": None,
            "predicted_width": None,
            "normalized_width": None,
            "within_prediction_range": None,
            "interval_score": None,
        }
    predicted_min = predicted["min"]
    predicted_max = predicted["max"]
    midpoint = (predicted_min + predicted_max) / 2
    width = predicted_max - predicted_min
    absolute_error = abs(midpoint - actual)
    percentage_error = (absolute_error / actual) * 100 if actual else None
    normalized_width = width / midpoint if midpoint else None
    within_prediction_range = predicted_min <= actual <= predicted_max
    interval_score = _interval_score(
        actual=actual,
        predicted_min=predicted_min,
        predicted_max=predicted_max,
    )
    return {
        "actual": actual,
        "predicted_min": predicted_min,
        "predicted_max": predicted_max,
        "predicted_midpoint": midpoint,
        "absolute_error": absolute_error,
        "percentage_error": percentage_error,
        "predicted_width": width,
        "normalized_width": normalized_width,
        "within_prediction_range": within_prediction_range,
        "interval_score": interval_score,
    }


def _interval_score(
    *,
    actual: float,
    predicted_min: float,
    predicted_max: float,
    alpha: float = 0.1,
) -> float:
    width = predicted_max - predicted_min
    if actual < predicted_min:
        return width + (2 / alpha) * (predicted_min - actual)
    if actual > predicted_max:
        return width + (2 / alpha) * (actual - predicted_max)
    return width


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _evaluate_numeric_ranges(
    acceptable: dict[str, float] | None,
    parsed: dict[str, dict[str, float]],
) -> dict[str, Any]:
    if not acceptable:
        return {"required_calorie_check": "not_applicable", "nutrients": {}}

    nutrients: dict[str, dict[str, Any]] = {}
    for nutrient in ("calories_kcal", "protein_g", "fat_g", "carbs_g"):
        expected_min = acceptable.get(f"{nutrient}_min")
        expected_max = acceptable.get(f"{nutrient}_max")
        predicted = parsed.get(nutrient)
        if expected_min is None or expected_max is None:
            status = "not_applicable"
        elif predicted is None:
            status = "unknown"
        else:
            overlaps = predicted["max"] >= expected_min and predicted["min"] <= expected_max
            status = "pass" if overlaps else "fail"
        nutrients[nutrient] = {
            "status": status,
            "strict": nutrient == "calories_kcal",
            "acceptable_min": expected_min,
            "acceptable_max": expected_max,
            "predicted": predicted,
        }
    return {
        "required_calorie_check": nutrients["calories_kcal"]["status"],
        "nutrients": nutrients,
    }


def _normalize_text_match(value: str) -> str:
    return value.casefold().replace("’", "'").replace("‘", "'")
