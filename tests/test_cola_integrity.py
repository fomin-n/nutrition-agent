from concurrent.futures import ThreadPoolExecutor

import pytest

from app.graph.graph import process_request
from app.graph.nodes import nutrition_retriever
from app.graph.nodes.calculator import calculate_totals
from app.graph.nodes.nutrition_retriever import NutritionRetriever
from app.graph.nodes.text_parser import parse_text_locally
from app.schemas.nutrition import IngredientEstimate, NutritionCandidate, NutritionValues
from app.tools.cache import JsonFileCache
from app.tools.food_query import normalize_food_description
from app.tools.nutrition_tools import NutritionSourceRouter


@pytest.mark.parametrize(
    "text",
    [
        "How many calories are in a can of Coca-Cola?",
        "Estimate a 330 ml Coke",
        "Сколько калорий в банке колы?",
        "Оцени 330 мл Кока-Колы",
        "Кола, одна банка",
    ],
)
def test_regular_cola_queries_have_consistent_macros(text: str) -> None:
    meal = parse_text_locally(text)
    assert len(meal.ingredients) == 1

    retriever = NutritionRetriever(router=_offline_router())
    item = retriever.lookup(meal.ingredients[0], language="ru" if "а" in text else "en")
    assert item is not None

    totals = calculate_totals([item])
    assert totals.calories_kcal.min == pytest.approx(140, abs=10)
    assert totals.calories_kcal.max == pytest.approx(140, abs=10)
    assert totals.protein_g.min == 0
    assert totals.fat_g.min == 0
    assert totals.carbs_g.min == pytest.approx(35, abs=1)
    assert item.candidate is not None
    assert item.candidate.stable_identity == "fallback:Coca-Cola:default"


def test_cola_aliases_normalize_to_product_metadata() -> None:
    for text in ("Coca-Cola", "Coke", "cola", "Кока-Колы", "колы"):
        query = normalize_food_description(text)
        assert query.canonical_query == "Coca-Cola"
        assert query.brand == "Coca-Cola"
        assert query.query_kind == "branded_product"
        assert query.food_category == "sugary_soft_drink"
        assert query.product_variant == "regular"
        assert query.default_serving_amount == 330
        assert query.default_serving_unit == "ml"


def test_zero_sugar_cola_is_distinct_from_regular() -> None:
    query = normalize_food_description("330 ml Кока-Кола без сахара")

    assert query.canonical_query == "Coca-Cola Zero Sugar"
    assert query.food_category == "zero_sugar_soft_drink"
    assert query.product_variant == "zero_sugar"

    meal = parse_text_locally("330 мл Кока-Кола без сахара")
    assert [ingredient.name for ingredient in meal.ingredients] == ["Coca-Cola Zero Sugar"]
    item = NutritionRetriever(router=_offline_router()).lookup(meal.ingredients[0], language="ru")
    assert item is not None
    totals = calculate_totals([item])
    assert totals.calories_kcal.max == 0
    assert totals.carbs_g.max == 0


def test_zero_sugar_cola_zero_total_is_not_rejected_by_critic(monkeypatch) -> None:
    monkeypatch.setattr(nutrition_retriever, "get_default_router", _offline_router)

    answer = process_request(
        text="Сколько калорий в банке Coca-Cola Zero 330 мл?",
        source="test",
        use_llm=False,
    )

    assert "🔥 Калории: 0 ккал" in answer
    assert "Нужно еще" not in answer


def test_invalid_soft_drink_candidate_is_rejected_for_valid_fallback() -> None:
    bad = NutritionCandidate(
        source="usda",
        source_id="bad-cola",
        name="Cola mixed food",
        values_per_100g=NutritionValues(
            calories_kcal=180,
            protein_g=8,
            fat_g=7,
            carbohydrate_g=20,
        ),
    )
    router = _offline_router()
    valid = router.retrieve_candidates(normalize_food_description("cola"))[0]
    router.retrieve_candidates = lambda query: [bad, valid]  # type: ignore[method-assign]

    outcome = NutritionRetriever(router=router).lookup_with_diagnostics(
        IngredientEstimate(name="cola", grams_min=330, grams_max=330),
        request_id="test-request",
    )

    assert outcome.item is not None
    assert outcome.item.source == "fallback"
    assert outcome.diagnostic.selected_identity == "fallback:Coca-Cola:default"
    assert outcome.diagnostic.candidates[0].validation.accepted is False
    assert "soft_drink_protein_above_limit" in outcome.diagnostic.candidates[0].validation.reasons


def test_parallel_food_retrieval_keeps_candidate_identity_isolated() -> None:
    inputs = ("hamburger", "chicken breast cooked", "Coca-Cola", "apple")

    def retrieve(name: str) -> tuple[str, str, float]:
        outcome = NutritionRetriever(router=_offline_router()).lookup_with_diagnostics(
            IngredientEstimate(name=name, grams_min=100, grams_max=100),
            request_id=name,
        )
        assert outcome.item is not None
        assert outcome.diagnostic.selected_identity is not None
        return name, outcome.diagnostic.selected_identity, outcome.item.per_100g.calories_kcal

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = dict((name, (identity, calories)) for name, identity, calories in executor.map(retrieve, inputs))

    assert results["Coca-Cola"] == ("fallback:Coca-Cola:default", 42)
    assert results["chicken breast cooked"] == ("fallback:chicken breast cooked:default", 165)
    assert len({identity for identity, _ in results.values()}) == len(inputs)


def test_cache_keys_distinguish_variant_and_serving_and_writes_are_readable(tmp_path) -> None:
    cache = JsonFileCache(tmp_path)
    regular_key = "off:search:v2:coca cola:page_size=5"
    zero_key = "off:search:v2:coca cola zero sugar:page_size=5"
    other_serving_key = "off:search:v2:coca cola:page_size=1"

    assert len({cache.key_digest(regular_key), cache.key_digest(zero_key), cache.key_digest(other_serving_key)}) == 3
    cache.set(regular_key, {"product": "regular"})
    assert cache.get(regular_key) == {"product": "regular"}
    assert not list(tmp_path.glob("*.tmp"))


def _offline_router() -> NutritionSourceRouter:
    return NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
