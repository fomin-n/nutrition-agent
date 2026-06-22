import json
from pathlib import Path

import httpx
import pytest

from app.evals.compare_golden_runs import build_comparison, render_comparison_markdown
from app.evals.golden import evaluate_answer, load_golden_examples, parse_nutrition_ranges
from app.evals.phoenix_datasets import upload_golden_dataset
from app.evals.run_golden_eval import run_golden_eval, write_golden_results

DATASET = Path("evals/datasets/nutrition_agent_phoenix_eval_datasets_v2.jsonl")
SINGLE_TURN_DATASET = Path("evals/datasets/nutrition_agent_golden_single_turn_v2.jsonl")
CONVERSATION_DATASET = Path("evals/datasets/nutrition_agent_golden_conversations_v1.jsonl")
BASELINE_SMOKE = Path(
    "reports/eval/baseline/golden_baseline_smoke_20260620T012752900358Z.json"
)
BASELINE_GOLDEN = Path(
    "reports/eval/baseline/golden_baseline_golden_20260620T012752900266Z.json"
)


def test_golden_loader_validates_and_filters_examples() -> None:
    all_examples = load_golden_examples(DATASET)
    single_turn = load_golden_examples(SINGLE_TURN_DATASET)
    conversations = load_golden_examples(CONVERSATION_DATASET)
    smoke = load_golden_examples(DATASET, split="smoke")
    memory = load_golden_examples(DATASET, tags=["memory"])

    assert len(all_examples) == 111
    assert len(single_turn) == 101
    assert len(conversations) == 10
    assert all(example.input.kind == "single_turn" for example in single_turn)
    assert all(example.input.kind == "conversation" for example in conversations)
    assert len(smoke) == 18
    assert len(memory) == 8
    assert {example.input.kind for example in all_examples} == {"single_turn", "conversation"}
    assert len({example.metadata.id for example in all_examples}) == 111


def test_golden_loader_rejects_duplicate_ids(tmp_path) -> None:
    example = load_golden_examples(DATASET)[0]
    duplicate_path = tmp_path / "duplicate.jsonl"
    duplicate_path.write_text(
        example.model_dump_json() + "\n" + example.model_dump_json() + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate golden example IDs"):
        load_golden_examples(duplicate_path)


def test_golden_answer_evaluator_uses_behavior_text_and_range_overlap() -> None:
    example = load_golden_examples(DATASET)[0]
    answer = (
        "Оценка калорий: 90-120 ккал\n"
        "Белки: 1-2 г\n"
        "Жиры: 0-1 г\n"
        "Углеводы: 25-29 г"
    )

    evaluation = evaluate_answer(example, answer)

    assert evaluation["passed"] is True
    assert evaluation["status"] == "pass"
    assert evaluation["actual_behavior"] == "estimate"
    assert evaluation["numeric_checks"]["required_calorie_check"] == "pass"
    assert parse_nutrition_ranges(answer)["carbs_g"] == {"min": 25.0, "max": 29.0}


def test_golden_text_checks_normalize_typographic_apostrophes() -> None:
    example = next(
        item
        for item in load_golden_examples(DATASET)
        if item.metadata.id == "na_conv_006_pending_then_unsafe_not_merged"
    )

    evaluation = evaluate_answer(example, "I can’t help with that request.")

    assert evaluation["text_checks"]["matched"] == ["can't help"]


def test_golden_answer_evaluator_marks_unparsed_calories_unknown() -> None:
    example = load_golden_examples(DATASET)[0]
    evaluation = evaluate_answer(example, "Оценка калорий приведена в приложении.")

    assert evaluation["status"] == "unknown"
    assert evaluation["failed_checks"] == []
    assert evaluation["unknown_checks"] == ["calories: answer could not be parsed"]


def test_golden_conversation_runner_captures_effective_text_and_memory(tmp_path) -> None:
    example = next(
        item
        for item in load_golden_examples(DATASET)
        if item.metadata.id == "na_conv_003_ru_fish_followup"
    )

    run = run_golden_eval(
        [example],
        dataset_path=DATASET,
        split="smoke",
        use_llm=False,
        live_providers=False,
    )
    json_path, markdown_path = write_golden_results(run, tmp_path)

    assert run["summary"]["passed"] == 1
    assert run["summary"]["failed"] == 0
    assert run["summary"]["unknown"] == 0
    result = run["examples"][0]
    assert result["execution"]["turns"][-1]["effective_text"] == "лосось, 200 г, запеченный"
    assert result["execution"]["final_unresolved_task"] is None
    assert json_path.exists()
    assert "na_conv_003_ru_fish_followup" not in markdown_path.read_text(encoding="utf-8")


def test_phoenix_upload_preserves_structured_rows_and_stable_ids() -> None:
    example = load_golden_examples(DATASET)[0]
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"data": [], "next_cursor": None})
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": {
                    "dataset_id": "dataset-1",
                    "version_id": "version-1",
                    "num_created_examples": 1,
                    "num_updated_examples": 0,
                    "num_deleted_examples": 0,
                }
            },
        )

    client = httpx.Client(base_url="http://phoenix", transport=httpx.MockTransport(handler))
    result = upload_golden_dataset(
        [example],
        name="nutrition-agent-test",
        description="test",
        base_url="http://phoenix",
        client=client,
    )
    client.close()

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["action"] == "create"
    assert payload["inputs"][0]["kind"] == "single_turn"
    assert payload["outputs"][0]["expected_behavior"] == "estimate"
    assert payload["metadata"][0]["id"] == example.metadata.id
    assert payload["example_ids"] == [example.metadata.id]
    assert payload["splits"] == [example.splits]
    assert result["dataset_id"] == "dataset-1"


def test_golden_comparison_reports_metrics_and_remaining_failures() -> None:
    baseline_smoke = json.loads(BASELINE_SMOKE.read_text(encoding="utf-8"))
    baseline_golden = json.loads(BASELINE_GOLDEN.read_text(encoding="utf-8"))

    comparison = build_comparison(
        baseline_smoke,
        baseline_golden,
        baseline_smoke,
        baseline_golden,
    )
    markdown = render_comparison_markdown(comparison)

    assert comparison["metrics"]["full_golden"]["delta"] == 0
    assert comparison["remaining_failure_count"] == 82
    assert comparison["categories_regressed"] == []
    assert "## Top Remaining Failures" in markdown
