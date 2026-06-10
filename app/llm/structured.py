from pathlib import Path
from typing import TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.llm.client import build_chat_model

SchemaT = TypeVar("SchemaT", bound=BaseModel)

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def read_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def invoke_structured_text(
    *,
    model_name: str,
    schema: type[SchemaT],
    system_prompt: str,
    user_prompt: str,
) -> SchemaT:
    model = build_chat_model(model_name).with_structured_output(schema)
    result = model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
    if not isinstance(result, schema):
        return schema.model_validate(result)
    return result

