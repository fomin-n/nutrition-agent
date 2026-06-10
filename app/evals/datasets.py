from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class EvalCase(BaseModel):
    id: str
    text: str
    expected: str
    category: str


def load_adversarial_cases(path: str | Path | None = None) -> list[EvalCase]:
    dataset_path = Path(path) if path else Path(__file__).with_name("adversarial_cases.yaml")
    raw: list[dict[str, Any]] = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    return [EvalCase.model_validate(item) for item in raw]

