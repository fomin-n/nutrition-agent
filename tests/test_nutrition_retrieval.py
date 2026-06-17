from app.graph.nodes.nutrition_retriever import NutritionRetriever
from app.schemas.nutrition import IngredientEstimate, NutritionCandidate, NutritionValues
from app.tools.food_query import normalize_food_description
from app.tools.nutrition_ranking import rank_candidates
from app.tools.nutrition_tools import NutritionSourceRouter
from app.tools.provider_utils import redacted_text


def test_russian_food_query_normalization() -> None:
    query = normalize_food_description("жареная куриная грудка 200 г")

    assert query.language == "ru"
    assert query.canonical_query == "fried chicken breast"
    assert query.preparation == "fried"
    assert query.quantity == 200
    assert query.unit == "г"


def test_brand_and_region_query_normalization() -> None:
    query = normalize_food_description("Danone Skyr 850 г")

    assert query.brand == "Danone"
    assert query.query_kind == "branded_product"
    assert "Danone" in query.canonical_query
    assert query.quantity == 850

    big_mac = normalize_food_description("биг мак во Франции")
    assert big_mac.restaurant == "McDonald's"
    assert big_mac.region == "FR"
    assert big_mac.query_kind == "restaurant_menu_item"


def test_candidate_ranking_prefers_brand_match_and_complete_macros() -> None:
    query = normalize_food_description("Danone Skyr 850 г")
    candidates = [
        NutritionCandidate(
            source="usda",
            source_id="1",
            name="Plain yogurt",
            food_type="generic",
            values_per_100g=NutritionValues(calories_kcal=60, protein_g=4, carbohydrate_g=5, fat_g=2),
        ),
        NutritionCandidate(
            source="fatsecret",
            source_id="2",
            name="Skyr",
            brand="Danone",
            food_type="branded",
            metric_serving_amount=100,
            metric_serving_unit="g",
            values_per_100g=NutritionValues(calories_kcal=62, protein_g=10, carbohydrate_g=4, fat_g=0.2),
        ),
    ]

    ranked = rank_candidates(candidates, query)

    assert ranked[0].source == "fatsecret"
    assert ranked[0].source_id == "2"
    assert ranked[0].score_components["brand"] > 0


def test_candidate_ranking_prefers_plain_fallback_over_unrequested_candied_match() -> None:
    query = normalize_food_description("apple")
    candidates = [
        NutritionCandidate(
            source="usda",
            source_id="candied-apple",
            name="Apple, candied",
            food_type="prepared",
            metric_serving_amount=100,
            metric_serving_unit="g",
            values_per_100g=NutritionValues(calories_kcal=134, protein_g=1.3, carbohydrate_g=29.6, fat_g=2.1),
        ),
        NutritionCandidate(
            source="fallback",
            source_id="apple",
            name="apple",
            food_type="generic",
            metric_serving_amount=100,
            metric_serving_unit="g",
            values_per_100g=NutritionValues(calories_kcal=52, protein_g=0.3, carbohydrate_g=13.8, fat_g=0.2),
        ),
    ]

    ranked = rank_candidates(candidates, query)

    assert ranked[0].source == "fallback"
    assert ranked[0].name == "apple"
    assert ranked[0].score_components["preparation"] == 0.0
    assert ranked[1].score_components["preparation"] < 0.0


def test_ml_serving_is_not_converted_to_per_100g() -> None:
    candidate = NutritionCandidate(
        source="fatsecret",
        source_id="milk-ml",
        name="Milk serving",
        metric_serving_amount=100,
        metric_serving_unit="ml",
        calories_kcal=60,
        protein_g=3,
        carbohydrate_g=5,
        fat_g=3,
    )

    assert candidate.to_per_100g() is None


def test_retriever_uses_ranked_candidate() -> None:
    query_candidate = NutritionCandidate(
        source="usda",
        source_id="banana",
        name="Banana",
        food_type="generic",
        metric_serving_amount=100,
        metric_serving_unit="g",
        values_per_100g=NutritionValues(calories_kcal=89, protein_g=1.1, carbohydrate_g=23, fat_g=0.3),
    )
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    router.retrieve_candidates = lambda query: [query_candidate]  # type: ignore[method-assign]

    item = NutritionRetriever(router=router).lookup(IngredientEstimate(name="banana", grams_min=100, grams_max=100))

    assert item.source == "usda"
    assert item.per_100g.calories_kcal == 89
    assert item.candidate is not None


def test_retriever_does_not_invent_generic_nutrition_when_no_sources() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    item = NutritionRetriever(router=router).lookup(IngredientEstimate(name="unknown meal", grams_min=100, grams_max=100))

    assert item is None


def test_secret_redaction() -> None:
    text = 'api_key=keyvalue Authorization: Bearer bearervalue client_secret="hiddenvalue" access_token="abcvalue"'
    redacted = redacted_text(text)

    assert "keyvalue" not in redacted
    assert "bearervalue" not in redacted
    assert "hiddenvalue" not in redacted
    assert "abcvalue" not in redacted
    assert "[REDACTED]" in redacted
