import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from app import execution
from app.bot import handlers
from app.graph.nodes.calculator import calculate_totals
from app.graph.nodes.nutrition_retriever import NutritionRetriever
from app.graph.nodes.packaging_recognizer import meal_from_label
from app.llm import client
from app.schemas.nutrition import IngredientEstimate, MealUnderstanding, NutritionValues
from app.schemas.packaging import ObservedNutritionLabel, PackagingObservation
from app.tools.cache import JsonFileCache
from app.tools.food_query import normalize_food_description
from app.tools.image_utils import encode_image_data_url
from app.tools.meal_validation import validate_meal
from app.tools.nutrition_tools import CandidateSelection, NutritionSourceRouter, _dedupe_candidates
from app.tools.open_food_facts_client import OpenFoodFactsClient


def test_deadline_stops_new_work_and_restores_context(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(execution.time, "monotonic", lambda: now[0])
    with execution.request_budget(3):
        assert execution.bounded_timeout(45) == 3
        now[0] += 4
        with pytest.raises(TimeoutError):
            execution.bounded_timeout(8)
    assert execution.bounded_timeout(8) == 8


def test_luna_default_is_bounded_and_preserves_other_model_roles(monkeypatch):
    for name in (
        "OPENAI_TEXT_MODEL", "OPENAI_VISION_MODEL", "OPENAI_VISION_ESCALATION_MODEL",
        "OPENAI_CRITIC_MODEL", "OPENAI_REASONING_EFFORT", "OPENAI_TEXT_REASONING_EFFORT",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = client.Settings(_env_file=None, openai_api_key=SecretStr("unit-test-placeholder"))
    captured = {}
    monkeypatch.setattr(client, "get_settings", lambda: settings)
    monkeypatch.setattr(client, "ChatOpenAI", lambda **kwargs: captured.update(kwargs))
    client.build_chat_model("gpt-6-luna", task="critic")
    assert captured["reasoning_effort"] == "none"
    assert captured["max_tokens"] == settings.openai_critic_max_output_tokens
    assert settings.openai_text_model == "gpt-6-luna"
    assert settings.openai_vision_model == "gpt-4.1-mini"
    assert settings.openai_vision_escalation_model == "gpt-5.4-mini"
    assert settings.openai_critic_model == "gpt-4.1-mini"
    for task in ("text", "scope"):
        client.build_chat_model(settings.openai_text_model, task=task)
        assert captured["reasoning_effort"] == "none"
        assert captured["temperature"] == 0
    client.build_chat_model(settings.openai_critic_model, task="critic")
    assert captured["reasoning_effort"] is None
    settings.openai_reasoning_effort = "low"
    client.build_chat_model("gpt-6-luna")
    assert captured["temperature"] is None
    with pytest.raises(ValueError):
        client.build_chat_model("gpt-4.1-mini")


def test_image_size_rejected_before_read(tmp_path, monkeypatch):
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"x" * 1025)
    monkeypatch.setattr(
        "app.tools.image_utils.get_settings", lambda: SimpleNamespace(max_image_bytes=1024)
    )
    with pytest.raises(ValueError, match="byte limit"):
        encode_image_data_url(path)


def test_label_is_scaled_deterministically_and_requires_consumed_mass():
    label = ObservedNutritionLabel(
        basis="per_serving", serving_grams=50, calories_kcal=100, protein_g=5, fat_g=4, carbs_g=11
    )
    observation = PackagingObservation(
        is_food=True, product_name="test packaged snack", label=label
    )
    assert meal_from_label(observation, caption="", language="en").needs_clarification
    meal = meal_from_label(observation, caption="100 g eaten", language="en")
    assert not validate_meal(meal, "100 g eaten", allow_observed_label=True)
    assert "nutrition_label_requires_packaging_image" in validate_meal(meal, "100 g eaten")
    item = NutritionRetriever(NutritionSourceRouter()).lookup(meal.ingredients[0])
    assert item is not None
    assert item.per_100g.calories_kcal == 200
    assert calculate_totals([item]).calories_kcal.min == 200
    assert item.candidate.source == "observed_label"


def test_candidate_boundary_rejects_injected_invalid_selection():
    router = NutritionSourceRouter()
    query = normalize_food_description("apple")
    original = router.select_candidate(query)
    invalid = original.selected.model_copy(
        update={
            "values_per_100g": NutritionValues(
                calories_kcal=5000, protein_g=0, fat_g=0, carbohydrate_g=0
            )
        }
    )
    router.select_candidate = lambda query: replace(original, selected=invalid)
    outcome = NutritionRetriever(router).lookup_with_diagnostics(
        IngredientEstimate(name="apple", grams_min=100, grams_max=100)
    )
    assert outcome.item is None
    assert outcome.failure is not None


def test_class_prior_validation_is_authoritative(monkeypatch):
    from app.graph.nodes import nutrition_retriever
    from app.schemas.nutrition import CandidateValidationResult

    router = NutritionSourceRouter()
    router.select_candidate = lambda query: CandidateSelection(None, [], [])
    monkeypatch.setattr(
        nutrition_retriever,
        "validate_candidate",
        lambda *args: CandidateValidationResult(accepted=False, reasons=["rejected"]),
    )
    outcome = NutritionRetriever(router).lookup_with_diagnostics(
        IngredientEstimate(name="mushrooms", grams_min=50, grams_max=50)
    )
    assert outcome.item is None


def test_serving_id_remains_part_of_candidate_identity():
    candidate = (
        NutritionSourceRouter().select_candidate(normalize_food_description("apple")).selected
    )
    other = candidate.model_copy(update={"serving_id": "other"})
    assert len(_dedupe_candidates([candidate, other, candidate])) == 2


def test_duplicate_food_diagnostics_keep_occurrence_contributions():
    from app.graph.nodes.calculator import calculate_macros

    retriever = NutritionRetriever(NutritionSourceRouter())
    outcomes = [
        retriever.lookup_with_diagnostics(
            IngredientEstimate(name="apple", grams_min=g, grams_max=g)
        )
        for g in (100, 200)
    ]
    result = calculate_macros(
        {
            "ingredient_nutrition": [o.item for o in outcomes],
            "retrieval_diagnostics": [o.diagnostic for o in outcomes],
        }
    )
    calories = [
        d.calculated_totals["calories_kcal"]["min"] for d in result["retrieval_diagnostics"]
    ]
    assert calories == [50, 100]
    assert result["totals"].calories_kcal.min == 160


def test_off_reuses_injected_client_and_cache(tmp_path):
    import httpx

    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "products": [
                    {
                        "code": "123",
                        "product_name": "test",
                        "nutriments": {
                            "energy-kcal_100g": 100,
                            "proteins_100g": 4,
                            "fat_100g": 2,
                            "carbohydrates_100g": 16,
                        },
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        off = OpenFoodFactsClient(JsonFileCache(tmp_path), client=http)
        first = off.search_products("test")
        second = off.search_products("test")
        assert len(calls) == 1
        assert first[0].stable_identity == second[0].stable_identity
        assert not http.is_closed


def test_delivery_failure_does_not_commit_memory(monkeypatch):
    written = []

    def process(**kwargs):
        kwargs["defer_memory_write"](lambda: written.append(True))
        return "answer"

    monkeypatch.setattr(handlers, "process_request", process)
    monkeypatch.setattr(handlers, "_reply", AsyncMock(side_effect=OSError("delivery failed")))
    update = SimpleNamespace(effective_user=None, effective_chat=None, effective_message=None)
    with pytest.raises(OSError):
        asyncio.run(handlers._process_and_reply(update, text="meal"))
    assert written == []


def test_schema_rejects_many_ingredients():
    item = IngredientEstimate(name="apple", grams_min=100, grams_max=100)
    with pytest.raises(ValueError):
        MealUnderstanding(ingredients=[item] * 13)


def test_clarification_cannot_smuggle_ingredients_into_calculation(monkeypatch):
    from app.graph.nodes.nutrition_retriever import retrieve_nutrition

    meal = MealUnderstanding(
        needs_clarification=True,
        ingredients=[IngredientEstimate(name="apple", grams_min=3000, grams_max=3000)],
    )
    monkeypatch.setattr(
        NutritionRetriever,
        "lookup_with_diagnostics",
        lambda *args, **kwargs: pytest.fail("must not retrieve"),
    )
    result = retrieve_nutrition({"meal": meal})
    assert result["meal"].ingredients == []
    assert result["ingredient_nutrition"] == []


def test_usda_details_are_deduplicated_and_bounded(monkeypatch):
    from app.schemas.nutrition import NutritionCandidate

    details = []
    searches = []
    candidates = [
        NutritionCandidate(source="usda", source_id=str(i), name="apple") for i in range(8)
    ]

    class FakeUsda:
        enabled = True

        def search_foods(self, query, **kwargs):
            searches.append(query)
            assert kwargs["require_details"] is False
            return candidates

        def get_food(self, food_id):
            details.append(food_id)
            return candidates[int(food_id)]

    monkeypatch.setattr(
        "app.tools.nutrition_tools.get_settings", lambda: SimpleNamespace(usda_detail_limit=3)
    )
    query = normalize_food_description("apple")
    rows = NutritionSourceRouter(usda=FakeUsda())._usda_candidates(query)
    assert searches
    assert len(details) == len(set(details)) == 3
    assert len(rows) == 8


@pytest.mark.parametrize(
    "nutriments",
    [
        {"energy-kcal_serving": 100, "proteins": 5, "fat": 2, "carbohydrates": 15},
        {"energy-kcal_100g": "nan", "proteins_100g": 5, "fat_100g": 2, "carbohydrates_100g": 15},
        ["malformed"],
    ],
)
def test_off_rejects_ambiguous_basis_and_nonfinite_rows(nutriments):
    from app.tools.open_food_facts_client import _parse_off_product

    assert _parse_off_product({"nutriments": nutriments}).to_per_100g() is None


def test_packaging_requires_readable_label_and_food_identity():
    assert meal_from_label(
        PackagingObservation(is_food=False), caption="100 g", language="en"
    ).needs_clarification
    assert meal_from_label(
        PackagingObservation(is_food=True, product_name="snack"), caption="100 g", language="en"
    ).needs_clarification
    with pytest.raises(ValueError):
        ObservedNutritionLabel(
            basis="per_serving", calories_kcal=100, protein_g=5, fat_g=2, carbs_g=15
        )


def test_packaging_wrapper_uses_label_schema_and_one_bounded_escalation(monkeypatch, tmp_path):
    from app.graph.nodes import packaging_recognizer as packaging

    photo = tmp_path / "fixture.jpg"
    photo.write_bytes(b"synthetic image bytes")
    label = ObservedNutritionLabel(
        basis="per_100g", calories_kcal=100, protein_g=5, fat_g=4, carbs_g=11
    )
    responses = iter(
        [
            PackagingObservation(
                is_food=True, product_name="snack", label=label, confidence="medium"
            ),
            PackagingObservation(
                is_food=True, product_name="snack", label=label, confidence="high"
            ),
        ]
    )
    models = []

    class Model:
        def with_structured_output(self, schema):
            assert schema is PackagingObservation
            return self

        def invoke(self, messages):
            assert "image_url" in str(messages)
            return next(responses)

    def build(name, *, task):
        assert task == "vision"
        models.append(name)
        return Model()

    monkeypatch.setattr(packaging, "build_chat_model", build)
    monkeypatch.setattr(
        packaging,
        "get_settings",
        lambda: SimpleNamespace(
            openai_vision_model="base",
            openai_vision_escalation_model="escalated",
            openai_vision_escalation_confidence="medium",
        ),
    )
    observation = packaging.read_packaging_observation(
        image_path=str(photo), mime_type="image/jpeg", caption="100 g eaten"
    )
    assert observation.confidence == "high"
    assert models == ["base", "escalated"]


def test_benchmark_requires_opt_in_and_restores_model_configuration(monkeypatch, tmp_path):
    import os

    from app.evals import benchmark_models

    with pytest.raises(SystemExit):
        benchmark_models.main([])
    monkeypatch.setenv("OPENAI_TEXT_MODEL", "original-model")
    calls = []

    def fake_run(examples, **kwargs):
        assert kwargs["live_providers"] is False
        calls.append((os.environ["OPENAI_TEXT_MODEL"], [e.metadata.id for e in examples]))
        return {}

    monkeypatch.setattr(benchmark_models, "run_golden_eval", fake_run)
    monkeypatch.setattr(
        benchmark_models,
        "write_golden_results",
        lambda *args: (tmp_path / "run.json", tmp_path / "run.md"),
    )
    assert benchmark_models.main(["--allow-paid-api", "--max-examples", "1"]) == 0
    assert [call[0] for call in calls] == [
        "gpt-4.1-mini",
        "gpt-6-luna",
        "gpt-6-luna",
        "gpt-4.1-mini",
    ]
    assert all(call[1] == calls[0][1] for call in calls)
    assert os.environ["OPENAI_TEXT_MODEL"] == "original-model"
