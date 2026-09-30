import pytest

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


def test_russian_chicken_meat_component_canonicalizes() -> None:
    query = normalize_food_description("Куриное мясо")

    assert query.language == "ru"
    assert query.canonical_query == "chicken breast cooked"


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


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("индейка (филе)", "turkey cooked"),
        ("Pork (chashu or similar)", "pork cooked"),
        ("Broth (pork or mixed)", "broth"),
        ("Лаваш или тонкий блин для ролла", "tortilla"),
    ],
)
def test_decorated_component_names_canonicalize_before_lookup(
    text: str,
    canonical: str,
) -> None:
    query = normalize_food_description(text)

    assert query.canonical_query == canonical


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


def test_retriever_resolves_russian_chicken_meat_component() -> None:
    item = NutritionRetriever(router=NutritionSourceRouter()).lookup(
        IngredientEstimate(name="Куриное мясо", grams_min=50, grams_max=90)
    )

    assert item.matched_food_name == "chicken breast cooked"
    assert item.source == "fallback"
    assert item.per_100g.calories_kcal == 165
    assert item.grams_min == 50
    assert item.grams_max == 90


def test_retriever_diagnostic_includes_query_kind() -> None:
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

    outcome = NutritionRetriever(router=router).lookup_with_diagnostics(
        IngredientEstimate(name="banana", grams_min=100, grams_max=100)
    )

    assert outcome.diagnostic.query_kind == "generic_ingredient"
    assert outcome.diagnostic.model_dump(mode="json")["query_kind"] == "generic_ingredient"


def test_retriever_backfills_unresolved_sauce_with_broad_class_prior() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)

    outcome = NutritionRetriever(router=router).lookup_with_diagnostics(
        IngredientEstimate(
            name="Соус (майонез, горчица или аналогичный)",
            grams_min=10,
            grams_max=20,
            origin="llm_component",
        ),
        language="ru",
    )

    assert outcome.failure is None
    assert outcome.item is not None
    assert outcome.item.matched_food_name == "mayonnaise"
    assert outcome.item.grams_min == 10
    assert outcome.item.grams_max == 20
    assert outcome.item.source_factor_min < 1
    assert outcome.item.source_factor_max > 1
    assert outcome.item.warning is not None
    assert "широкий типовой профиль" in outcome.item.warning
    assert outcome.diagnostic.fallback_path == "component_class_prior_backfill"


def test_retriever_backfills_generic_sauce_when_specific_sauce_is_unknown() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)

    outcome = NutritionRetriever(router=router).lookup_with_diagnostics(
        IngredientEstimate(
            name="Соус (соевый, унаги или майонезный)",
            grams_min=20,
            grams_max=40,
            origin="llm_component",
        ),
        language="ru",
    )

    assert outcome.failure is None
    assert outcome.item is not None
    assert outcome.item.matched_food_name == "generic sauce"
    assert outcome.item.warning is not None
    assert "широкий типовой профиль" in outcome.item.warning


def test_retriever_backfills_fried_fish_with_wide_prior() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)

    outcome = NutritionRetriever(router=router).lookup_with_diagnostics(
        IngredientEstimate(
            name="Fried fish fillet",
            grams_min=180,
            grams_max=220,
            origin="llm_component",
        ),
        language="en",
    )

    assert outcome.failure is None
    assert outcome.item is not None
    assert outcome.item.matched_food_name == "fried fish fillet"
    assert outcome.item.grams_min == 180
    assert outcome.item.grams_max == 220
    assert outcome.item.grams_min * outcome.item.source_factor_min == 120
    assert outcome.item.grams_max * outcome.item.source_factor_max == 280
    assert outcome.item.warning is not None
    assert "broad" in outcome.item.warning


