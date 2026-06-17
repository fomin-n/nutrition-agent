import logging
from typing import Any

import httpx

from app.schemas.nutrition import NutritionCandidate, NutritionPer100g, NutritionValues
from app.tools.cache import JsonFileCache
from app.tools.fallback_nutrition import normalize_food_query

LOGGER = logging.getLogger(__name__)


class OpenFoodFactsClient:
    def __init__(self, cache: JsonFileCache, timeout_seconds: float = 8.0) -> None:
        self.cache = cache
        self.timeout_seconds = timeout_seconds

    def search_product(self, product_name: str) -> NutritionPer100g | None:
        candidates = self.search_products(product_name, page_size=1)
        if not candidates:
            return None
        return candidates[0].to_per_100g()

    def search_products(self, product_name: str, *, page_size: int = 5) -> list[NutritionCandidate]:
        cache_key = f"off:search:v2:{normalize_food_query(product_name)}:page_size={page_size}"
        cached = self.cache.get(cache_key)
        if cached:
            return [_parse_off_product(product) for product in _cached_products(cached)]

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(
                    "https://world.openfoodfacts.org/cgi/search.pl",
                    params={
                        "search_terms": product_name,
                        "search_simple": 1,
                        "action": "process",
                        "json": 1,
                        "page_size": page_size,
                    },
                    headers={"User-Agent": "nutrition-agent/0.1"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            LOGGER.warning("Open Food Facts product search failed for %s: %s", product_name, exc)
            return []

        products = payload.get("products") or []
        if not products:
            return []
        self.cache.set(cache_key, {"products": products})
        return [_parse_off_product(product) for product in products if isinstance(product, dict)]

    def lookup_barcode(self, barcode: str) -> NutritionPer100g | None:
        candidate = self.get_barcode_candidate(barcode)
        return candidate.to_per_100g() if candidate else None

    def get_barcode_candidate(self, barcode: str) -> NutritionCandidate | None:
        cache_key = f"off:barcode:v2:{barcode}"
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


def _cached_products(cached: dict[str, Any]) -> list[dict[str, Any]]:
    products = cached.get("products")
    if isinstance(products, list):
        return [product for product in products if isinstance(product, dict)]
    return [cached]


def _parse_off_product(product: dict[str, Any]) -> NutritionCandidate:
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
    values = NutritionValues(
        calories_kcal=calories,
        protein_g=protein,
        fat_g=fat,
        carbohydrate_g=carbs,
        fiber_g=number("fiber_100g", "fiber"),
        sugar_g=number("sugars_100g", "sugars"),
        sodium_mg=_sodium_mg(number("sodium_100g", "sodium")),
    )

    name = str(product.get("product_name") or product.get("generic_name") or "packaged food")
    source_id = str(product.get("code")) if product.get("code") else None
    return NutritionCandidate(
        source="open_food_facts",
        source_id=source_id,
        name=name,
        brand=str(product.get("brands")) if product.get("brands") else None,
        food_type="branded",
        description=str(product.get("generic_name")) if product.get("generic_name") else None,
        serving_description=str(product.get("serving_size")) if product.get("serving_size") else None,
        metric_serving_amount=None,
        metric_serving_unit=None,
        calories_kcal=values.calories_kcal,
        protein_g=values.protein_g,
        fat_g=values.fat_g,
        carbohydrate_g=values.carbohydrate_g,
        fiber_g=values.fiber_g,
        sugar_g=values.sugar_g,
        sodium_mg=values.sodium_mg,
        values_per_100g=values if values.has_required_macros() else None,
        source_confidence="medium",
        metadata={"quantity": product.get("quantity"), "categories": product.get("categories")},
    )


def _sodium_mg(value: float | None) -> float | None:
    if value is None:
        return None
    return value * 1000
