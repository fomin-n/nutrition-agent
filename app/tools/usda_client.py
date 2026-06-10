import logging
from typing import Any

import httpx

from app.schemas.nutrition import NutritionPer100g
from app.tools.cache import JsonFileCache

LOGGER = logging.getLogger(__name__)

USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"


class UsdaClient:
    def __init__(self, api_key: str | None, cache: JsonFileCache, timeout_seconds: float = 8.0) -> None:
        self.api_key = api_key
        self.cache = cache
        self.timeout_seconds = timeout_seconds

    def search_food(self, query: str) -> NutritionPer100g | None:
        if not self.api_key:
            LOGGER.info("USDA_API_KEY missing; using fallback nutrition sources")
            return None

        cache_key = f"usda:search:{query.lower()}"
        cached = self.cache.get(cache_key)
        if cached:
            return self._parse_search_response(cached, query)

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(
                    USDA_SEARCH_URL,
                    params={
                        "api_key": self.api_key,
                        "query": query,
                        "pageSize": 5,
                        "dataType": ["SR Legacy", "Foundation", "Survey (FNDDS)"],
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            LOGGER.warning("USDA lookup failed for %s: %s", query, exc)
            return None

        self.cache.set(cache_key, payload)
        return self._parse_search_response(payload, query)

    def _parse_search_response(self, payload: dict[str, Any], query: str) -> NutritionPer100g | None:
        foods = payload.get("foods") or []
        for food in foods:
            parsed = _parse_usda_food(food)
            if parsed is not None:
                return parsed
        LOGGER.info("USDA lookup returned no usable nutrition for %s", query)
        return None


def _parse_usda_food(food: dict[str, Any]) -> NutritionPer100g | None:
    nutrients = food.get("foodNutrients") or []
    values: dict[str, float] = {}

    for nutrient in nutrients:
        name = str(nutrient.get("nutrientName", "")).lower()
        value = nutrient.get("value")
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue

        if "energy" in name and "kcal" in str(nutrient.get("unitName", "")).lower():
            values["calories_kcal"] = numeric
        elif name == "energy":
            values.setdefault("calories_kcal", numeric)
        elif "protein" in name:
            values["protein_g"] = numeric
        elif "total lipid" in name or name == "fat":
            values["fat_g"] = numeric
        elif "carbohydrate, by difference" in name or name == "carbohydrate":
            values["carbs_g"] = numeric

    required = {"calories_kcal", "protein_g", "fat_g", "carbs_g"}
    if not required.issubset(values):
        return None

    return NutritionPer100g(
        food_name=str(food.get("description") or "USDA food"),
        calories_kcal=values["calories_kcal"],
        protein_g=values["protein_g"],
        fat_g=values["fat_g"],
        carbs_g=values["carbs_g"],
        source="usda",
        source_id=str(food.get("fdcId")) if food.get("fdcId") else None,
    )

