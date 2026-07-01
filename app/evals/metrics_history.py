import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_HISTORY_PATH = Path("reports/eval/metrics_history.jsonl")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append compact golden-run metrics to JSONL history.")
    parser.add_argument("runs", nargs="+", type=Path, help="Golden eval JSON run files.")
    parser.add_argument("--output", type=Path, default=DEFAULT_HISTORY_PATH)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Rewrite the output file instead of appending.",
    )
    args = parser.parse_args(argv)

    rows = [row_from_run_path(path) for path in args.runs]
    write_history_rows(rows, args.output, append=not args.replace)
    print(json.dumps({"output": str(args.output), "rows": len(rows)}, indent=2))
    return 0


def row_from_run_path(path: Path) -> dict[str, Any]:
    run = json.loads(path.read_text(encoding="utf-8"))
    row = row_from_run(run)
    row["source_path"] = str(path)
    return row


def row_from_run(run: dict[str, Any]) -> dict[str, Any]:
    summary = run["summary"]
    calorie_metrics = summary.get("numeric_metrics", {}).get("calories_kcal", {})
    return {
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "run_id": run.get("run_id"),
        "run_timestamp_utc": run.get("timestamp_utc"),
        "git_commit": run.get("git_commit"),
        "lane": _lane(run.get("config", {})),
        "dataset_path": run.get("dataset_path"),
        "filters": run.get("filters", {}),
        "total": summary.get("total"),
        "passed": summary.get("passed"),
        "failed": summary.get("failed"),
        "unknown": summary.get("unknown"),
        "pass_rate": summary.get("pass_rate"),
        "duration_seconds": summary.get("duration_seconds"),
        "calorie_metrics": {
            "mean_percentage_error": calorie_metrics.get("mean_percentage_error"),
            "p90_percentage_error": calorie_metrics.get("p90_percentage_error"),
            "max_percentage_error": calorie_metrics.get("max_percentage_error"),
            "mean_absolute_error": calorie_metrics.get("mean_absolute_error"),
            "p90_absolute_error": calorie_metrics.get("p90_absolute_error"),
            "max_absolute_error": calorie_metrics.get("max_absolute_error"),
            "mean_predicted_width": calorie_metrics.get("mean_predicted_width"),
            "median_predicted_width": calorie_metrics.get("median_predicted_width"),
            "mean_interval_score": calorie_metrics.get("mean_interval_score"),
            "within_prediction_range_rate": calorie_metrics.get(
                "within_prediction_range_rate"
            ),
        },
        "category_pass_rates": _dimension_rates(summary, "category"),
        "tag_pass_rates": _dimension_rates(summary, "tag"),
        "expected_behavior_pass_rates": _dimension_rates(summary, "expected_behavior"),
        "confidence": _confidence_rows(summary),
        "llm_usage": {
            "calls": summary.get("llm_usage", {}).get("calls"),
            "errors": summary.get("llm_usage", {}).get("errors"),
            "estimated_cost_usd": summary.get("llm_usage", {}).get("estimated_cost_usd"),
            "models": summary.get("llm_usage", {}).get("models", {}),
        },
    }


def write_history_rows(rows: Sequence[dict[str, Any]], path: Path, *, append: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _lane(config: dict[str, Any]) -> str:
    llm_mode = str(config.get("llm_mode") or ("live" if config.get("use_llm") else "off"))
    if llm_mode == "live" and config.get("live_providers"):
        return "live_providers"
    if llm_mode == "live":
        return "live_parser"
    return llm_mode


def _dimension_rates(summary: dict[str, Any], dimension: str) -> dict[str, float]:
    breakdown = summary.get("breakdowns", {}).get(dimension, {})
    return {
        str(key): float(value["pass_rate"])
        for key, value in sorted(breakdown.items())
        if isinstance(value, dict) and "pass_rate" in value
    }


def _confidence_rows(summary: dict[str, Any]) -> dict[str, dict[str, float | int | None]]:
    buckets = summary.get("confidence_calibration", {}).get("buckets", {})
    rows: dict[str, dict[str, float | int | None]] = {}
    for confidence, data in sorted(buckets.items()):
        calorie = data.get("numeric_metrics", {}).get("calories_kcal", {})
        rows[str(confidence)] = {
            "total": data.get("total"),
            "pass_rate": data.get("pass_rate"),
            "calorie_mean_percentage_error": calorie.get("mean_percentage_error"),
            "calorie_p90_percentage_error": calorie.get("p90_percentage_error"),
            "calorie_mean_interval_score": calorie.get("mean_interval_score"),
        }
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