def test_arbitration_prefers_fallback_over_weak_generic_provider() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    avocado_oil = NutritionCandidate(
        source="usda",
        source_id="avocado-oil",
        name="Oil, avocado",
        food_type="generic",
        metric_serving_amount=100,
        metric_serving_unit="g",
        match_score=0.84,
        score_components={"name": 0.26, "source": 0.35},
        values_per_100g=NutritionValues(calories_kcal=884, protein_g=0, carbohydrate_g=0, fat_g=100),
    )
    avocado = NutritionCandidate(
        source="fallback",
        source_id="avocado",
        name="avocado",
        food_type="generic",
        metric_serving_amount=100,
        metric_serving_unit="g",
        match_score=0.82,
        score_components={"name": 0.34, "source": 0.18},
        values_per_100g=NutritionValues(calories_kcal=160, protein_g=2, carbohydrate_g=8.5, fat_g=14.7),
    )
    router.retrieve_candidates = lambda query: [avocado_oil, avocado]  # type: ignore[method-assign]

    selection = router.select_candidate(normalize_food_description("avocado"))

    assert selection.selected is not None
    assert selection.selected.source == "fallback"
    assert selection.arbitration_path == "fallback_selected_over_weak_provider"
    assert "provider_disagrees_with_grounded_fallback" in selection.arbitration_reasons


def test_arbitration_keeps_strong_branded_provider() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    provider = NutritionCandidate(
        source="fatsecret",
        source_id="snickers-provider",
        name="Snickers Bar",
        brand="Snickers",
        food_type="branded",
        metric_serving_amount=100,
        metric_serving_unit="g",
        match_score=0.9,
        score_components={"name": 0.34, "brand": 0.18},
        values_per_100g=NutritionValues(calories_kcal=505, protein_g=8, carbohydrate_g=61, fat_g=25),
    )
    fallback = NutritionCandidate(
        source="fallback",
        source_id="Snickers",
        name="Snickers",
        brand="Snickers",
        food_type="branded",
        metric_serving_amount=100,
        metric_serving_unit="g",
        match_score=0.88,
        score_components={"name": 0.34, "brand": 0.18},
        values_per_100g=NutritionValues(calories_kcal=500, protein_g=8, carbohydrate_g=62, fat_g=24),
    )
    router.retrieve_candidates = lambda query: [provider, fallback]  # type: ignore[method-assign]

    selection = router.select_candidate(normalize_food_description("Snickers"))

    assert selection.selected is not None
    assert selection.selected.source == "fatsecret"
    assert selection.arbitration_path == "provider_kept_for_product_identity"


def test_retriever_diagnostic_includes_arbitration_and_scores() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    avocado_oil = NutritionCandidate(
        source="usda",
        source_id="avocado-oil",
        name="Oil, avocado",
        food_type="generic",
        metric_serving_amount=100,
        metric_serving_unit="g",
        match_score=0.84,
        score_components={"name": 0.26},
        values_per_100g=NutritionValues(calories_kcal=884, protein_g=0, carbohydrate_g=0, fat_g=100),
    )
    avocado = NutritionCandidate(
        source="fallback",
        source_id="avocado",
        name="avocado",
        food_type="generic",
        metric_serving_amount=100,
        metric_serving_unit="g",
        match_score=0.82,
        score_components={"name": 0.34},
        values_per_100g=NutritionValues(calories_kcal=160, protein_g=2, carbohydrate_g=8.5, fat_g=14.7),
    )
    router.retrieve_candidates = lambda query: [avocado_oil, avocado]  # type: ignore[method-assign]

    outcome = NutritionRetriever(router=router).lookup_with_diagnostics(
        IngredientEstimate(name="avocado", grams_min=100, grams_max=100)
    )

    assert outcome.item is not None
    assert outcome.diagnostic.arbitration_path == "fallback_selected_over_weak_provider"
    assert outcome.diagnostic.arbitration_reasons
    assert outcome.diagnostic.candidates[0].score_components == {"name": 0.26}


def test_arbitration_prefers_pizza_prior_over_implausible_provider() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    dessert_pizza = _candidate(
        source="usda",
        source_id="dessert-pizza",
        name="Dessert pizza",
        calories=204,
        protein=1.8,
        fat=7.5,
        carbs=32.4,
        match_score=0.92,
    )
    pizza = _candidate(
        source="fallback",
        source_id="pizza",
        name="pizza",
        calories=266,
        protein=11,
        fat=10,
        carbs=33,
        match_score=0.66,
    )
    router.retrieve_candidates = lambda query: [dessert_pizza, pizza]  # type: ignore[method-assign]

    selection = router.select_candidate(normalize_food_description("Margherita pizza"))

    assert selection.selected is not None
    assert selection.selected.source == "fallback"
    assert "pizza_provider_protein_below_floor" in selection.arbitration_reasons
    assert "pizza_provider_variant_mismatch" in selection.arbitration_reasons


