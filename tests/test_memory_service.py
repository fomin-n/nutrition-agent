from concurrent.futures import ThreadPoolExecutor

from app.memory.service import (
    MemoryConfig,
    MemoryService,
    extract_long_term_facts,
)


def test_memory_context_isolated_by_user_and_conversation(tmp_path) -> None:
    service = MemoryService(tmp_path / "memory.sqlite3")

    service.record_turn(
        user_id=1,
        conversation_id=10,
        user_text="How many calories are in chicken?",
        assistant_text="I need one more detail.",
    )

    assert service.load_context(1, 10).recent_messages
    assert service.load_context(1, 11).recent_messages == []
    assert service.load_context(2, 10).recent_messages == []


def test_memory_persists_unresolved_task(tmp_path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    service = MemoryService(db_path)
    service.record_turn(
        user_id=1,
        conversation_id=10,
        user_text="How many calories are in chicken?",
        effective_text="How many calories are in chicken?",
        assistant_text="I need one more detail.",
        final_state={"final_estimate": {"text": "clarify", "confidence": "low", "is_clarification": True}},
    )

    reloaded = MemoryService(db_path)
    context = reloaded.load_context(1, 10)

    assert context.unresolved_task is not None
    assert context.unresolved_task.food_name == "chicken"
    assert context.unresolved_task.missing_fields == ["cut", "quantity", "preparation"]


def test_memory_compacts_old_messages_without_discarding_recent(tmp_path) -> None:
    service = MemoryService(
        tmp_path / "memory.sqlite3",
        MemoryConfig(recent_messages=4, summarize_after_messages=6, summary_max_chars=500),
    )

    for index in range(5):
        service.record_turn(
            user_id=1,
            conversation_id=10,
            user_text=f"meal {index}",
            assistant_text=f"answer {index}",
        )

    context = service.load_context(1, 10)

    assert context.summary
    assert len(context.recent_messages) == 4
    assert context.recent_messages[-1].text == "answer 4"


def test_memory_concurrent_writes_remain_isolated(tmp_path) -> None:
    service = MemoryService(tmp_path / "memory.sqlite3")

    def write_turn(index: int) -> None:
        service.record_turn(
            user_id=index % 3,
            conversation_id=index,
            user_text=f"meal {index}",
            assistant_text=f"answer {index}",
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write_turn, range(12)))

    for index in range(12):
        context = service.load_context(index % 3, index)
        assert context.recent_messages[0].text == f"meal {index}"
        assert context.recent_messages[1].text == f"answer {index}"


def test_extract_long_term_facts_stores_stable_nutrition_context_only() -> None:
    facts = extract_long_term_facts("I'm allergic to peanuts and prefer grams. My goal is to gain muscle.")

    assert ("allergy", "peanuts", "peanuts") in facts
    assert ("measurement_preference", "units", "metric") in facts
    assert ("goal", "gain_muscle", "gain muscle") in facts
