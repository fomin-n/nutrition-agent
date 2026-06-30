import argparse
import json
import logging
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from pydantic import BaseModel

from app.evals.golden import (
    DEFAULT_GOLDEN_DATASET,
    GoldenExample,
    evaluate_answer,
    load_golden_examples,
)
from app.evals.llm_stub import STUB_VERSION, build_golden_llm_stub
from app.graph import graph as graph_module
from app.graph.graph import process_request
from app.graph.nodes import (
    coordinator,
    critic,
    image_recognizer,
    nutrition_retriever,
    packaging_recognizer,
    safety_gate,
    text_parser,
)
from app.llm import structured
from app.llm.client import get_settings
from app.memory.service import MemoryService
from app.tools.fallback_nutrition import normalize_food_query
from app.tools.nutrition_tools import NutritionSourceRouter

DEFAULT_OUTPUT_DIR = Path("reports/eval")
LLM_MODES = ("off", "stub", "live")
MODEL_PRICING_USD_PER_MILLION = {
    "gpt-4.1-mini": {
        "input": 0.40,
        "cached_input": 0.10,
        "output": 1.60,
        "source": "https://developers.openai.com/api/docs/models/gpt-4.1-mini",
        "checked_date": "2026-06-24",
    }
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic NutritionAgent golden evals.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_GOLDEN_DATASET)
    parser.add_argument("--split", help="Only run examples assigned to this split.")
    parser.add_argument("--tag", action="append", default=[], help="Require a metadata tag; repeatable.")
    parser.add_argument("--max-examples", type=int)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--llm-mode",
        choices=LLM_MODES,
        default="off",
        help=(
            "Parser lane to run: off=deterministic fallback, "
            "stub=use the production LLM branch with deterministic golden fixtures, "
            "live=use real configured LLM calls."
        ),
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Deprecated alias for --llm-mode live.",
    )
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
    if args.use_llm and args.llm_mode != "off":
        parser.error("--use-llm cannot be combined with --llm-mode")
    llm_mode = "live" if args.use_llm else args.llm_mode
    if llm_mode == "live" and not args.allow_paid_api:
        parser.error("--llm-mode live requires --allow-paid-api")
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
        llm_mode=llm_mode,
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
    use_llm: bool | None = None,
    llm_mode: str | None = None,
    live_providers: bool = False,
) -> dict[str, Any]:
    resolved_llm_mode = _resolve_llm_mode(use_llm=use_llm, llm_mode=llm_mode)
    timestamp = datetime.now(UTC)
    started = time.perf_counter()
    with _retrieval_mode(live_providers=live_providers), _llm_parser_mode(
        llm_mode=resolved_llm_mode,
        examples=examples,
    ):
        results = [
            _run_example(example, use_llm=resolved_llm_mode != "off")
            for example in examples
        ]
    passed = sum(1 for result in results if result["status"] == "pass")
    failed = sum(1 for result in results if result["status"] == "fail")
    unknown = sum(1 for result in results if result["status"] == "unknown")
    total = len(results)
    llm_usage = _aggregate_llm_usage(results)
    summary = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "unknown": unknown,
        "pass_rate": passed / total if total else 0.0,
        "breakdowns": _build_breakdowns(examples, results),
        "issue_classifications": _count_issue_classifications(results),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "llm_usage": llm_usage,
        "numeric_metrics": _aggregate_numeric_metrics(results),
        "confidence_calibration": _confidence_calibration(results),
    }
    run_scope = split or "all"
    settings = get_settings()
    return {
        "run_id": f"golden_baseline_{run_scope}_{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}",
        "timestamp_utc": timestamp.isoformat(),
        "git_commit": _git_commit(),
        "python_version": sys.version.split()[0],
        "dataset_path": str(Path(dataset_path)),
        "filters": {"split": split, "tags": list(tags)},
        "config": {
            "use_llm": resolved_llm_mode != "off",
            "llm_mode": resolved_llm_mode,
            "llm_stub_version": STUB_VERSION if resolved_llm_mode == "stub" else None,
            "live_providers": live_providers,
            "macro_ranges_are_advisory": True,
            "openai_text_model": settings.openai_text_model,
            "openai_vision_model": settings.openai_vision_model,
            "openai_critic_model": settings.openai_critic_model,
            "temperature": 0.0,
            "critic_max_iterations": settings.critic_max_iterations,
            "openai_moderation_enabled": settings.openai_moderation_enabled,
            "provider_flags": {
                "usda": settings.enable_usda,
                "fatsecret": settings.enable_fatsecret,
                "open_food_facts": settings.enable_open_food_facts,
            },
            "nutrition_cache_dir": settings.nutrition_cache_dir if live_providers else None,
            "pricing": MODEL_PRICING_USD_PER_MILLION,
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
    started = time.perf_counter()
    try:
        with (
            _capture_graph_states() as graph_states,
            _capture_llm_usage(enabled=use_llm) as usage,
            _capture_provider_events() as provider_events,
        ):
            if example.input.kind == "single_turn":
                answer, execution = _run_single_turn(example, use_llm=use_llm)
            else:
                answer, execution = _run_conversation(example, use_llm=use_llm)
        execution["duration_seconds"] = round(time.perf_counter() - started, 3)
        execution["llm_usage"] = usage.summary()
        execution["graph_invocations"] = [_graph_state_snapshot(state) for state in graph_states]
        execution["provider_events"] = provider_events
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
            "duration_seconds": round(time.perf_counter() - started, 3),
        }


class LLMUsageCollector(BaseCallbackHandler):
    def __init__(self) -> None:
        self._lock = Lock()
        self.calls: list[dict[str, Any]] = []
        self.errors = 0

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        del kwargs
        call = _usage_from_llm_result(response)
        with self._lock:
            self.calls.append(call)

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        del error, kwargs
        with self._lock:
            self.errors += 1

    def summary(self) -> dict[str, Any]:
        totals = {
            "calls": len(self.calls),
            "errors": self.errors,
            "input_tokens": sum(int(call["input_tokens"]) for call in self.calls),
            "cached_input_tokens": sum(
                int(call["cached_input_tokens"]) for call in self.calls
            ),
            "output_tokens": sum(int(call["output_tokens"]) for call in self.calls),
            "total_tokens": sum(int(call["total_tokens"]) for call in self.calls),
        }
        models: dict[str, dict[str, int | float | None]] = {}
        for call in self.calls:
            model = str(call["model"] or "unknown")
            model_totals = models.setdefault(
                model,
                {
                    "calls": 0,
                    "input_tokens": 0,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost_usd": None,
                },
            )
            for key in (
                "calls",
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "total_tokens",
            ):
                model_totals[key] = int(model_totals[key] or 0) + (
                    1 if key == "calls" else int(call[key])
                )
        estimated_cost = 0.0
        cost_complete = True
        for model, model_totals in models.items():
            cost = _estimate_model_cost(model, model_totals)
            model_totals["estimated_cost_usd"] = cost
            if cost is None:
                cost_complete = False
            else:
                estimated_cost += cost
        totals["models"] = models
        totals["estimated_cost_usd"] = round(estimated_cost, 6) if cost_complete else None
        totals["calls_detail"] = self.calls
        return totals


class _CapturingGraph:
    def __init__(self, graph: Any, states: list[dict[str, Any]]) -> None:
        self.graph = graph
        self.states = states

    def invoke(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        state = self.graph.invoke(*args, **kwargs)
        self.states.append(state)
        return state


class _ProviderEventHandler(logging.Handler):
    def __init__(self, events: list[dict[str, str]]) -> None:
        super().__init__(level=logging.WARNING)
        self.events = events

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if record.name.startswith("app.tools."):
            self.events.append({"logger": record.name, "level": record.levelname, "message": message})


@contextmanager
def _capture_graph_states() -> Iterator[list[dict[str, Any]]]:
    states: list[dict[str, Any]] = []
    original = graph_module.get_compiled_graph
    graph = original()
    graph_module.get_compiled_graph = lambda: _CapturingGraph(graph, states)
    try:
        yield states
    finally:
        graph_module.get_compiled_graph = original


@contextmanager
def _capture_llm_usage(*, enabled: bool) -> Iterator[LLMUsageCollector]:
    collector = LLMUsageCollector()
    if not enabled:
        yield collector
        return

    original_structured = structured.build_chat_model
    original_image = image_recognizer.build_chat_model

    def build_with_collector(model_name: str, *, temperature: float = 0.0):
        model = original_structured(model_name, temperature=temperature)
        callbacks = [*(model.callbacks or []), collector]
        return model.model_copy(update={"callbacks": callbacks})

    structured.build_chat_model = build_with_collector
    image_recognizer.build_chat_model = build_with_collector
    try:
        yield collector
    finally:
        structured.build_chat_model = original_structured
        image_recognizer.build_chat_model = original_image


@contextmanager
def _capture_provider_events() -> Iterator[list[dict[str, str]]]:
    events: list[dict[str, str]] = []
    handler = _ProviderEventHandler(events)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield events
    finally:
        root.removeHandler(handler)


def _usage_from_llm_result(response: LLMResult) -> dict[str, Any]:
    message = None
    if response.generations and response.generations[0]:
        message = getattr(response.generations[0][0], "message", None)
    usage = dict(getattr(message, "usage_metadata", None) or {})
    response_metadata = dict(getattr(message, "response_metadata", None) or {})
    token_usage = dict((response.llm_output or {}).get("token_usage") or {})
    input_tokens = int(
        usage.get("input_tokens")
        or token_usage.get("prompt_tokens")
        or 0
    )
    output_tokens = int(
        usage.get("output_tokens")
        or token_usage.get("completion_tokens")
        or 0
    )
    total_tokens = int(
        usage.get("total_tokens")
        or token_usage.get("total_tokens")
        or input_tokens + output_tokens
    )
    input_details = dict(usage.get("input_token_details") or {})
    prompt_details = dict(token_usage.get("prompt_tokens_details") or {})
    cached_input_tokens = int(
        input_details.get("cache_read")
        or prompt_details.get("cached_tokens")
        or 0
    )
    model = (
        response_metadata.get("model_name")
        or (response.llm_output or {}).get("model_name")
        or "unknown"
    )
    return {
        "model": str(model),
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _estimate_model_cost(
    model: str,
    usage: dict[str, int | float | None],
) -> float | None:
    pricing = next(
        (
            rates
            for prefix, rates in MODEL_PRICING_USD_PER_MILLION.items()
            if model == prefix or model.startswith(f"{prefix}-")
        ),
        None,
    )
    if pricing is None:
        return None
    input_tokens = int(usage["input_tokens"] or 0)
    cached_tokens = min(input_tokens, int(usage["cached_input_tokens"] or 0))
    uncached_tokens = input_tokens - cached_tokens
    output_tokens = int(usage["output_tokens"] or 0)
    cost = (
        uncached_tokens * float(pricing["input"])
        + cached_tokens * float(pricing["cached_input"])
        + output_tokens * float(pricing["output"])
    ) / 1_000_000
    return round(cost, 6)


def _aggregate_llm_usage(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    collector = LLMUsageCollector()
    for result in results:
        usage = result.get("execution", {}).get("llm_usage", {})
        collector.errors += int(usage.get("errors", 0))
        collector.calls.extend(usage.get("calls_detail", []))
    return collector.summary()


def _graph_state_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "scope_decision",
        "meal",
        "ingredient_nutrition",
        "totals",
        "final_estimate",
        "critic_result",
        "critic_history",
        "critic_feedback",
        "critic_iteration",
        "retrieval_failures",
        "retrieval_diagnostics",
        "errors",
    )
    return {key: _jsonable(state[key]) for key in keys if key in state}


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


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


def _resolve_llm_mode(*, use_llm: bool | None, llm_mode: str | None) -> str:
    if llm_mode is not None:
        if llm_mode not in LLM_MODES:
            raise ValueError(f"Unsupported llm_mode={llm_mode!r}")
        return llm_mode
    return "live" if use_llm else "off"


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


@contextmanager
def _llm_parser_mode(
    *,
    llm_mode: str,
    examples: Sequence[GoldenExample],
) -> Iterator[None]:
    if llm_mode != "stub":
        yield
        return
    class LocalModerationService:
        def moderate_text(self, text: str | None, *, request_id: str | None = None):
            return safety_gate.local_moderate_text(text)

    original_has_openai_key = text_parser.has_openai_key
    original_parse_text_with_llm = text_parser.parse_text_with_llm
    original_coordinator_has_openai_key = coordinator.has_openai_key
    original_critic_has_openai_key = critic.has_openai_key
    original_image_has_openai_key = image_recognizer.has_openai_key
    original_packaging_has_openai_key = packaging_recognizer.has_openai_key
    original_moderation_service = safety_gate.ModerationService
    text_parser.has_openai_key = lambda: True
    text_parser.parse_text_with_llm = build_golden_llm_stub(examples)
    coordinator.has_openai_key = lambda: False
    critic.has_openai_key = lambda: False
    image_recognizer.has_openai_key = lambda: False
    packaging_recognizer.has_openai_key = lambda: False
    safety_gate.ModerationService = LocalModerationService
    try:
        yield
    finally:
        text_parser.has_openai_key = original_has_openai_key
        text_parser.parse_text_with_llm = original_parse_text_with_llm
        coordinator.has_openai_key = original_coordinator_has_openai_key
        critic.has_openai_key = original_critic_has_openai_key
        image_recognizer.has_openai_key = original_image_has_openai_key
        packaging_recognizer.has_openai_key = original_packaging_has_openai_key
        safety_gate.ModerationService = original_moderation_service


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
        "confidence": defaultdict(list),
        "query_kind": defaultdict(list),
    }
    grouped_results: dict[str, dict[str, list[dict[str, Any]]]] = {
        dimension: defaultdict(list)
        for dimension in dimensions
    }
    for example, result in zip(examples, results, strict=True):
        status = str(result["status"])
        dimensions["kind"][example.input.kind].append(status)
        dimensions["language"][example.metadata.language or example.input.language].append(status)
        dimensions["expected_behavior"][example.output.expected_behavior].append(status)
        dimensions["category"][example.metadata.category or "unknown"].append(status)
        confidence = _result_confidence(result)
        dimensions["confidence"][confidence].append(status)
        query_kinds = _result_query_kinds(result)
        for query_kind in query_kinds:
            dimensions["query_kind"][query_kind].append(status)
        grouped_results["kind"][example.input.kind].append(result)
        grouped_results["language"][example.metadata.language or example.input.language].append(result)
        grouped_results["expected_behavior"][example.output.expected_behavior].append(result)
        grouped_results["category"][example.metadata.category or "unknown"].append(result)
        grouped_results["confidence"][confidence].append(result)
        for query_kind in query_kinds:
            grouped_results["query_kind"][query_kind].append(result)
        for tag in example.metadata.tags:
            dimensions["tag"][tag].append(status)
            grouped_results["tag"][tag].append(result)

    return {
        dimension: {
            key: {
                **_group_summary(values),
                "numeric_metrics": _aggregate_numeric_metrics(grouped_results[dimension][key]),
            }
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


def _aggregate_numeric_metrics(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        nutrient: _nutrient_metric_summary(
            [
                result.get("evaluation", {}).get("numeric_metrics", {}).get(nutrient, {})
                for result in results
            ]
        )
        for nutrient in ("calories_kcal", "protein_g", "fat_g", "carbs_g")
    }


def _nutrient_metric_summary(metrics: Sequence[dict[str, Any]]) -> dict[str, Any]:
    absolute_errors = _numeric_values(metrics, "absolute_error")
    percentage_errors = _numeric_values(metrics, "percentage_error")
    widths = _numeric_values(metrics, "predicted_width")
    normalized_widths = _numeric_values(metrics, "normalized_width")
    interval_scores = _numeric_values(metrics, "interval_score")
    within_values = [
        value
        for metric in metrics
        if isinstance(value := metric.get("within_prediction_range"), bool)
    ]
    return {
        "count": len(absolute_errors),
        "mean_absolute_error": _mean(absolute_errors),
        "median_absolute_error": _percentile(absolute_errors, 0.5),
        "p90_absolute_error": _percentile(absolute_errors, 0.9),
        "p95_absolute_error": _percentile(absolute_errors, 0.95),
        "max_absolute_error": max(absolute_errors) if absolute_errors else None,
        "mean_percentage_error": _mean(percentage_errors),
        "median_percentage_error": _percentile(percentage_errors, 0.5),
        "p90_percentage_error": _percentile(percentage_errors, 0.9),
        "p95_percentage_error": _percentile(percentage_errors, 0.95),
        "max_percentage_error": max(percentage_errors) if percentage_errors else None,
        "mean_predicted_width": _mean(widths),
        "median_predicted_width": _percentile(widths, 0.5),
        "mean_normalized_width": _mean(normalized_widths),
        "median_normalized_width": _percentile(normalized_widths, 0.5),
        "mean_interval_score": _mean(interval_scores),
        "median_interval_score": _percentile(interval_scores, 0.5),
        "within_prediction_range_rate": (
            sum(1 for value in within_values if value) / len(within_values)
            if within_values
            else None
        ),
    }


def _confidence_calibration(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        groups[_result_confidence(result)].append(result)
    summary = {
        confidence: {
            **_group_summary([str(result["status"]) for result in grouped]),
            "numeric_metrics": _aggregate_numeric_metrics(grouped),
        }
        for confidence, grouped in sorted(groups.items())
    }
    ordered_errors = [
        summary[level]["numeric_metrics"]["calories_kcal"]["mean_percentage_error"]
        for level in ("low", "medium", "high")
        if level in summary
    ]
    monotonic_error_decreases = (
        all(
            left is None or right is None or left >= right
            for left, right in zip(ordered_errors, ordered_errors[1:], strict=False)
        )
        if len(ordered_errors) >= 2
        else None
    )
    return {
        "buckets": summary,
        "calorie_mape_decreases_with_confidence": monotonic_error_decreases,
    }


def _result_confidence(result: dict[str, Any]) -> str:
    invocations = result.get("execution", {}).get("graph_invocations", [])
    for invocation in reversed(invocations):
        final = invocation.get("final_estimate")
        if isinstance(final, dict) and final.get("confidence"):
            return str(final["confidence"])
    return "unknown"


def _result_query_kinds(result: dict[str, Any]) -> tuple[str, ...]:
    query_kinds: list[str] = []
    for invocation in result.get("execution", {}).get("graph_invocations", []):
        for diagnostic in invocation.get("retrieval_diagnostics", []):
            query_kind = str(diagnostic.get("query_kind") or "unknown")
            if query_kind not in query_kinds:
                query_kinds.append(query_kind)
    return tuple(query_kinds or ["none"])


def _numeric_values(metrics: Sequence[dict[str, Any]], key: str) -> list[float]:
    return [
        float(value)
        for metric in metrics
        if isinstance(value := metric.get(key), int | float)
    ]


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


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
        "- Magnitude policy: scalar nutrition references are summarized by midpoint error, range sharpness, and interval score.",
        "- Diagnosis policy: issue classifications are deterministic triage hints, not ground truth.",
        "",
        "## Numeric Metrics",
        "",
        "| Nutrient | Count | Mean Abs Error | Median Abs Error | P90 Abs Error | Mean % Error | P90 % Error | Mean Width | Mean Norm Width | Within Prediction |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for nutrient, metrics in summary["numeric_metrics"].items():
        lines.append(
            f"| {nutrient} | {metrics['count']} | "
            f"{_fmt_number(metrics['mean_absolute_error'])} | "
            f"{_fmt_number(metrics['median_absolute_error'])} | "
            f"{_fmt_number(metrics['p90_absolute_error'])} | "
            f"{_fmt_number(metrics['mean_percentage_error'])} | "
            f"{_fmt_number(metrics['p90_percentage_error'])} | "
            f"{_fmt_number(metrics['mean_predicted_width'])} | "
            f"{_fmt_number(metrics['mean_normalized_width'])} | "
            f"{_fmt_percent(metrics['within_prediction_range_rate'])} |"
        )

    lines.extend(
        [
            "",
            "## Confidence Calibration",
            "",
            f"- Calorie MAPE decreases with confidence: `{summary['confidence_calibration']['calorie_mape_decreases_with_confidence']}`",
            "",
            "| Confidence | Passed | Failed | Unknown | Total | Rate | Calorie Mean % Error | Calorie P90 % Error | Calorie Mean Width |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for confidence, metrics in summary["confidence_calibration"]["buckets"].items():
        calorie = metrics["numeric_metrics"]["calories_kcal"]
        lines.append(
            f"| {confidence} | {metrics['passed']} | {metrics['failed']} | "
            f"{metrics['unknown']} | {metrics['total']} | {metrics['pass_rate']:.1%} | "
            f"{_fmt_number(calorie['mean_percentage_error'])} | "
            f"{_fmt_number(calorie['p90_percentage_error'])} | "
            f"{_fmt_number(calorie['mean_predicted_width'])} |"
        )

    lines.extend(
        [
            "",
            "## Breakdowns",
            "",
        ]
    )
    for dimension, groups in summary["breakdowns"].items():
        lines.extend(
            [
                f"### {dimension.replace('_', ' ').title()}",
                "",
                "| Value | Passed | Failed | Unknown | Total | Rate | Calorie Mean % Error | Calorie P90 % Error | Calorie Mean Width |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for value, metrics in groups.items():
            calorie = metrics["numeric_metrics"]["calories_kcal"]
            lines.append(
                f"| {value} | {metrics['passed']} | {metrics['failed']} | "
                f"{metrics['unknown']} | {metrics['total']} | {metrics['pass_rate']:.1%} | "
                f"{_fmt_number(calorie['mean_percentage_error'])} | "
                f"{_fmt_number(calorie['p90_percentage_error'])} | "
                f"{_fmt_number(calorie['mean_predicted_width'])} |"
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


def _fmt_number(value: Any) -> str:
    return f"{value:.2f}" if isinstance(value, int | float) else "n/a"


def _fmt_percent(value: Any) -> str:
    return f"{value:.1%}" if isinstance(value, int | float) else "n/a"


if __name__ == "__main__":
    raise SystemExit(main())
