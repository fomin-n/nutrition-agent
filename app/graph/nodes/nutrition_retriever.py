import logging
import re

from app.graph.state import NutritionGraphState
from app.llm.client import get_settings, reveal_secret
from app.schemas.nutrition import IngredientEstimate, IngredientNutrition, NutritionPer100g
from app.tools.cache import JsonFileCache
from app.tools.fallback_nutrition import lookup_fallback_food
from app.tools.open_food_facts_client import OpenFoodFactsClient
from app.tools.usda_client import UsdaClient

LOGGER = logging.getLogger(__name__)


class NutritionRetriever:
    def __init__(self) -> None:
        settings = get_settings()
        cache = JsonFileCache(settings.nutrition_cache_dir)
        self.usda = UsdaClient(reveal_secret(settings.usda_api_key), cache)
        self.off = OpenFoodFactsClient(cache)

    def lookup(self, ingredient: IngredientEstimate, *, packaged: bool = False) -> IngredientNutrition:
        query = ingredient.name
        nutrition: NutritionPer100g | None = None
        warning: str | None = None

        if packaged:
            barcode = _extract_barcode(query)
            nutrition = self.off.lookup_barcode(barcode) if barcode else self.off.search_product(query)

        if nutrition is None:
            nutrition = lookup_fallback_food(query)

        if nutrition is None:
            nutrition = self.usda.search_food(query)

        if nutrition is None and not packaged:
            nutrition = self.off.search_product(query)

        if nutrition is None:
            nutrition = _generic_unknown_food(query)
            warning = f"No database match for {query}; used generic mixed-food fallback."

        return IngredientNutrition(
            ingredient_name=ingredient.name,
            matched_food_name=nutrition.food_name,
            grams_min=ingredient.grams_min,
            grams_max=ingredient.grams_max,
            per_100g=nutrition,
            source=nutrition.source,
            warning=warning,
        )


def retrieve_nutrition(state: NutritionGraphState) -> NutritionGraphState:
    meal = state.get("meal")
    if meal is None:
        return {"ingredient_nutrition": []}

    retriever = NutritionRetriever()
    packaged = state.get("scope_decision") is not None and state["scope_decision"].route == "packaged_food"
    items = [retriever.lookup(ingredient, packaged=packaged) for ingredient in meal.ingredients]
    return {"ingredient_nutrition": items}


def _extract_barcode(text: str) -> str | None:
    match = re.search(r"\b(\d{8,14})\b", text)
    return match.group(1) if match else None


def _generic_unknown_food(query: str) -> NutritionPer100g:
    LOGGER.info("Using generic mixed-food fallback for unmatched ingredient: %s", query)
    return NutritionPer100g(
        food_name="generic mixed food",
        calories_kcal=180,
        protein_g=8,
        fat_g=7,
        carbs_g=20,
        source="generic_fallback",
        source_id="generic_mixed_food",
    )

