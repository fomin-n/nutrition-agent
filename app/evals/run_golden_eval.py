import argparse
import json
from collections import defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.evals.golden import (
    DEFAULT_GOLDEN_DATASET,
    GoldenExample,
    evaluate_answer,
    load_golden_examples,
)
from app.graph.graph import process_request
from app.graph.nodes import nutrition_retriever
from app.memory.service import MemoryService
from app.tools.fallback_nutrition import normalize_food_query
from app.tools.nutrition_tools import NutritionSourceRouter

DEFAULT_OUTPUT_DIR = Path("reports/eval")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic NutritionAgent golden evals.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_GOLDEN_DATASET)
    parser.add_argument("--split", help="Only run examples assigned to this split.")
    parser.add_argument("--tag", action="append", default=[], help="Require a metadata tag; repeatable.")
    parser.add_argument("--max-examples", type=int)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--use-llm", action="store_true", help="Override examples and enable LLM paths.")
    parser.add_argument(
        "--allow-paid-api",
        action="store_true",
        help="Required with --use-llm to prevent accidental paid calls.",
    )
    parser.add_argument(
        "--live-providers",
        action="store_true",
        help="Use configured nutrition providers instead of deterministic local fallbacks.",
    )
    args = parser.parse_args(argv)
    if args.use_llm and not args.allow_paid_api:
        parser.error("--use-llm requires --allow-paid-api")
    if args.max_examples is not None and args.max_examples < 1:
        parser.error("--max-examples must be at least 1")

    try:
        examples = load_golden_examples(args.dataset, split=args.split, tags=args.tag)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.max_examples is not None:
        examples = examples[: args.max_examples]
    if not examples:
        parser.error("No examples matched the requested filters")

    run_output = run_golden_eval(
        examples,
        dataset_path=args.dataset,
        split=args.split,
        tags=args.tag,
        use_llm=args.use_llm,
        live_providers=args.live_providers,
    )
    json_path, markdown_path = write_golden_results(run_output, args.output_dir)
    print(
        json.dumps(
            {
                "summary": run_output["summary"],
                "json_path": str(json_path),
                "markdown_path": str(markdown_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    summary = run_output["summary"]
    return 0 if summary["failed"] == 0 and summary["unknown"] == 0 else 1


def run_golden_eval(
    examples: Sequence[GoldenExample],
    *,
    dataset_path: str | Path,
    split: str | None = None,
    tags: Sequence[str] = (),
    use_llm: bool = False,
    live_providers: bool = False,
) -> dict[str, Any]:
    timestamp = datetime.now(UTC)
    with _retrieval_mode(live_providers=live_providers):
        results = [_run_example(example, use_llm=use_llm) for example in examples]
    passed = sum(1 for result in results if result["status"] == "pass")
    failed = sum(1 for result in results if result["status"] == "fail")
    unknown = sum(1 for result in results if result["status"] == "unknown")
    total = len(results)
    summary = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "unknown": unknown,
        "pass_rate": passed / total if total else 0.0,
        "breakdowns": _build_breakdowns(examples, results),
        "issue_classifications": _count_issue_classifications(results),
    }
    run_scope = split or "all"
    return {
        "run_id": f"golden_baseline_{run_scope}_{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}",
        "timestamp_utc": timestamp.isoformat(),
        "dataset_path": str(Path(dataset_path)),
        "filters": {"split": split, "tags": list(tags)},
        "config": {
            "use_llm": use_llm,
            "live_providers": live_providers,
            "macro_ranges_are_advisory": True,
        },
        "summary": summary,
        "examples": results,
    }


def write_golden_results(run_output: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_output["run_id"]
    json_path = output_dir / f"{run_id}.json"
    markdown_path = output_dir / f"{run_id}.md"
    json_path.write_text(json.dumps(run_output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_render_markdown(run_output), encoding="utf-8")
    return json_path, markdown_path


def _run_example(example: GoldenExample, *, use_llm: bool) -> dict[str, Any]:
    try:
        if example.input.kind == "single_turn":
            answer, execution = _run_single_turn(example, use_llm=use_llm)
        else:
            answer, execution = _run_conversation(example, use_llm=use_llm)
        evaluation = evaluate_answer(example, answer)
        memory_failures = _evaluate_conversation_expectations(example, execution)
        evaluation["failed_checks"].extend(memory_failures)
        status = (
            "fail"
            if evaluation["failed_checks"]
            else "unknown"
            if evaluation["unknown_checks"]
            else "pass"
        )
        evaluation["status"] = status
        evaluation["passed"] = status == "pass"
        issue_classification = _classify_issue(evaluation)
        return {
            "id": example.metadata.id,
            "kind": example.input.kind,
            "language": example.metadata.language or example.input.language,
            "category": example.metadata.category,
            "tags": example.metadata.tags,
            "input": _input_summary(example),
            "answer": answer,
            "execution": execution,
            "evaluation": evaluation,
            "failed_checks": evaluation["failed_checks"],
            "unknown_checks": evaluation["unknown_checks"],
            "issue_classification": issue_classification,
            "status": status,
            "passed": status == "pass",
        }
    except Exception as exc:
        return {
            "id": example.metadata.id,
            "kind": example.input.kind,
            "language": example.metadata.language or example.input.language,
            "category": example.metadata.category,
            "tags": example.metadata.tags,
            "input": _input_summary(example),
            "answer": "",
            "execution": {},
            "evaluation": {},
            "failed_checks": [f"execution_error: {type(exc).__name__}: {exc}"],
            "unknown_checks": [],
            "issue_classification": "evaluator_issue",
            "status": "fail",
            "passed": False,
        }


def _classify_issue(evaluation: dict[str, Any]) -> str | None:
    failures = evaluation["failed_checks"]
    unknowns = evaluation["unknown_checks"]
    if not failures and not unknowns:
        return None
    if not failures:
        return "evaluator_issue"
    if any(
        failure.startswith(("execution_error:", "unsupported_memory_assertion:"))
        for failure in failures
    ):
        return "evaluator_issue"

    expected = evaluation.get("expected_behavior")
    actual = evaluation.get("actual_behavior")
    if expected != actual:
        if expected == "estimate" and actual in {"clarify", "refuse", "unknown"}:
            return "unsupported_current_behavior"
        return "real_system_failure"
    if any(
        failure.startswith(("calories:", "memory_assertion_failed:"))
        for failure in failures
    ):
        return "real_system_failure"
    if all(failure.startswith(("must_contain_any:", "must_not_contain_any:")) for failure in failures):
        return "likely_dataset_issue"
    return "real_system_failure"


def _count_issue_classifications(results: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for result in results:
        classification = result.get("issue_classification")
        if classification:
            counts[classification] += 1
    return dict(sorted(counts.items()))


def _run_single_turn(example: GoldenExample, *, use_llm: bool) -> tuple[str, dict[str, Any]]:
    user_input = example.input.user_input
    if user_input is None:
        raise ValueError("single-turn example has no user_input")
    answer = process_request(
        text=user_input.text,
        image_path=user_input.image_path,
        image_mime_type=user_input.image_mime_type,
        source=user_input.source or "phoenix_eval",
        use_llm=use_llm,
    )
    return answer, {"turns": [{"text": user_input.text, "answer": answer}]}


def _run_conversation(example: GoldenExample, *, use_llm: bool) -> tuple[str, dict[str, Any]]:
    with TemporaryDirectory(prefix="nutrition-agent-golden-") as directory:
        memory = MemoryService(Path(directory) / "memory.sqlite3")
        user_id = f"golden:{example.metadata.id}"
        session_id = "conversation"
        turns: list[dict[str, Any]] = []
        answer = ""
        for turn in example.input.turns:
            context = memory.load_context(user_id, session_id)
            prepared = memory.prepare_input(turn.text, context)
            answer = process_request(
                text=turn.text,
                image_path=turn.image_path,
                image_mime_type=turn.image_mime_type,
                source=turn.source or "phoenix_eval",
                use_llm=use_llm,
                user_id=user_id,
                session_id=session_id,
                memory_service=memory,
            )
            turns.append(
                {
                    "text": turn.text,
                    "effective_text": prepared.effective_text,
                    "used_followup": prepared.used_followup,
                    "answer": answer,
                }
            )
        final_context = memory.load_context(user_id, session_id)
        return answer, {
            "turns": turns,
            "final_unresolved_task": (
                final_context.unresolved_task.model_dump(mode="json")
                if final_context.unresolved_task
                else None
            ),
        }


def _evaluate_conversation_expectations(
    example: GoldenExample,
    execution: dict[str, Any],
) -> list[str]:
    if example.input.kind != "conversation":
        return []
    failures: list[str] = []
    turns = execution.get("turns", [])
    expected_effective = example.output.expected_effective_text_after_followup
    if expected_effective is not None:
        actual_effective = turns[-1].get("effective_text") if turns else None
        if normalize_food_query(actual_effective or "") != normalize_food_query(expected_effective):
            failures.append(
                f"effective_text: expected {expected_effective!r}, got {actual_effective!r}"
            )

    assertions = example.output.expected_memory_assertions
    for assertion, expected in assertions.items():
        if not expected:
            continue
        if assertion == "final_unresolved_task_is_null":
            passed = execution.get("final_unresolved_task") is None
        elif assertion in {
            "unsafe_turn_not_merged",
            "new_food_question_not_merged",
            "standalone_request_not_contaminated",
        }:
            passed = bool(turns) and not bool(turns[-1].get("used_followup"))
        elif assertion == "unresolved_task_can_be_null_or_pending":
            passed = True
        else:
            failures.append(f"unsupported_memory_assertion: {assertion}")
            continue
        if not passed:
            failures.append(f"memory_assertion_failed: {assertion}")
    return failures


@contextmanager
def _retrieval_mode(*, live_providers: bool) -> Iterator[None]:
    if live_providers:
        yield
        return
    original = nutrition_retriever.get_default_router
    offline_router = NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None)
    nutrition_retriever.get_default_router = lambda: offline_router
    try:
        yield
    finally:
        nutrition_retriever.get_default_router = original


def _input_summary(example: GoldenExample) -> str | list[str] | None:
    if example.input.kind == "single_turn":
        return example.input.user_input.text if example.input.user_input else None
    return [turn.text or "[image]" for turn in example.input.turns]


def _build_breakdowns(
    examples: Sequence[GoldenExample],
    results: Sequence[dict[str, Any]],
) -> dict[str, dict[str, dict[str, float | int]]]:
    dimensions: dict[str, dict[str, list[str]]] = {
        "kind": defaultdict(list),
        "language": defaultdict(list),
        "expected_behavior": defaultdict(list),
        "category": defaultdict(list),
        "tag": defaultdict(list),
    }
    for example, result in zip(examples, results, strict=True):
        status = str(result["status"])
        dimensions["kind"][example.input.kind].append(status)
        dimensions["language"][example.metadata.language or example.input.language].append(status)
        dimensions["expected_behavior"][example.output.expected_behavior].append(status)
        dimensions["category"][example.metadata.category or "unknown"].append(status)
        for tag in example.metadata.tags:
            dimensions["tag"][tag].append(status)

    return {
        dimension: {
            key: _group_summary(values)
            for key, values in sorted(groups.items())
        }
        for dimension, groups in dimensions.items()
    }


def _group_summary(values: Sequence[str]) -> dict[str, float | int]:
    passed = values.count("pass")
    failed = values.count("fail")
    unknown = values.count("unknown")
    total = len(values)
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "unknown": unknown,
        "pass_rate": passed / total if total else 0.0,
    }


def _render_markdown(run_output: dict[str, Any]) -> str:
    summary = run_output["summary"]
    lines = [
        "# NutritionAgent Golden Eval",
        "",
        f"- Run ID: `{run_output['run_id']}`",
        f"- Dataset: `{run_output['dataset_path']}`",
        f"- Filters: split=`{run_output['filters']['split']}`, tags=`{run_output['filters']['tags']}`",
        f"- Total: {summary['total']}",
        f"- Passed: {summary['passed']}",
        f"- Failed: {summary['failed']}",
        f"- Unknown: {summary['unknown']}",
        f"- Pass rate: {summary['pass_rate']:.1%}",
        "- Numeric policy: calorie overlap is required; macro overlap is advisory.",
        "- Diagnosis policy: issue classifications are deterministic triage hints, not ground truth.",
        "",
        "## Breakdowns",
        "",
    ]
    for dimension, groups in summary["breakdowns"].items():
        lines.extend(
            [
                f"### {dimension.replace('_', ' ').title()}",
                "",
                "| Value | Passed | Failed | Unknown | Total | Rate |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for value, metrics in groups.items():
            lines.append(
                f"| {value} | {metrics['passed']} | {metrics['failed']} | "
                f"{metrics['unknown']} | {metrics['total']} | {metrics['pass_rate']:.1%} |"
            )
        lines.append("")

    lines.extend(["## Issue Classifications", ""])
    classifications = summary["issue_classifications"]
    if classifications:
        for classification, count in classifications.items():
            lines.append(f"- `{classification}`: {count}")
    else:
        lines.append("No issues.")
    lines.extend(["", "## Failed And Unknown Examples", ""])

    issues = [result for result in run_output["examples"] if result["status"] != "pass"]
    if not issues:
        lines.append("No failures or unknown results.")
    for result in issues:
        parsed = result.get("evaluation", {}).get("parsed_nutrition", {})
        failed_checks = "; ".join(result["failed_checks"]) or "none"
        unknown_checks = "; ".join(result["unknown_checks"]) or "none"
        lines.extend(
            [
                f"### {result['id']}",
                "",
                f"- Input: `{result['input']}`",
                f"- Status: `{result['status']}`",
                f"- Classification: `{result['issue_classification']}`",
                f"- Expected behavior: `{result.get('evaluation', {}).get('expected_behavior')}`",
                f"- Actual behavior: `{result.get('evaluation', {}).get('actual_behavior')}`",
                f"- Failed checks: {failed_checks}",
                f"- Unknown checks: {unknown_checks}",
                f"- Parsed nutrition: `{json.dumps(parsed, ensure_ascii=False)}`",
                "",
                "```text",
                result["answer"],
                "```",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
