import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from app.graph.nodes.nutrition_retriever import LookupOutcome, _lookup_ingredients
from app.llm.client import Settings
from app.schemas.nutrition import (
    IngredientEstimate,
    IngredientNutrition,
    NutritionPer100g,
    RetrievalDiagnostic,
)
from app.tools.cache import JsonFileCache


def test_concurrent_lookups_keep_input_order() -> None:
    delays = {"first": 0.06, "second": 0.03, "third": 0.01}

    class FakeRetriever:
        def lookup_with_diagnostics(self, ingredient: IngredientEstimate, **_: object) -> LookupOutcome:
            time.sleep(delays[ingredient.name])
            return _successful_outcome(ingredient)

    ingredients = [_ingredient(name) for name in delays]
    outcomes = _run_lookups(FakeRetriever(), ingredients, max_workers=3)

    assert [outcome.item.ingredient_name for outcome in outcomes if outcome.item] == list(delays)
    assert [outcome.diagnostic.ingredient_name for outcome in outcomes] == list(delays)


def test_concurrent_lookup_exception_is_isolated() -> None:
    class FakeRetriever:
        def lookup_with_diagnostics(self, ingredient: IngredientEstimate, **_: object) -> LookupOutcome:
            if ingredient.name == "broken":
                raise RuntimeError("provider failure")
            return _successful_outcome(ingredient)

    ingredients = [_ingredient(name) for name in ("first", "broken", "third")]
    outcomes = _run_lookups(FakeRetriever(), ingredients, max_workers=3)

    assert outcomes[0].item is not None
    assert outcomes[1].item is None
    assert outcomes[1].failure is not None
    assert outcomes[1].failure.ingredient_name == "broken"
    assert outcomes[1].failure.reason == "unexpected_retrieval_error"
    assert outcomes[2].item is not None


def test_concurrent_lookup_respects_worker_cap() -> None:
    lock = threading.Lock()
    active = 0
    peak_active = 0

    class FakeRetriever:
        def lookup_with_diagnostics(self, ingredient: IngredientEstimate, **_: object) -> LookupOutcome:
            nonlocal active, peak_active
            with lock:
                active += 1
                peak_active = max(peak_active, active)
            try:
                time.sleep(0.03)
                return _successful_outcome(ingredient)
            finally:
                with lock:
                    active -= 1

    ingredients = [_ingredient(f"item-{index}") for index in range(6)]
    outcomes = _run_lookups(FakeRetriever(), ingredients, max_workers=2)

    assert len(outcomes) == 6
    assert peak_active == 2


def test_json_cache_remains_readable_during_concurrent_writes(tmp_path) -> None:
    cache = JsonFileCache(tmp_path)

    def write_and_read(writer: int) -> None:
        for version in range(10):
            cache.set("shared", {"writer": writer, "version": version})
            value = cache.get("shared")
            assert value is not None
            assert set(value) == {"writer", "version"}

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write_and_read, range(4)))


def test_retrieval_worker_setting_is_bounded() -> None:
    assert Settings(nutrition_retrieval_max_workers=3).nutrition_retrieval_max_workers == 3
    with pytest.raises(ValidationError):
        Settings(nutrition_retrieval_max_workers=0)
    with pytest.raises(ValidationError):
        Settings(nutrition_retrieval_max_workers=9)


def _run_lookups(
    retriever: object,
    ingredients: list[IngredientEstimate],
    *,
    max_workers: int,
) -> list[LookupOutcome]:
    return _lookup_ingredients(  # type: ignore[arg-type]
        retriever,
        ingredients,
        source_route="text_meal",
        language="en",
        request_id="test-request",
        raw_input="test meal",
        max_workers=max_workers,
    )


def _ingredient(name: str) -> IngredientEstimate:
    return IngredientEstimate(name=name, grams_min=100, grams_max=100)


def _successful_outcome(ingredient: IngredientEstimate) -> LookupOutcome:
    item = IngredientNutrition(
        ingredient_name=ingredient.name,
        matched_food_name=ingredient.name,
        grams_min=ingredient.grams_min,
        grams_max=ingredient.grams_max,
        per_100g=NutritionPer100g(
            food_name=ingredient.name,
            calories_kcal=100,
            protein_g=10,
            fat_g=4,
            carbs_g=8,
            source="test",
        ),
        source="test",
    )
    diagnostic = RetrievalDiagnostic(
        request_id="test-request",
        ingredient_name=ingredient.name,
        canonical_query=ingredient.name,
        food_category="food",
        product_variant="unknown",
        amount_min_g=ingredient.grams_min,
        amount_max_g=ingredient.grams_max,
    )
    return LookupOutcome(item=item, failure=None, diagnostic=diagnostic)
