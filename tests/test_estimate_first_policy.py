import pytest

from app.graph import graph as graph_module
from app.graph.nodes import nutrition_retriever
from app.graph.nodes.calculator import calculate_macros
from app.graph.nodes.nutrition_retriever import retrieve_nutrition
from app.graph.nodes.synthesizer import synthesize_answer
from app.graph.nodes.text_parser import parse_text_meal
from app.schemas.inputs import NormalizedInput, UserInput
from app.schemas.nutrition import (
    IngredientEstimate,
    MealUnderstanding,
    NutritionCandidate,
    NutritionValues,
)
from app.tools.food_query import normalize_food_description
from app.tools.nutrition_tools import NutritionSourceRouter


@pytest.fixture
def offline_router(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        nutrition_retriever,
        "get_default_router",
        lambda: NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None),
    )


@pytest.mark.parametrize(
    ("text", "expected_items", "expected_portions", "expected_confidence"),
    [
        ("Сколько калорий в борще?", ["borscht"], [(350, 450)], "low"),
        ("Сколько калорий в одной пельмешке?", ["pelmeni"], [(12, 18)], "low"),
        ("Сколько калорий в одном крылышке KFC?", ["KFC chicken wing"], [(35, 50)], "low"),
        ("Сколько калорий в самом обычном молоке?", ["milk"], [(200, 300)], "medium"),
        ("Сколько калорий в литре воды?", ["water"], [(1000, 1000)], "high"),
        ("Сколько калорий в среднем банане?", ["banana"], [(100, 140)], "medium"),
        (
            "Пюрешка с котлеткой",
            ["mashed potatoes", "meat cutlet"],
            [(180, 250), (80, 120)],
            "low",
        ),
    ],
)
def test_common_russian_food_requests_return_estimates(
    offline_router: None,
    text: str,
    expected_items: list[str],
    expected_portions: list[tuple[int, int]],
    expected_confidence: str,
) -> None:
    state = graph_module.build_graph().invoke(
        {"user_input": UserInput(text=text, source="test"), "use_llm": False}
    )

    meal = state["meal"]
    final = state["final_estimate"]
    assert [item.name for item in meal.ingredients] == expected_items
    assert [(item.grams_min, item.grams_max) for item in meal.ingredients] == expected_portions
    assert meal.assumptions
    assert final.totals is not None
    assert final.totals.calories_kcal.max >= final.totals.calories_kcal.min
    assert final.is_clarification is False
    assert final.is_refusal is False
    assert final.confidence == expected_confidence
    assert "🔥 Калории:" in final.text
    assert "📋 Допущения:" in final.text


@pytest.mark.parametrize(
    ("russian", "english"),
    [
        ("Сколько калорий в борще?", "How many calories are in borscht?"),
        ("Сколько калорий в одной пельмешке?", "How many calories are in one pelmeni?"),
        ("Сколько калорий в одном крылышке KFC?", "How many calories are in one KFC wing?"),
    ],
)
def test_russian_and_english_priors_are_consistent(
    offline_router: None,
    russian: str,
    english: str,
) -> None:
    states = [
        graph_module.build_graph().invoke(
            {"user_input": UserInput(text=text, source="test"), "use_llm": False}
        )
        for text in (russian, english)
    ]

    assert states[0]["totals"] == states[1]["totals"]
    assert "🔥 Калории:" in states[0]["final_estimate"].text
    assert "🔥 Calories:" in states[1]["final_estimate"].text


def test_known_dish_prior_wins_over_llm_recipe_decomposition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.graph.nodes.text_parser.has_openai_key", lambda: True)
    monkeypatch.setattr(
        "app.graph.nodes.text_parser.parse_text_with_llm",
        lambda *_args, **_kwargs: pytest.fail("known dish should not call the LLM parser"),
    )

    result = parse_text_meal(
        {
            "normalized_input": NormalizedInput(
                text="Сколько калорий в борще?",
                has_text=True,
                has_image=False,
                language="ru",
            ),
            "use_llm": True,
        }
    )

    meal = result["meal"]
    assert [item.name for item in meal.ingredients] == ["borscht"]
    assert (meal.ingredients[0].grams_min, meal.ingredients[0].grams_max) == (350, 450)


def test_partial_retrieval_returns_low_confidence_estimate(
    offline_router: None,
) -> None:
    state = {
        "normalized_input": NormalizedInput(
            text="Банан с неизвестной добавкой",
            has_text=True,
            has_image=False,
            language="ru",
        ),
        "meal": MealUnderstanding(
            ingredients=[
                IngredientEstimate(name="banana", grams_min=100, grams_max=100),
                IngredientEstimate(name="unknown topping", grams_min=10, grams_max=20),
            ],
            assumptions=["Приняты указанные продукты."],
            confidence="medium",
        ),
    }
    state.update(retrieve_nutrition(state))
    state.update(calculate_macros(state))
    state.update(synthesize_answer(state))

    final = state["final_estimate"]
    assert len(state["ingredient_nutrition"]) == 1
    assert len(state["retrieval_failures"]) == 1
    assert final.totals is not None
    assert final.is_clarification is False
    assert final.confidence == "low"
    assert "Частичная оценка" in final.text
    assert "не включен" in final.text