def test_arbitration_prefers_firm_tofu_prior_over_soft_provider() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    soft_tofu = _candidate(
        source="usda",
        source_id="soft-tofu",
        name="Firm tofu",
        calories=85,
        protein=10.9,
        fat=4.2,
        carbs=1,
        match_score=0.89,
    )
    firm_tofu = _candidate(
        source="fallback",
        source_id="tofu firm",
        name="tofu firm",
        calories=120,
        protein=14,
        fat=7,
        carbs=2.5,
        match_score=0.82,
    )
    router.retrieve_candidates = lambda query: [soft_tofu, firm_tofu]  # type: ignore[method-assign]

    selection = router.select_candidate(normalize_food_description("150 g firm tofu"))

    assert selection.selected is not None
    assert selection.selected.source_id == "tofu firm"
    assert "firm_tofu_provider_too_lean" in selection.arbitration_reasons


def test_arbitration_prefers_local_prior_for_five_percent_cottage_cheese() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    vegetable_cottage = _candidate(
        source="usda",
        source_id="veg-cottage",
        name="Cheese, cottage, with vegetables",
        calories=95,
        protein=10.9,
        fat=4.2,
        carbs=3,
        match_score=0.89,
    )
    cottage = _candidate(
        source="fallback",
        source_id="cottage cheese",
        name="cottage cheese",
        calories=121,
        protein=17,
        fat=5,
        carbs=3,
        match_score=0.82,
    )
    router.retrieve_candidates = lambda query: [vegetable_cottage, cottage]  # type: ignore[method-assign]

    selection = router.select_candidate(normalize_food_description("200g 5% cottage cheese"))

    assert selection.selected is not None
    assert selection.selected.source_id == "cottage cheese"
    assert "cottage_cheese_variant_mismatch" in selection.arbitration_reasons
    assert "cottage_cheese_5_percent_provider_out_of_range" in selection.arbitration_reasons


def test_arbitration_prefers_prepared_dish_prior_when_provider_disagrees() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    low_curry = _candidate(
        source="usda",
        source_id="low-curry",
        name="Chicken curry with rice",
        calories=116,
        protein=5,
        fat=4,
        carbs=15,
        match_score=1.0,
    )
    curry = _candidate(
        source="fallback",
        source_id="chicken curry with rice",
        name="chicken curry with rice",
        calories=160,
        protein=7.8,
        fat=6.2,
        carbs=18.9,
        match_score=0.66,
    )
    router.retrieve_candidates = lambda query: [low_curry, curry]  # type: ignore[method-assign]

    selection = router.select_candidate(normalize_food_description("chicken curry with rice"))

    assert selection.selected is not None
    assert selection.selected.source_id == "chicken curry with rice"
    assert "prepared_dish_provider_disagrees_with_local_prior" in selection.arbitration_reasons


def test_retriever_widens_exact_provider_prepared_dish_row() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    lasagna = _candidate(
        source="usda",
        source_id="lasagna-provider",
        name="Lasagna with meat",
        calories=186,
        protein=10,
        fat=9,
        carbs=17,
        match_score=0.92,
    )
    router.retrieve_candidates = lambda query: [lasagna]  # type: ignore[method-assign]

    outcome = NutritionRetriever(router=router).lookup_with_diagnostics(
        IngredientEstimate(name="lasagna", grams_min=350, grams_max=350),
        language="en",
    )

    assert outcome.item is not None
    assert outcome.item.grams_min == outcome.item.grams_max == 350
    assert outcome.item.grams_min * outcome.item.source_factor_min == 308
    assert round(outcome.item.grams_max * outcome.item.source_factor_max) == 392
    assert outcome.item.warning is not None
    assert "widened range for prepared dish" in outcome.item.warning


