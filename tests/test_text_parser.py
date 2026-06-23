from app.graph.nodes import text_parser
from app.schemas.inputs import NormalizedInput
from app.schemas.nutrition import IngredientEstimate, MealUnderstanding


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


def test_known_packaged_product_bypasses_llm_decomposition(monkeypatch) -> None:
    monkeypatch.setattr(text_parser, "has_openai_key", lambda: True)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("known packaged products should bypass the LLM parser")

    monkeypatch.setattr(text_parser, "parse_text_with_llm", fail_if_called)

    result = text_parser.parse_text_meal(
        {
            "normalized_input": NormalizedInput(
                text="Сколько калорий в Сникерс (50g)?",
                has_text=True,
                has_image=False,
                language="ru",
            ),
            "use_llm": True,
        }
    )

    meal = result["meal"]
    assert [ingredient.name for ingredient in meal.ingredients] == ["Snickers"]
    assert meal.ingredients[0].grams_min == 50
    assert meal.ingredients[0].grams_max == 50


def test_russian_compound_chicken_dish_gets_llm_parser_chance(monkeypatch) -> None:
    called = False
    monkeypatch.setattr(text_parser, "has_openai_key", lambda: True)

    def parse_with_llm(*_args, **_kwargs):
        nonlocal called
        called = True
        return MealUnderstanding(
            dish_name="куриный суп",
            ingredients=[
                IngredientEstimate(
                    name="vegetable soup",
                    grams_min=400,
                    grams_max=400,
                    notes="compound dish fixture",
                )
            ],
        )

    monkeypatch.setattr(text_parser, "parse_text_with_llm", parse_with_llm)

    result = text_parser.parse_text_meal(
        {
            "normalized_input": NormalizedInput(
                text="Сколько БЖУ в тарелке куриного супа 400 г?",
                has_text=True,
                has_image=False,
                language="ru",
            ),
            "use_llm": True,
        }
    )

    meal = result["meal"]
    assert called is True
    assert not meal.needs_clarification
    assert meal.ingredients[0].name == "vegetable soup"


def test_english_compound_chicken_dish_gets_llm_parser_chance(monkeypatch) -> None:
    called = False
    monkeypatch.setattr(text_parser, "has_openai_key", lambda: True)

    def parse_with_llm(*_args, **_kwargs):
        nonlocal called
        called = True
        return MealUnderstanding(
            dish_name="chicken shawarma",
            ingredients=[
                IngredientEstimate(
                    name="chicken breast cooked",
                    grams_min=150,
                    grams_max=200,
                    notes="compound dish fixture",
                )
            ],
        )

    monkeypatch.setattr(text_parser, "parse_text_with_llm", parse_with_llm)

    result = text_parser.parse_text_meal(
        {
            "normalized_input": NormalizedInput(
                text="How many calories in a chicken shawarma?",
                has_text=True,
                has_image=False,
                language="en",
            ),
            "use_llm": True,
        }
    )

    meal = result["meal"]
    assert called is True
    assert not meal.needs_clarification
    assert meal.ingredients[0].name == "chicken breast cooked"


def test_bare_generic_chicken_still_clarifies_without_llm_parser(monkeypatch) -> None:
    monkeypatch.setattr(text_parser, "has_openai_key", lambda: True)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("bare generic chicken should keep the deterministic clarification")

    monkeypatch.setattr(text_parser, "parse_text_with_llm", fail_if_called)

    result = text_parser.parse_text_meal(
        {
            "normalized_input": NormalizedInput(
                text="Сколько калорий в курице?",
                has_text=True,
                has_image=False,
                language="ru",
            ),
            "use_llm": True,
        }
    )

    meal = result["meal"]
    assert meal.needs_clarification
    assert "часть курицы" in (meal.clarification_question or "")
