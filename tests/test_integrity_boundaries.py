from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import pytest

from app.graph import graph
from app.graph.nodes import text_parser
from app.graph.nodes.nutrition_retriever import NutritionRetriever
from app.memory.service import (
    MemoryConfig,
    MemoryService,
    extract_long_term_facts,
    memory_context_prompt,
)
from app.schemas.inputs import NormalizedInput
from app.schemas.nutrition import IngredientEstimate, MealUnderstanding
from app.schemas.outputs import FinalEstimate
from app.tools.food_normalization import find_food_mentions
from app.tools.meal_validation import validate_meal
from app.tools.nutrition_tools import NutritionSourceRouter


@pytest.mark.parametrize(
    "text,grams",
    [
        ("100 g apple and 200 g apple", [100, 200]),
        ("Snickers 50 g and Snickers 50 g", [50, 50]),
        ("100 г яблока и 200 г яблока", [100, 200]),
        ("2 tbsp peanut butter, 32g", [32]),
    ],
)
def test_occurrences_and_weighed_mass(text, grams):
    meal = text_parser.parse_text_locally(text)
    assert [item.grams_min for item in meal.ingredients] == grams
    assert not validate_meal(meal, text)


@pytest.mark.parametrize("amount,unit", [(100, "g"), (0.1, "kg"), (3.52734, "oz")])
def test_mass_units_and_scaling(amount, unit):
    meal = text_parser.parse_text_locally(f"{amount}{unit} apple")
    assert meal.ingredients[0].grams_min == pytest.approx(100, abs=0.02)
    doubled = text_parser.parse_text_locally(f"{2 * amount}{unit} apple")
    assert doubled.ingredients[0].grams_min == 2 * meal.ingredients[0].grams_min


def test_twice_rejected_model_never_returns_original_parse():
    invalid = MealUnderstanding(
        ingredients=[IngredientEstimate(name="durian", grams_min=3000, grams_max=3000)]
    )
    state = {
        "normalized_input": NormalizedInput(text="100 g durian", has_text=True, language="en"),
        "use_llm": True,
    }
    with (
        patch.object(text_parser, "has_openai_key", return_value=True),
        patch.object(
            text_parser,
            "_try_parse_text_with_llm",
            return_value=invalid,
        ) as parser,
    ):
        meal = text_parser.parse_text_meal(state)["meal"]
    assert parser.call_count == 2
    assert meal.needs_clarification
    assert not meal.ingredients


def test_unparsed_dish_mass_is_not_an_estimate():
    state = {
        "normalized_input": NormalizedInput(
            text="fish and chips, 450 g", has_text=True, language="en"
        ),
        "use_llm": False,
    }
    meal = text_parser.parse_text_meal(state)["meal"]
    assert meal.needs_clarification
    assert not meal.ingredients


def test_preparation_is_not_silently_substituted():
    retriever = NutritionRetriever(NutritionSourceRouter())
    cooked = IngredientEstimate(
        name="cooked white rice", preparation="cooked", grams_min=100, grams_max=100
    )
    assert retriever.lookup(cooked) is not None
    for preparation in ("raw", "dry"):
        assert retriever.lookup(cooked.model_copy(update={"preparation": preparation})) is None


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_ingredient_weights_must_be_finite(value):
    with pytest.raises(ValueError):
        IngredientEstimate(name="apple", grams_min=value, grams_max=value)


def test_mentions_keep_occurrence_identity():
    mentions = find_food_mentions("100g apple and 200g apple")
    assert len(mentions) == 2
    assert mentions[0].end < mentions[1].start


def test_forget_invalidates_in_flight_write_after_restart(tmp_path):
    service = MemoryService(tmp_path / "memory.sqlite3")
    context = service.load_context(1, 10)
    service.delete_user_data(1)
    restarted = MemoryService(service.db_path)
    restarted.record_turn(
        user_id=1,
        conversation_id=10,
        user_text="old",
        assistant_text="old",
        expected_generation=context.generation,
    )
    assert restarted.load_context(1, 10).recent_messages == []
    restarted.record_turn(
        user_id=1, conversation_id=10, user_text="new", assistant_text="new", expected_generation=1
    )
    assert len(restarted.load_context(1, 10).recent_messages) == 2