def test_retriever_widens_high_variance_soup_fallback() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)

    outcome = NutritionRetriever(router=router).lookup_with_diagnostics(
        IngredientEstimate(name="Куриный суп", grams_min=380, grams_max=420),
        language="ru",
    )

    assert outcome.item is not None
    assert outcome.item.matched_food_name == "chicken soup"
    assert outcome.item.per_100g.calories_kcal == 53
    assert outcome.item.grams_min == 380
    assert outcome.item.grams_max == 420
    assert outcome.item.grams_min * outcome.item.source_factor_min == 260
    assert outcome.item.grams_max * outcome.item.source_factor_max == 540
    assert outcome.item.warning is not None
    assert "куриный суп" in outcome.item.warning.lower()
    assert "диапазон расширен" in outcome.item.warning


def test_retriever_does_not_invent_generic_nutrition_when_no_sources() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    item = NutritionRetriever(router=router).lookup(IngredientEstimate(name="unknown meal", grams_min=100, grams_max=100))

    assert item is None


def test_retrieval_failure_records_unresolved_component_mass() -> None:
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    outcome = NutritionRetriever(router=router).lookup_with_diagnostics(
        IngredientEstimate(
            name="unknown meal",
            grams_min=80,
            grams_max=120,
            origin="llm_component",
        )
    )

    assert outcome.item is None
    assert outcome.failure is not None
    assert outcome.failure.grams_min == 80
    assert outcome.failure.grams_max == 120
    assert outcome.failure.component_origin == "llm_component"
    assert outcome.diagnostic.component_origin == "llm_component"


def test_open_food_facts_uses_bounded_query_expansions_for_branded_products() -> None:
    off = _FakeOpenFoodFactsClient()
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=off)  # type: ignore[arg-type]
    query = normalize_food_description("Сколько калорий в Сникерсе?", language="ru")

    candidates = router.retrieve_candidates(query, include_fallback=False)

    assert off.queries == [
        "Snickers",
        "Snickers bar",
        "Snickers chocolate bar",
        "Сколько калорий в Сникерсе?",
    ]
    assert len(off.queries) <= 5
    assert [candidate.source_id for candidate in candidates] == ["off-snickers"]


def test_open_food_facts_is_not_used_for_generic_foods() -> None:
    off = _FakeOpenFoodFactsClient()
    router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=off)  # type: ignore[arg-type]

    router.retrieve_candidates(normalize_food_description("banana"), include_fallback=False)

    assert off.queries == []


def test_secret_redaction() -> None:
    text = 'api_key=keyvalue Authorization: Bearer bearervalue client_secret="hiddenvalue" access_token="abcvalue"'
    redacted = redacted_text(text)

    assert "keyvalue" not in redacted
    assert "bearervalue" not in redacted
    assert "hiddenvalue" not in redacted
    assert "abcvalue" not in redacted
    assert "[REDACTED]" in redacted


def _candidate(
    *,
    source: str,
    source_id: str,
    name: str,
    calories: float,
    protein: float,
    fat: float,
    carbs: float,
    match_score: float,
) -> NutritionCandidate:
    return NutritionCandidate(
        source=source,
        source_id=source_id,
        name=name,
        food_type="prepared" if "pizza" in name.lower() or "lasagna" in name.lower() else "generic",
        metric_serving_amount=100,
        metric_serving_unit="g",
        match_score=match_score,
        score_components={"name": 0.34, "source": 0.3},
        values_per_100g=NutritionValues(
            calories_kcal=calories,
            protein_g=protein,
            fat_g=fat,
            carbohydrate_g=carbs,
        ),
    )


class _FakeOpenFoodFactsClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search_products(self, product_name: str, *, page_size: int = 5) -> list[NutritionCandidate]:
        self.queries.append(product_name)
        if "Snickers" not in product_name and "Сникерсе" not in product_name:
            return []
        return [
            NutritionCandidate(
                source="open_food_facts",
                source_id="off-snickers",
                name="Snickers",
                brand="Snickers",
                food_type="branded",
                values_per_100g=NutritionValues(
                    calories_kcal=500,
                    protein_g=8,
                    carbohydrate_g=62,
                    fat_g=24,
                ),
            )
        ]
