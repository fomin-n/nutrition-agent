import httpx

from app.tools.cache import JsonFileCache
from app.tools.usda_client import (
    USDA_DETAIL_URL,
    USDA_SEARCH_URL,
    UsdaClient,
    data_types_for_query_kind,
)


def test_usda_search_parsing(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(USDA_SEARCH_URL)
        return httpx.Response(
            200,
            json={
                "foods": [
                    {
                        "fdcId": 1,
                        "description": "Chicken breast, cooked",
                        "dataType": "SR Legacy",
                        "foodNutrients": [
                            {"nutrientName": "Energy", "unitName": "KCAL", "value": 165, "nutrientNumber": "1008"},
                            {"nutrientName": "Protein", "unitName": "G", "value": 31, "nutrientNumber": "1003"},
                            {"nutrientName": "Total lipid (fat)", "unitName": "G", "value": 3.6, "nutrientNumber": "1004"},
                            {
                                "nutrientName": "Carbohydrate, by difference",
                                "unitName": "G",
                                "value": 0,
                                "nutrientNumber": "1005",
                            },
                        ],
                    }
                ]
            },
        )

    client = UsdaClient("key", JsonFileCache(tmp_path), client=httpx.Client(transport=httpx.MockTransport(handler)))
    candidates = client.search_foods("chicken breast")

    assert len(candidates) == 1
    assert candidates[0].source == "usda"
    assert candidates[0].source_id == "1"
    assert candidates[0].metadata["data_type"] == "SR Legacy"
    assert candidates[0].values_per_100g is not None
    assert candidates[0].values_per_100g.protein_g == 31


def test_usda_food_details_parsing(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(f"{USDA_DETAIL_URL}/123")
        return httpx.Response(
            200,
            json={
                "fdcId": 123,
                "description": "Borscht soup",
                "dataType": "Survey (FNDDS)",
                "foodPortions": [
                    {
                        "amount": 1,
                        "gramWeight": 245,
                        "modifier": "bowl",
                        "measureUnit": {"name": "serving"},
                    }
                ],
                "foodNutrients": [
                    {"nutrient": {"id": 1008, "number": "1008", "name": "Energy", "unitName": "KCAL"}, "amount": 50},
                    {"nutrient": {"id": 1003, "number": "1003", "name": "Protein", "unitName": "G"}, "amount": 2},
                    {
                        "nutrient": {"id": 1004, "number": "1004", "name": "Total lipid (fat)", "unitName": "G"},
                        "amount": 1.4,
                    },
                    {
                        "nutrient": {
                            "id": 1005,
                            "number": "1005",
                            "name": "Carbohydrate, by difference",
                            "unitName": "G",
                        },
                        "amount": 7,
                    },
                    {"nutrient": {"id": 1093, "number": "1093", "name": "Sodium, Na", "unitName": "MG"}, "amount": 300},
                ],
            },
        )

    client = UsdaClient("key", JsonFileCache(tmp_path), client=httpx.Client(transport=httpx.MockTransport(handler)))
    candidate = client.get_food("123")

    assert candidate is not None
    assert candidate.food_type == "prepared"
    assert candidate.metric_serving_amount == 245
    assert candidate.values_per_100g is not None
    assert candidate.values_per_100g.sodium_mg == 300


def test_usda_missing_key_disables_provider(tmp_path) -> None:
    client = UsdaClient(None, JsonFileCache(tmp_path))
    assert client.search_foods("banana") == []
    assert client.get_food("1") is None


def test_usda_query_kind_data_types() -> None:
    assert data_types_for_query_kind("generic_ingredient")[0] == "Foundation"
    assert data_types_for_query_kind("standard_prepared_dish")[0] == "Survey (FNDDS)"
    assert data_types_for_query_kind("branded_product")[0] == "Branded"
