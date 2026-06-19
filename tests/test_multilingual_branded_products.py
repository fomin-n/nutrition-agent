import pytest

from app.graph.graph import process_request
from app.graph.nodes import nutrition_retriever
from app.graph.nodes.nutrition_retriever import NutritionRetriever
from app.schemas.nutrition import IngredientEstimate, NutritionCandidate, NutritionValues
from app.tools.food_query import normalize_food_description
from app.tools.nutrition_tools import NutritionSourceRouter, provider_search_queries


@pytest.fixture
def offline_retrieval(monkeypatch) -> None:
    monkeypatch.setattr(
        nutrition_retriever,
        "get_default_router",
        lambda: NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None),
    )


@pytest.mark.parametrize(
    ("text", "calories", "macros"),
    [
        ("Сколько калорий в Сникерс (50g)?", "250-250 ккал", ("4-4 г", "12-12 г", "31-31 г")),
        ("Сколько калорий в Сникерсе?", "250-250 ккал", ("4-4 г", "12-12 г", "31-31 г")),
        ("Сколько калорий в Твиксе?", "250-250 ккал", ("2-2 г", "12-12 г", "32-32 г")),
        ("Сколько калорий в Баунти?", "280-280 ккал", ("2-2 г", "15-15 г", "34-34 г")),
    ],
)
def test_russian_branded_snacks_return_estimates(
    offline_retrieval,
    text: str,
    calories: str,
    macros: tuple[str, str, str],
) -> None:
    answer = process_request(text=text, source="test", use_llm=False)

    assert calories in answer
    assert all(value in answer for value in macros)
    assert "Не удалось найти" not in answer
    assert "Уверенность:" in answer


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("How many calories are in Snickers (50g)?", "250-250 kcal"),
        ("How many calories are in a Twix bar?", "250-250 kcal"),
        ("How many calories are in a Bounty bar?", "280-280 kcal"),
    ],
)
def test_english_branded_snacks_still_work(offline_retrieval, text: str, expected: str) -> None:
    answer = process_request(text=text, source="test", use_llm=False)

    assert expected in answer
    assert "I couldn't find reliable" not in answer
    assert "Confidence:" in answer


def test_russian_snack_comparison_is_not_aggregated(offline_retrieval) -> None:
    answer = process_request(
        text="Где больше калорий, в Твиксе или в Сникерсе?",
        source="test",
        use_llm=False,
    )

    assert answer.startswith("Сравнение калорийности:")
    assert "Snickers (50 г): 250 ккал" in answer
    assert "Twix (50 г): 250 ккал" in answer
    assert "примерно одинаковая" in answer
    assert "500" not in answer


def test_russian_product_alias_expands_to_english_provider_queries() -> None:
    query = normalize_food_description("Сникерс 50g")
    variants = provider_search_queries(query)

    assert query.canonical_query == "Snickers"
    assert query.brand == "Snickers"
    assert query.query_kind == "branded_product"
    assert query.food_category == "chocolate_bar"
    assert query.product_type == "chocolate bar"
    assert query.quantity == 50
    assert variants[:3] == ["Snickers", "Snickers bar", "Snickers chocolate bar"]
    assert "Сникерс 50g" in variants
    assert "Snickers 50g" in variants


def test_wrong_branded_bar_candidate_is_rejected_for_explicit_fallback() -> None:
    wrong_product = NutritionCandidate(
        source="usda",
        source_id="twix-result",
        name="Twix chocolate bar",
        brand="Twix",
        food_type="branded",
        values_per_100g=NutritionValues(
            calories_kcal=495,
            protein_g=5,
            fat_g=24,
            carbohydrate_g=65,
        ),
    )
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    fallback = router.retrieve_candidates(normalize_food_description("Snickers"))[0]
    router.retrieve_candidates = lambda query: [wrong_product, fallback]  # type: ignore[method-assign]

    outcome = NutritionRetriever(router=router).lookup_with_diagnostics(
        IngredientEstimate(name="Сникерс", grams_min=50, grams_max=50),
        language="ru",
        request_id="snickers-regression",
    )

    assert outcome.item is not None
    assert outcome.item.matched_food_name == "Snickers"
    assert outcome.diagnostic.provider_queries[:3] == [
        "Snickers",
        "Snickers bar",
        "Snickers chocolate bar",
    ]
    assert outcome.diagnostic.candidates[0].validation.accepted is False
    assert "chocolate_bar_product_identity_mismatch" in outcome.diagnostic.candidates[0].validation.reasons
    assert outcome.diagnostic.selected_identity == "fallback:Snickers:default"
