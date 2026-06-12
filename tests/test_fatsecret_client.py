from concurrent.futures import ThreadPoolExecutor

import httpx

from app.tools.fatsecret_client import (
    FATSECRET_REST_URL,
    FATSECRET_TOKEN_URL,
    FatSecretAuthClient,
    FatSecretClient,
)


def test_fatsecret_token_acquisition_and_reuse() -> None:
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        assert "Authorization" in request.headers
        token_calls += 1
        return httpx.Response(200, json={"access_token": "token-1", "token_type": "Bearer", "expires_in": 3600})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    auth = FatSecretAuthClient(client_id="id", client_secret="secret", client=client, sleep=lambda _: None)

    assert auth.get_access_token() == "token-1"
    assert auth.get_access_token() == "token-1"
    assert token_calls == 1


def test_fatsecret_token_refresh() -> None:
    now = 1000.0
    tokens = iter(["token-1", "token-2"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": next(tokens), "token_type": "Bearer", "expires_in": 100})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    auth = FatSecretAuthClient(
        client_id="id",
        client_secret="secret",
        client=client,
        now=lambda: now,
        token_margin_seconds=10,
        sleep=lambda _: None,
    )

    assert auth.get_access_token() == "token-1"
    now = 1095.0
    assert auth.get_access_token() == "token-2"


def test_fatsecret_concurrent_token_refresh_is_locked() -> None:
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        token_calls += 1
        return httpx.Response(200, json={"access_token": "shared-token", "token_type": "Bearer", "expires_in": 3600})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    auth = FatSecretAuthClient(client_id="id", client_secret="secret", client=client, sleep=lambda _: None)

    with ThreadPoolExecutor(max_workers=5) as executor:
        tokens = list(executor.map(lambda _: auth.get_access_token(), range(5)))

    assert tokens == ["shared-token"] * 5
    assert token_calls == 1


def test_fatsecret_search_parsing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == FATSECRET_TOKEN_URL:
            return httpx.Response(200, json={"access_token": "token", "token_type": "Bearer", "expires_in": 3600})
        assert str(request.url) == FATSECRET_REST_URL
        assert request.headers["Authorization"] == "Bearer token"
        return httpx.Response(
            200,
            json={
                "foods": {
                    "food": [
                        {
                            "food_id": "123",
                            "food_name": "Banana",
                            "food_type": "Generic",
                            "food_description": "Per 100g - Calories: 89kcal | Fat: 0.33g | Carbs: 22.84g | Protein: 1.09g",
                        }
                    ]
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    auth = FatSecretAuthClient(client_id="id", client_secret="secret", client=client, sleep=lambda _: None)
    foods = FatSecretClient(auth_client=auth, client=client, sleep=lambda _: None).search_foods("banana")

    assert len(foods) == 1
    assert foods[0].source == "fatsecret"
    assert foods[0].source_id == "123"
    assert foods[0].values_per_100g
    assert foods[0].values_per_100g.calories_kcal == 89


def test_fatsecret_food_get_serving_conversion() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == FATSECRET_TOKEN_URL:
            return httpx.Response(200, json={"access_token": "token", "token_type": "Bearer", "expires_in": 3600})
        return httpx.Response(
            200,
            json={
                "food": {
                    "food_id": "42",
                    "food_name": "Test Bar",
                    "food_type": "Brand",
                    "brand_name": "Acme",
                    "servings": {
                        "serving": {
                            "serving_description": "1 bar",
                            "metric_serving_amount": "50",
                            "metric_serving_unit": "g",
                            "calories": "250",
                            "protein": "10",
                            "carbohydrate": "30",
                            "fat": "8",
                        }
                    },
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    auth = FatSecretAuthClient(client_id="id", client_secret="secret", client=client, sleep=lambda _: None)
    food = FatSecretClient(auth_client=auth, client=client, sleep=lambda _: None).get_food("42")

    assert food is not None
    assert food.brand == "Acme"
    assert food.values_per_100g is not None
    assert food.values_per_100g.calories_kcal == 500
    assert food.to_per_100g() is not None


def test_fatsecret_missing_credentials_disable_provider() -> None:
    auth = FatSecretAuthClient(client_id=None, client_secret=None, sleep=lambda _: None)
    assert auth.get_access_token() is None
    assert FatSecretClient(auth_client=auth, sleep=lambda _: None).search_foods("banana") == []


def test_fatsecret_api_failures_degrade_gracefully() -> None:
    statuses = [401, 403, 429, 500]

    for status in statuses:
        def handler(request: httpx.Request, *, status: int = status) -> httpx.Response:
            if str(request.url) == FATSECRET_TOKEN_URL:
                return httpx.Response(200, json={"access_token": "token", "token_type": "Bearer", "expires_in": 3600})
            return httpx.Response(status, json={"error": {"message": "nope"}})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        auth = FatSecretAuthClient(client_id="id", client_secret="secret", client=client, sleep=lambda _: None)
        assert FatSecretClient(auth_client=auth, client=client, sleep=lambda _: None).search_foods("banana") == []


def test_fatsecret_malformed_response_degrades_gracefully() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == FATSECRET_TOKEN_URL:
            return httpx.Response(200, json={"access_token": "token", "token_type": "Bearer", "expires_in": 3600})
        return httpx.Response(200, content=b"not-json")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    auth = FatSecretAuthClient(client_id="id", client_secret="secret", client=client, sleep=lambda _: None)
    assert FatSecretClient(auth_client=auth, client=client, sleep=lambda _: None).search_foods("banana") == []