def test_forget_during_request_cannot_restore_memory(tmp_path, monkeypatch):
    entered, release = Event(), Event()
    service = MemoryService(tmp_path / "memory.sqlite3")

    class DelayedGraph:
        def invoke(self, state):
            entered.set()
            assert release.wait(5)
            return {"final_estimate": FinalEstimate(text="answer")}

    monkeypatch.setattr(graph, "get_compiled_graph", DelayedGraph)
    with ThreadPoolExecutor(max_workers=1) as pool:
        request = pool.submit(
            graph.process_request,
            text="apple",
            user_id=1,
            session_id=10,
            use_llm=False,
            memory_service=service,
        )
        assert entered.wait(5)
        service.delete_user_data(1)
        release.set()
        assert request.result(5) == "answer"
    assert service.load_context(1, 10).recent_messages == []


@pytest.mark.parametrize(
    "text",
    [
        "I am not vegan",
        "I am not allergic to peanuts",
        "My friend is vegan",
        "Мой друг веган",
        "Я не веган",
        "У меня нет аллергии на арахис",
    ],
)
def test_negation_and_other_people_are_not_stable_facts(text):
    assert not extract_long_term_facts(text)


def test_retraction_and_parser_evidence(tmp_path):
    service = MemoryService(
        tmp_path / "memory.sqlite3", MemoryConfig(recent_messages=2, summarize_after_messages=4)
    )
    for text in ["I am vegan", "I am no longer vegan", "apple", "banana"]:
        service.record_turn(
            user_id=1,
            conversation_id=10,
            user_text=text,
            assistant_text="PRIVATE_ESTIMATE 999 kcal",
        )
    context = service.load_context(1, 10)
    assert not context.facts
    assert context.summary
    assert "PRIVATE_ESTIMATE" not in memory_context_prompt(context)


def test_memory_write_failure_does_not_drop_completed_answer(tmp_path, monkeypatch):
    service = MemoryService(tmp_path / "memory.sqlite3")
    monkeypatch.setattr(
        service, "record_turn", lambda **kw: (_ for _ in ()).throw(OSError("private"))
    )

    class Graph:
        def invoke(self, state):
            return {"final_estimate": FinalEstimate(text="completed")}

    monkeypatch.setattr(graph, "get_compiled_graph", Graph)
    assert (
        graph.process_request(text="apple", user_id=1, use_llm=False, memory_service=service)
        == "completed"
    )


@pytest.mark.parametrize(
    "text",
    [
        "Я думаю, мой друг веган",
        "I am happy and my friend is allergic to peanuts",
        "Я сказала, что она веган",
        "My friend is vegan",
    ],
)
def test_third_person_facts_are_not_personal_memory(text):
    from app.memory.service import extract_long_term_facts

    assert extract_long_term_facts(text) == []


def test_personal_allergy_list_is_preserved():
    facts = extract_long_term_facts("I am allergic to peanuts and almonds, milk.")
    assert {key for kind, key, value in facts if kind == "allergy"} == {
        "peanuts",
        "almonds",
        "milk",
    }


def test_preparation_does_not_leak_between_components():
    meal = text_parser.parse_text_locally("100 g rice and 100 g fried chicken breast")
    assert [item.preparation for item in meal.ingredients] == [None, "fried"]


def test_instant_noodles_phrase_is_not_cooked_preparation():
    from app.graph.nodes.text_parser import parse_text_locally

    meal = parse_text_locally(
        "Сколько БЖУ в пачке лапши быстрого приготовления 85 г?", language="ru"
    )
    assert meal.ingredients[0].preparation is None
    assert meal.ingredients[0].grams_min == 85
