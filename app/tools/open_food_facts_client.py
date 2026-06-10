import logging
from typing import Any

import httpx

from app.schemas.nutrition import NutritionPer100g
from app.tools.cache import JsonFileCache

LOGGER = logging.getLogger(__name__)


class OpenFoodFactsClient:
    def __init__(self, cache: JsonFileCache, timeout_seconds: float = 8.0) -> None:
        self.cache = cache
        self.timeout_seconds = timeout_seconds

    def search_product(self, product_name: str) -> NutritionPer100g | None:
        cache_key = f"off:search:{product_name.lower()}"
        cached = self.cache.get(cache_key)
        if cached:
            return _parse_off_product(cached)

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(
                    "https://world.openfoodfacts.org/cgi/search.pl",
                    params={
                        "search_terms": product_name,
                        "search_simple": 1,
                        "action": "process",
                        "json": 1,
                        "page_size": 1,
                    },
                    headers={"User-Agent": "nutrition-agent/0.1"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            LOGGER.warning("Open Food Facts product search failed for %s: %s", product_name, exc)
            return None

        products = payload.get("products") or []
        if not products:
            return None
        product = products[0]
        self.cache.set(cache_key, product)
        return _parse_off_product(product)

    def lookup_barcode(self, barcode: str) -> NutritionPer100g | None:
        cache_key = f"off:barcode:{barcode}"
        cached = self.cache.get(cache_key)
        if cached:
            return _parse_off_product(cached)

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(
                    f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json",
                    headers={"User-Agent": "nutrition-agent/0.1"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            LOGGER.warning("Open Food Facts barcode lookup failed for %s: %s", barcode, exc)
            return None

        product = payload.get("product")
        if not isinstance(product, dict):
            return None
        self.cache.set(cache_key, product)
        return _parse_off_product(product)


def _parse_off_product(product: dict[str, Any]) -> NutritionPer100g | None:
    nutriments = product.get("nutriments") or {}

    def number(*keys: str) -> float | None:
        for key in keys:
            value = nutriments.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    calories = number("energy-kcal_100g", "energy-kcal")
    protein = number("proteins_100g", "proteins")
    fat = number("fat_100g", "fat")
    carbs = number("carbohydrates_100g", "carbohydrates")
    if None in (calories, protein, fat, carbs):
        return None

    name = str(product.get("product_name") or product.get("generic_name") or "packaged food")
    source_id = str(product.get("code")) if product.get("code") else None
    return NutritionPer100g(
        food_name=name,
        calories_kcal=calories,
        protein_g=protein,
        fat_g=fat,
        carbs_g=carbs,
        source="open_food_facts",
        source_id=source_id,
    )

