from app.graph.nodes import text_parser
from app.schemas.inputs import NormalizedInput
from app.schemas.nutrition import MealUnderstanding


def test_parse_text_meal_uses_local_food_parse_when_llm_requests_clarification(monkeypatch) -> None:
    monkeypatch.setattr(text_parser, "has_openai_key", lambda: True)
    monkeypatch.setattr(
        text_parser,
        "parse_text_with_llm",
        lambda *_args, **_kwargs: MealUnderstanding(
            ingredients=[],
            needs_clarification=True,
            clarification_question="mock clarification",
        ),
    )

    result = text_parser.parse_text_meal(
        {
            "normalized_input": NormalizedInput(
                text="Сколько калрий в одном зелёном яблоке?",
                has_text=True,
                has_image=False,
                language="ru",
            ),
            "use_llm": True,
        }
    )

    meal = result["meal"]
    assert meal.ingredients
    assert meal.ingredients[0].name == "apple"
    assert not meal.needs_clarification