def test_unrecognizable_food_still_requires_clarification(offline_router: None) -> None:
    state = graph_module.build_graph().invoke(
        {
            "user_input": UserInput(
                text="Сколько калорий в совершенно неизвестной штуке?",
                source="test",
            ),
            "use_llm": False,
        }
    )

    final = state["final_estimate"]
    assert final.is_clarification is True
    assert final.totals is None


def test_plain_beef_rejects_salami_candidate() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    salami = _candidate(
        source_id="salami",
        name="Salami, cooked, beef",
        calories=330,
        protein=18,
        fat=28,
        carbs=2,
    )
    plain = _candidate(
        source="fallback",
        source_id="beef cooked",
        name="beef cooked",
        calories=250,
        protein=26,
        fat=15,
        carbs=0,
    )
    router.retrieve_candidates = lambda _query: [salami, plain]  # type: ignore[method-assign]

    selection = router.select_candidate(normalize_food_description("beef cooked"))

    assert selection.selected is not None
    assert selection.selected.source_id == "beef cooked"
    assert "plain_beef_matched_processed_meat" in selection.validations[0].reasons


def test_boiled_potato_rejects_high_fat_candidate() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    high_fat = _candidate(
        source_id="potato-fat",
        name="Potato, boiled",
        calories=210,
        protein=3,
        fat=12,
        carbs=22,
    )
    plain = _candidate(
        source="fallback",
        source_id="potato boiled",
        name="potato boiled",
        calories=87,
        protein=1.9,
        fat=0.1,
        carbs=20.1,
    )
    router.retrieve_candidates = lambda _query: [high_fat, plain]  # type: ignore[method-assign]

    selection = router.select_candidate(normalize_food_description("potato boiled"))

    assert selection.selected is not None
    assert selection.selected.source_id == "potato boiled"
    assert "boiled_potato_macros_out_of_range" in selection.validations[0].reasons


def test_kfc_query_rejects_non_kfc_restaurant_candidate() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    generic = _candidate(
        source_id="generic-wing",
        name="Restaurant fried chicken wing",
        calories=280,
        protein=20,
        fat=20,
        carbs=8,
    )
    kfc = _candidate(
        source="fallback",
        source_id="KFC chicken wing",
        name="KFC chicken wing",
        calories=290,
        protein=18,
        fat=21,
        carbs=9,
    )
    router.retrieve_candidates = lambda _query: [generic, kfc]  # type: ignore[method-assign]

    selection = router.select_candidate(normalize_food_description("KFC chicken wing"))

    assert selection.selected is not None
    assert selection.selected.source_id == "KFC chicken wing"
    assert "restaurant_identity_mismatch" in selection.validations[0].reasons


def test_ordinary_milk_rejects_cracker_candidate() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    crackers = _candidate(
        source_id="milk-crackers",
        name="Crackers, milk",
        calories=446,
        protein=7.6,
        fat=13.8,
        carbs=71.7,
    )
    milk = _candidate(
        source="fallback",
        source_id="milk",
        name="milk",
        calories=61,
        protein=3.2,
        fat=3.3,
        carbs=4.8,
    )
    router.retrieve_candidates = lambda _query: [crackers, milk]  # type: ignore[method-assign]

    selection = router.select_candidate(normalize_food_description("milk"))

    assert selection.selected is not None
    assert selection.selected.source_id == "milk"
    assert "ordinary_milk_identity_mismatch" in selection.validations[0].reasons
    assert "ordinary_milk_macros_out_of_range" in selection.validations[0].reasons


def test_meat_borscht_prior_rejects_ultralight_soup_candidate() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    light_soup = _candidate(
        source_id="light-borscht",
        name="Soup, borscht",
        calories=20,
        protein=0.5,
        fat=0.4,
        carbs=3.9,
    )
    borscht = _candidate(
        source="fallback",
        source_id="borscht",
        name="borscht",
        calories=55,
        protein=2.5,
        fat=2,
        carbs=6.5,
    )
    router.retrieve_candidates = lambda _query: [light_soup, borscht]  # type: ignore[method-assign]

    selection = router.select_candidate(normalize_food_description("borscht"))

    assert selection.selected is not None
    assert selection.selected.source_id == "borscht"
    assert "meat_borscht_macros_out_of_range" in selection.validations[0].reasons


def _candidate(
    *,
    source: str = "usda",
    source_id: str,
    name: str,
    calories: float,
    protein: float,
    fat: float,
    carbs: float,
) -> NutritionCandidate:
    return NutritionCandidate(
        source=source,
        source_id=source_id,
        name=name,
        food_type="generic",
        metric_serving_amount=100,
        metric_serving_unit="g",
        values_per_100g=NutritionValues(
            calories_kcal=calories,
            protein_g=protein,
            fat_g=fat,
            carbohydrate_g=carbs,
        ),
    )
