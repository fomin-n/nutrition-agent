import os

import pytest

from app.llm.client import get_settings, reveal_secret
from app.tools.fatsecret_client import FatSecretAuthClient, FatSecretClient
from app.tools.nutrition_tools import get_default_router
from app.tools.usda_client import data_types_for_query_kind

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_NUTRITION_TESTS") != "1",
    reason="live nutrition provider tests require RUN_LIVE_NUTRITION_TESTS=1",
)


def test_live_usda_search_when_configured() -> None:
    settings = get_settings()
    if not reveal_secret(settings.usda_api_key):
        pytest.skip("USDA_API_KEY is not configured")
    router = get_default_router()
    assert router.usda is not None
    results = router.usda.search_foods("banana", data_types=data_types_for_query_kind("generic_ingredient"), page_size=3)
    assert results


def test_live_fatsecret_search_when_configured() -> None:
    settings = get_settings()
    client_id = reveal_secret(settings.fatsecret_client_id)
    client_secret = reveal_secret(settings.fatsecret_client_secret)
    if not client_id or not client_secret:
        pytest.skip("FatSecret credentials are not configured")
    client = FatSecretClient(
        auth_client=FatSecretAuthClient(client_id=client_id, client_secret=client_secret),
    )
    results = client.search_foods("banana", max_results=3)
    if not results:
        pytest.skip("FatSecret live search returned no results; account/IP restrictions may apply")
    assert results
