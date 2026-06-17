import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.schemas.nutrition import NutritionCandidate, NutritionValues
from app.tools.fallback_nutrition import normalize_food_query
from app.tools.provider_utils import (
    ProviderUnavailableError,
    log_provider_failure,
    request_json_with_retries,
    retrieval_span,
)

LOGGER = logging.getLogger(__name__)

FATSECRET_TOKEN_URL = "https://oauth.fatsecret.com/connect/token"
FATSECRET_REST_URL = "https://platform.fatsecret.com/rest/server.api"


@dataclass
class FatSecretToken:
    access_token: str
    expires_at: float
    token_type: str = "Bearer"


class FatSecretAuthClient:
    def __init__(
        self,
        *,
        client_id: str | None,
        client_secret: str | None,
        timeout_seconds: float = 8.0,
        token_margin_seconds: float = 90.0,
        client: httpx.Client | None = None,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout_seconds = timeout_seconds
        self.token_margin_seconds = token_margin_seconds
        self.client = client
        self.now = now
        self.sleep = sleep
        self._token: FatSecretToken | None = None
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def get_access_token(self) -> str | None:
        if not self.enabled:
            LOGGER.info("FatSecret credentials missing; provider disabled")
            return None
        token = self._token
        if token is not None and token.expires_at - self.token_margin_seconds > self.now():
            return token.access_token
        with self._lock:
            token = self._token
            if token is not None and token.expires_at - self.token_margin_seconds > self.now():
                return token.access_token
            self._token = self._fetch_token()
            return self._token.access_token

    def invalidate_token(self) -> None:
        with self._lock:
            self._token = None

    def _fetch_token(self) -> FatSecretToken:
        def request() -> httpx.Response:
            client = self.client or httpx.Client(timeout=self.timeout_seconds)
            try:
                return client.post(
                    FATSECRET_TOKEN_URL,
                    auth=(self.client_id or "", self.client_secret or ""),
                    data={"grant_type": "client_credentials", "scope": "basic"},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            finally:
                if self.client is None:
                    client.close()

        payload = request_json_with_retries(
            request,
            provider="fatsecret",
            operation="token",
            max_retries=1,
            sleep=self.sleep,
        )
        access_token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        token_type = str(payload.get("token_type") or "Bearer")
        if not access_token or not expires_in:
            raise ProviderUnavailableError("fatsecret", "token", "token response missing fields")
        try:
            ttl = float(expires_in)
        except (TypeError, ValueError) as exc:
            raise ProviderUnavailableError("fatsecret", "token", "invalid expires_in") from exc
        return FatSecretToken(access_token=str(access_token), token_type=token_type, expires_at=self.now() + ttl)


class FatSecretClient:
    def __init__(
        self,
        *,
        auth_client: FatSecretAuthClient,
        timeout_seconds: float = 8.0,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.auth_client = auth_client
        self.timeout_seconds = timeout_seconds
        self.client = client
        self.sleep = sleep

    @property
    def enabled(self) -> bool:
        return self.auth_client.enabled

    def search_foods(
        self,
        query: str,
        *,
        page: int = 0,
        max_results: int = 20,
        region: str | None = None,
        language: str | None = None,
    ) -> list[NutritionCandidate]:
        if not self.enabled:
            LOGGER.info("FatSecret credentials missing; skipping search")
            return []
        params: dict[str, str | int] = {
            "method": "foods.search",
            "search_expression": query,
            "page_number": page,
            "max_results": min(max_results, 50),
            "format": "json",
        }
        candidates = self._call_food_method("foods.search", params, query=query)
        return [_parse_search_food(item, region=region, language=language) for item in _food_list(candidates)]

    def get_food(
        self,
        food_id: str,
        *,
        region: str | None = None,
        language: str | None = None,
    ) -> NutritionCandidate | None:
        if not self.enabled:
            LOGGER.info("FatSecret credentials missing; skipping food.get")
            return None
        payload = self._call_food_method(
            "food.get",
            {"method": "food.get", "food_id": food_id, "format": "json"},
            query=food_id,
        )
        food = payload.get("food")
        if not isinstance(food, dict):
            return None
        return _parse_food_details(food, region=region, language=language)

    def _call_food_method(self, operation: str, params: dict[str, str | int], *, query: str) -> dict[str, Any]:
        try:
            token = self.auth_client.get_access_token()
        except ProviderUnavailableError as exc:
            log_provider_failure(LOGGER, exc, query=query)
            return {}
        if token is None:
            return {}

        def request() -> httpx.Response:
            client = self.client or httpx.Client(timeout=self.timeout_seconds)
            try:
                return client.post(
                    FATSECRET_REST_URL,
                    data=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
            finally:
                if self.client is None:
                    client.close()

        with retrieval_span("fatsecret", operation, query=normalize_food_query(query)):
            try:
                payload = request_json_with_retries(
                    request,
                    provider="fatsecret",
                    operation=operation,
                    max_retries=2,
                    sleep=self.sleep,
                )
            except ProviderUnavailableError as exc:
                if exc.status_code == 401:
                    self.auth_client.invalidate_token()
                log_provider_failure(LOGGER, exc, query=query)
                return {}

        error = payload.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message") or "API error"
            LOGGER.warning(
                "FatSecret operation=%s returned api_error_code=%s message=%s",
                operation,
                code,
                _safe_fatsecret_error_message(code, str(message)),
            )
            return {}
        return payload


def _food_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    foods = payload.get("foods")
    if not isinstance(foods, dict):
        return []
    food = foods.get("food")
    if isinstance(food, list):
        return [item for item in food if isinstance(item, dict)]
    if isinstance(food, dict):
        return [food]
    return []


def _parse_search_food(food: dict[str, Any], *, region: str | None, language: str | None) -> NutritionCandidate:
    name = str(food.get("food_name") or "FatSecret food")
    brand = _string_or_none(food.get("brand_name"))
    food_type = _fatsecret_food_type(food)
    values = _parse_food_description(str(food.get("food_description") or ""))
    return NutritionCandidate(
        source="fatsecret",
        source_id=str(food.get("food_id")) if food.get("food_id") else None,
        name=name,
        brand=brand,
        food_type=food_type,
        description=_string_or_none(food.get("food_description")),
        region=region,
        language=language,
        serving_description="search result summary" if values else None,
        metric_serving_amount=100.0 if values else None,
        metric_serving_unit="g" if values else None,
        calories_kcal=values.calories_kcal if values else None,
        protein_g=values.protein_g if values else None,
        carbohydrate_g=values.carbohydrate_g if values else None,
        fat_g=values.fat_g if values else None,
        values_per_100g=values,
        source_confidence="medium",
        metadata={"food_url": _string_or_none(food.get("food_url"))},
    )


def _parse_food_details(food: dict[str, Any], *, region: str | None, language: str | None) -> NutritionCandidate:
    servings = food.get("servings")
    serving = None
    if isinstance(servings, dict):
        serving_items = servings.get("serving")
        if isinstance(serving_items, list):
            serving = _best_serving(serving_items)
        elif isinstance(serving_items, dict):
            serving = serving_items
    serving = serving if isinstance(serving, dict) else {}
    values = _values_from_serving(serving)
    values_per_100g = _per_100g_from_serving(serving, values)
    return NutritionCandidate(
        source="fatsecret",
        source_id=str(food.get("food_id")) if food.get("food_id") else None,
        serving_id=str(serving.get("serving_id")) if serving.get("serving_id") else None,
        name=str(food.get("food_name") or "FatSecret food"),
        brand=_string_or_none(food.get("brand_name")),
        food_type=_fatsecret_food_type(food),
        description=_string_or_none(food.get("food_description")),
        region=region,
        language=language,
        serving_description=_string_or_none(serving.get("serving_description")),
        serving_amount=_float_or_none(serving.get("number_of_units")),
        serving_unit=_string_or_none(serving.get("measurement_description")),
        metric_serving_amount=_float_or_none(serving.get("metric_serving_amount")),
        metric_serving_unit=_string_or_none(serving.get("metric_serving_unit")),
        calories_kcal=values.calories_kcal,
        protein_g=values.protein_g,
        carbohydrate_g=values.carbohydrate_g,
        fat_g=values.fat_g,
        fiber_g=values.fiber_g,
        sugar_g=values.sugar_g,
        sodium_mg=values.sodium_mg,
        values_per_100g=values_per_100g,
        source_confidence="high" if values_per_100g and values_per_100g.has_required_macros() else "medium",
        metadata={"food_url": _string_or_none(food.get("food_url"))},
    )


def _best_serving(servings: list[Any]) -> dict[str, Any]:
    dict_servings = [serving for serving in servings if isinstance(serving, dict)]
    for serving in dict_servings:
        amount = _float_or_none(serving.get("metric_serving_amount"))
        unit = normalize_food_query(str(serving.get("metric_serving_unit") or ""))
        if amount and abs(amount - 100.0) < 0.001 and unit in {"g", "gram", "grams"}:
            return serving
    for serving in dict_servings:
        unit = normalize_food_query(str(serving.get("metric_serving_unit") or ""))
        if _float_or_none(serving.get("metric_serving_amount")) and unit in {"g", "gram", "grams"}:
            return serving
    return dict_servings[0] if dict_servings else {}


def _values_from_serving(serving: dict[str, Any]) -> NutritionValues:
    return NutritionValues(
        calories_kcal=_float_or_none(serving.get("calories")),
        protein_g=_float_or_none(serving.get("protein")),
        carbohydrate_g=_float_or_none(serving.get("carbohydrate")),
        fat_g=_float_or_none(serving.get("fat")),
        fiber_g=_float_or_none(serving.get("fiber")),
        sugar_g=_float_or_none(serving.get("sugar")),
        sodium_mg=_float_or_none(serving.get("sodium")),
    )


def _per_100g_from_serving(serving: dict[str, Any], values: NutritionValues) -> NutritionValues | None:
    amount = _float_or_none(serving.get("metric_serving_amount"))
    unit = normalize_food_query(str(serving.get("metric_serving_unit") or ""))
    if amount is None or amount <= 0 or unit not in {"g", "gram", "grams"}:
        return None
    factor = 100.0 / amount
    return _scale_values(values, factor)


def _parse_food_description(description: str) -> NutritionValues | None:
    if not description:
        return None
    lowered = description.lower()
    if "100g" not in lowered and "100 g" not in lowered:
        return None

    def match(pattern: str) -> float | None:
        found = re.search(pattern, description, flags=re.IGNORECASE)
        if not found:
            return None
        return _float_or_none(found.group(1))

    values = NutritionValues(
        calories_kcal=match(r"calories:\s*([0-9.]+)\s*kcal"),
        fat_g=match(r"fat:\s*([0-9.]+)\s*g"),
        carbohydrate_g=match(r"carbs:\s*([0-9.]+)\s*g"),
        protein_g=match(r"protein:\s*([0-9.]+)\s*g"),
    )
    return values if values.has_required_macros() else None


def _scale_values(values: NutritionValues, factor: float) -> NutritionValues:
    return NutritionValues(
        calories_kcal=_scale(values.calories_kcal, factor),
        protein_g=_scale(values.protein_g, factor),
        carbohydrate_g=_scale(values.carbohydrate_g, factor),
        fat_g=_scale(values.fat_g, factor),
        fiber_g=_scale(values.fiber_g, factor),
        sugar_g=_scale(values.sugar_g, factor),
        sodium_mg=_scale(values.sodium_mg, factor),
    )


def _scale(value: float | None, factor: float) -> float | None:
    return round(value * factor, 4) if value is not None else None


def _safe_fatsecret_error_message(code: Any, message: str) -> str:
    if str(code) == "21":
        return "account or IP restriction"
    lowered = message.lower()
    if "scope" in lowered or "premier" in lowered or "not allowed" in lowered:
        return "account capability restriction"
    return "API error"


def _fatsecret_food_type(food: dict[str, Any]) -> str:
    food_type = normalize_food_query(str(food.get("food_type") or ""))
    if "brand" in food_type:
        return "branded"
    if _string_or_none(food.get("brand_name")):
        return "branded"
    return "generic"


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
