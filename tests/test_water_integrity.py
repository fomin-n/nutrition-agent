import pytest

from app.graph.graph import process_request
from app.graph.nodes import nutrition_retriever
from app.graph.nodes.calculator import calculate_totals
from app.graph.nodes.critic import critic
from app.graph.nodes.nutrition_retriever import NutritionRetriever
from app.graph.nodes.text_parser import parse_text_locally
from app.schemas.nutrition import (
    IngredientEstimate,
    MealUnderstanding,
    NutritionCandidate,
    NutritionValues,
)
from app.schemas.outputs import FinalEstimate
from app.tools.food_normalization import find_food_mentions
from app.tools.food_query import normalize_food_description
from app.tools.nutrition_tools import NutritionSourceRouter
from app.tools.nutrition_validation import validate_candidate


@pytest.mark.parametrize(
    ("text", "expected_grams"),
    [
        ("Сколько калорий в литре воды?", 1000),
        ("Сколько калорий в 500 мл воды?", 500),
        ("How many calories are in one liter of water?", 1000),
        ("How many calories are in 500 ml of plain water?", 500),
    ],
)
def test_plain_water_parser_uses_density_for_volume(text: str, expected_grams: float) -> None:
    meal = parse_text_locally(text)

    assert meal.needs_clarification is False
    assert meal.confidence == "high"
    assert [ingredient.name for ingredient in meal.ingredients] == ["water"]
    assert meal.ingredients[0].grams_min == expected_grams
    assert meal.ingredients[0].grams_max == expected_grams


@pytest.mark.parametrize(
    "text",
    [
        "Сколько калорий в воде с сахаром?",
        "Сколько калорий в воде с сиропом?",
        "Calories in flavored water?",
        "Calories in Vitaminwater?",
    ],
)
def test_water_with_additives_is_not_classified_as_plain_water(text: str) -> None:
    query = normalize_food_description(text)

    assert query.food_category == "unknown"
    assert query.canonical_query != "water"
    assert find_food_mentions(text) == ()
    assert _offline_router().retrieve_candidates(query) == []


@pytest.mark.parametrize(
    ("text", "language_marker"),
    [
        ("Сколько калорий в литре воды?", "🟢 Уверенность: высокая"),
        ("Сколько калорий в 500 мл воды?", "🟢 Уверенность: высокая"),
        ("Сколько калорий в обычной воде?", "🟢 Уверенность: высокая"),
        ("How many calories are in one liter of water?", "🟢 Confidence: High"),
        ("How many calories are in 500 ml of plain water?", "🟢 Confidence: High"),
    ],
)
def test_plain_water_full_graph_returns_verified_zero(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    language_marker: str,
) -> None:
    monkeypatch.setattr(nutrition_retriever, "get_default_router", _offline_router)

    answer = process_request(text=text, source="test", use_llm=False)

    assert "0" in answer
    assert language_marker in answer
    assert "reliable nutrition data" not in answer
    assert "надежные данные" not in answer
    assert "need one more detail" not in answer
    assert "Нужно еще" not in answer


def test_plain_water_retrieval_marks_zero_as_semantically_valid() -> None:
    outcome = NutritionRetriever(router=_offline_router()).lookup_with_diagnostics(
        IngredientEstimate(name="water", grams_min=1000, grams_max=1000)
    )

    assert outcome.failure is None
    assert outcome.item is not None
    assert outcome.item.candidate is not None
    assert outcome.item.candidate.valid_zero_calories is True
    assert outcome.diagnostic.selected_identity == "fallback:water:default"
    assert outcome.diagnostic.candidates[0].validation.valid_zero_calories is True


def test_empty_retrieval_zero_totals_are_not_semantically_valid() -> None:
    totals = calculate_totals([])
    result = critic(
        {
            "meal": MealUnderstanding(
                ingredients=[IngredientEstimate(name="unknown", grams_min=100, grams_max=100)]
            ),
            "ingredient_nutrition": [],
            "totals": totals,
            "final_estimate": FinalEstimate(text="0 kcal", totals=totals),
        }
    )["critic_result"]

    assert result.action == "clarify"
    assert "zero calorie estimate" in result.issues


def test_plain_water_validation_rejects_flavored_candidate() -> None:
    query = normalize_food_description("plain water")
    candidate = NutritionCandidate(
        source="usda",
        source_id="flavored-water",
        name="Flavored water with lemon",
        values_per_100g=NutritionValues(
            calories_kcal=0,
            protein_g=0,
            fat_g=0,
            carbohydrate_g=0,
        ),
    )

    validation = validate_candidate(candidate, query)

    assert validation.accepted is False
    assert validation.valid_zero_calories is False
    assert "plain_water_identity_or_additive_mismatch" in validation.reasons


@pytest.mark.parametrize(
    "text",
    [
        "Сколько калорий в воде с сахаром?",
        "Calories in flavored water?",
        "Calories in Vitaminwater?",
    ],
)
def test_original_modifiers_prevent_llm_plain_water_collapse(text: str) -> None:
    outcome = NutritionRetriever(router=_offline_router()).lookup_with_diagnostics(
        IngredientEstimate(name="water", grams_min=500, grams_max=500),
        raw_input=text,
    )

    assert outcome.item is None
    assert outcome.failure is not None
    assert outcome.diagnostic.selected_identity is None
    assert outcome.diagnostic.fallback_path is None


def _offline_router() -> NutritionSourceRouter:
    return NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
