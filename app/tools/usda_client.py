import logging
from typing import Any

import httpx

from app.schemas.nutrition import NutritionCandidate, NutritionPer100g, NutritionValues
from app.tools.cache import JsonFileCache
from app.tools.fallback_nutrition import normalize_food_query
from app.tools.provider_utils import (
    ProviderUnavailableError,
    log_provider_failure,
    request_json_with_retries,
    retrieval_span,
)

LOGGER = logging.getLogger(__name__)

USDA_API_BASE = "https://api.nal.usda.gov/fdc/v1"
USDA_SEARCH_URL = f"{USDA_API_BASE}/foods/search"
USDA_DETAIL_URL = f"{USDA_API_BASE}/food"
GENERIC_DATA_TYPES = ["Foundation", "SR Legacy", "Survey (FNDDS)"]
PREPARED_DATA_TYPES = ["Survey (FNDDS)", "Foundation", "SR Legacy"]
BRANDED_DATA_TYPES = ["Branded", "Survey (FNDDS)", "Foundation", "SR Legacy"]


class UsdaClient:
    def __init__(
        self,
        api_key: str | None,
        cache: JsonFileCache,
        timeout_seconds: float = 8.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.cache = cache
        self.timeout_seconds = timeout_seconds
        self.client = client

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def search_foods(
        self,
        query: str,
        *,
        data_types: list[str] | None = None,
        page_size: int = 10,
        require_details: bool = False,
    ) -> list[NutritionCandidate]:
        if not self.api_key:
            LOGGER.info("USDA_API_KEY missing; USDA provider disabled")
            return []

        data_types = data_types or GENERIC_DATA_TYPES
        cache_key = f"usda:search:v2:{normalize_food_query(query)}:{','.join(data_types)}:{page_size}"
        cached = self.cache.get(cache_key)
        if cached:
            candidates = self._parse_search_response(cached, query)
        else:
            try:
                with retrieval_span("usda", "foods.search", query=normalize_food_query(query)):
                    payload = self._request_search(query, data_types=data_types, page_size=page_size)
            except ProviderUnavailableError as exc:
                log_provider_failure(LOGGER, exc, query=query)
                return []
            self.cache.set(cache_key, payload)
            candidates = self._parse_search_response(payload, query)

        if require_details:
            detailed: list[NutritionCandidate] = []
            for candidate in candidates[: min(len(candidates), 5)]:
                if candidate.source_id:
                    detail = self.get_food(candidate.source_id)
                    detailed.append(detail or candidate)
                else:
                    detailed.append(candidate)
            return detailed
        return candidates

    def get_food(self, fdc_id: str) -> NutritionCandidate | None:
        if not self.api_key:
            LOGGER.info("USDA_API_KEY missing; USDA provider disabled")
            return None
        cache_key = f"usda:food:v2:{fdc_id}"
        cached = self.cache.get(cache_key)
        if cached:
            return _parse_usda_food(cached)
        try:
            with retrieval_span("usda", "food.get", source_id=fdc_id):
                payload = self._request_food(fdc_id)
        except ProviderUnavailableError as exc:
            log_provider_failure(LOGGER, exc, query=fdc_id)
            return None
        self.cache.set(cache_key, payload)
        return _parse_usda_food(payload)

    def search_food(self, query: str) -> NutritionPer100g | None:
        candidates = self.search_foods(query, data_types=GENERIC_DATA_TYPES, page_size=5, require_details=False)
        for candidate in candidates:
            per_100g = candidate.to_per_100g()
            if per_100g is not None:
                return per_100g
        LOGGER.info("USDA lookup returned no usable nutrition for %s", query)
        return None

    def _request_search(self, query: str, *, data_types: list[str], page_size: int) -> dict[str, Any]:
        def request() -> httpx.Response:
            client = self.client or httpx.Client(timeout=self.timeout_seconds)
            try:
                return client.post(
                    USDA_SEARCH_URL,
                    params={"api_key": self.api_key},
                    json={
                        "query": query,
                        "pageSize": page_size,
                        "dataType": data_types,
                    },
                )
            finally:
                if self.client is None:
                    client.close()

        return request_json_with_retries(request, provider="usda", operation="foods.search")

    def _request_food(self, fdc_id: str) -> dict[str, Any]:
        def request() -> httpx.Response:
            client = self.client or httpx.Client(timeout=self.timeout_seconds)
            try:
                return client.get(f"{USDA_DETAIL_URL}/{fdc_id}", params={"api_key": self.api_key})
            finally:
                if self.client is None:
                    client.close()

        return request_json_with_retries(request, provider="usda", operation="food.get")

    def _parse_search_response(self, payload: dict[str, Any], query: str) -> list[NutritionCandidate]:
        foods = payload.get("foods") or []
        candidates = [_parse_usda_food(food) for food in foods if isinstance(food, dict)]
        result = [candidate for candidate in candidates if candidate is not None]
        if not result:
            LOGGER.info("USDA lookup returned no usable nutrition for %s", query)
        return result


def data_types_for_query_kind(query_kind: str) -> list[str]:
    if query_kind in {"branded_product", "restaurant_menu_item"}:
        return BRANDED_DATA_TYPES
    if query_kind in {"standard_prepared_dish", "user_composite_meal", "photo_derived_food"}:
        return PREPARED_DATA_TYPES
    return GENERIC_DATA_TYPES


def _parse_usda_food(food: dict[str, Any]) -> NutritionCandidate | None:
    values = _parse_nutrients(food.get("foodNutrients") or [])
    if not values.has_required_macros():
        return None
    data_type = _string_or_none(food.get("dataType"))
    food_type = _food_type_from_data_type(data_type)
    portions = food.get("foodPortions") or []
    serving = _best_portion(portions)
    metric_serving_amount = _float_or_none(serving.get("gramWeight")) if serving else None
    serving_description = _serving_description(serving)
    brand = _string_or_none(food.get("brandName")) or _string_or_none(food.get("brandOwner"))
    name = str(food.get("description") or food.get("lowercaseDescription") or "USDA food")
    return NutritionCandidate(
        source="usda",
        source_id=str(food.get("fdcId")) if food.get("fdcId") else None,
        serving_id=(
            str(serving.get("id") or serving.get("foodPortionId"))
            if serving and (serving.get("id") or serving.get("foodPortionId"))
            else None
        ),
        name=name,
        brand=brand,
        food_type=food_type,
        description=_string_or_none(food.get("additionalDescriptions")) or _string_or_none(food.get("ingredients")),
        serving_description=serving_description,
        serving_amount=_float_or_none(serving.get("amount")) if serving else None,
        serving_unit=_string_or_none(serving.get("measureUnit", {}).get("name")) if serving else None,
        metric_serving_amount=metric_serving_amount,
        metric_serving_unit="g" if metric_serving_amount else None,
        calories_kcal=values.calories_kcal,
        protein_g=values.protein_g,
        carbohydrate_g=values.carbohydrate_g,
        fat_g=values.fat_g,
        fiber_g=values.fiber_g,
        sugar_g=values.sugar_g,
        sodium_mg=values.sodium_mg,
        values_per_100g=values,
        source_confidence="high" if data_type in {"Foundation", "SR Legacy", "Survey (FNDDS)"} else "medium",
        metadata={
            "data_type": data_type,
            "food_category": _string_or_none(food.get("foodCategory")),
            "publication_date": _string_or_none(food.get("publicationDate")),
        },
    )


def _parse_nutrients(nutrients: list[Any]) -> NutritionValues:
    values: dict[str, float] = {}
    for item in nutrients:
        if not isinstance(item, dict):
            continue
        name, unit, value = _nutrient_name_unit_value(item)
        if value is None:
            continue
        name_l = name.lower()
        unit_l = unit.lower()
        number = str(item.get("nutrientNumber") or item.get("number") or "")
        nutrient_id = str(item.get("nutrientId") or item.get("id") or "")
        if (number == "1008" or nutrient_id == "1008" or "energy" in name_l) and "kj" not in unit_l:
            values["calories_kcal"] = value
        elif number == "1003" or nutrient_id == "1003" or name_l == "protein":
            values["protein_g"] = value
        elif number == "1004" or nutrient_id == "1004" or "total lipid" in name_l or name_l == "fat":
            values["fat_g"] = value
        elif number == "1005" or nutrient_id == "1005" or "carbohydrate, by difference" in name_l:
            values["carbohydrate_g"] = value
        elif number == "1079" or nutrient_id == "1079" or "fiber" in name_l:
            values["fiber_g"] = value
        elif number == "2000" or nutrient_id == "2000" or "sugars" in name_l:
            values["sugar_g"] = value
        elif number == "1093" or nutrient_id == "1093" or name_l == "sodium, na":
            values["sodium_mg"] = value
    return NutritionValues(**values)


def _nutrient_name_unit_value(item: dict[str, Any]) -> tuple[str, str, float | None]:
    nested = item.get("nutrient")
    if isinstance(nested, dict):
        name = str(nested.get("name") or item.get("nutrientName") or "")
        unit = str(nested.get("unitName") or item.get("unitName") or "")
        value = _float_or_none(item.get("amount") if item.get("amount") is not None else item.get("value"))
        return name, unit, value
    return (
        str(item.get("nutrientName") or item.get("name") or ""),
        str(item.get("unitName") or ""),
        _float_or_none(item.get("value") if item.get("value") is not None else item.get("amount")),
    )


def _best_portion(portions: list[Any]) -> dict[str, Any]:
    candidates = [portion for portion in portions if isinstance(portion, dict)]
    for portion in candidates:
        if _float_or_none(portion.get("gramWeight")) and _float_or_none(portion.get("amount")) == 1:
            return portion
    return candidates[0] if candidates else {}


def _serving_description(portion: dict[str, Any]) -> str | None:
    if not portion:
        return None
    modifier = _string_or_none(portion.get("modifier"))
    amount = _float_or_none(portion.get("amount"))
    unit = None
    measure = portion.get("measureUnit")
    if isinstance(measure, dict):
        unit = _string_or_none(measure.get("name"))
    parts = [str(amount).rstrip("0").rstrip(".") if amount else None, unit, modifier]
    return " ".join(part for part in parts if part)


def _food_type_from_data_type(data_type: str | None) -> str:
    if data_type == "Branded":
        return "branded"
    if data_type == "Survey (FNDDS)":
        return "prepared"
    if data_type in {"Foundation", "SR Legacy"}:
        return "generic"
    return "unknown"


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
