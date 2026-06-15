from app.graph.graph import process_request
from app.graph.nodes import nutrition_retriever
from app.memory.service import MemoryService
from app.tools.nutrition_tools import NutritionSourceRouter


def test_chicken_followup_uses_conversation_memory(tmp_path) -> None:
    memory = MemoryService(tmp_path / "memory.sqlite3")

    first = process_request(
        text="How many calories are in chicken?",
        source="test",
        use_llm=False,
        user_id=1,
        session_id=10,
        memory_service=memory,
    )
    assert "cut of chicken" in first
    assert "how much" in first
    assert "prepared" in first

    second = process_request(
        text="100 g, fried.",
        source="test",
        use_llm=False,
        user_id=1,
        session_id=10,
        memory_service=memory,
    )
    assert "cut of chicken" in second
    assert "how much" not in second
    assert "prepared" not in second

    context = memory.load_context(1, 10)
    assert context.unresolved_task is not None
    assert context.unresolved_task.quantity == "100 g"
    assert context.unresolved_task.preparation == "fried"
    assert context.unresolved_task.missing_fields == ["cut"]


def test_chicken_followup_completes_after_cut(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        nutrition_retriever,
        "get_default_router",
        lambda: NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None),
    )
    memory = MemoryService(tmp_path / "memory.sqlite3")
    process_request(
        text="How many calories are in chicken?",
        source="test",
        use_llm=False,
        user_id=1,
        session_id=10,
        memory_service=memory,
    )
    process_request(
        text="100 g, fried.",
        source="test",
        use_llm=False,
        user_id=1,
        session_id=10,
        memory_service=memory,
    )

    final = process_request(
        text="breast",
        source="test",
        use_llm=False,
        user_id=1,
        session_id=10,
        memory_service=memory,
    )

    assert "Estimated calories:" in final
    assert "chicken" in final.lower()
    assert memory.load_context(1, 10).unresolved_task is None


def test_followup_memory_does_not_cross_conversations(tmp_path) -> None:
    memory = MemoryService(tmp_path / "memory.sqlite3")
    process_request(
        text="How many calories are in chicken?",
        source="test",
        use_llm=False,
        user_id=1,
        session_id=10,
        memory_service=memory,
    )

    answer = process_request(
        text="100 g, fried.",
        source="test",
        use_llm=False,
        user_id=1,
        session_id=11,
        memory_service=memory,
    )

    assert "What foods are in the meal" in answer


def test_followup_memory_does_not_cross_users(tmp_path) -> None:
    memory = MemoryService(tmp_path / "memory.sqlite3")
    process_request(
        text="How many calories are in chicken?",
        source="test",
        use_llm=False,
        user_id=1,
        session_id=10,
        memory_service=memory,
    )

    answer = process_request(
        text="100 g, fried.",
        source="test",
        use_llm=False,
        user_id=2,
        session_id=10,
        memory_service=memory,
    )

    assert "What foods are in the meal" in answer
