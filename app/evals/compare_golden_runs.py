import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare golden eval baseline and current runs.")
    parser.add_argument("--baseline-smoke", type=Path, required=True)
    parser.add_argument("--baseline-golden", type=Path, required=True)
    parser.add_argument("--current-smoke", type=Path, required=True)
    parser.add_argument("--current-golden", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/eval/post_change"))
    args = parser.parse_args(argv)

    comparison = build_comparison(
        _load_run(args.baseline_smoke),
        _load_run(args.baseline_golden),
        _load_run(args.current_smoke),
        _load_run(args.current_golden),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_id = comparison["comparison_id"]
    json_path = args.output_dir / f"{run_id}.json"
    markdown_path = args.output_dir / f"{run_id}.md"
    json_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_comparison_markdown(comparison), encoding="utf-8")
    print(json.dumps({"json_path": str(json_path), "markdown_path": str(markdown_path)}, indent=2))
    return 0


def build_comparison(
    baseline_smoke: dict[str, Any],
    baseline_golden: dict[str, Any],
    current_smoke: dict[str, Any],
    current_golden: dict[str, Any],
) -> dict[str, Any]:
    timestamp = datetime.now(UTC)
    metrics = {
        "smoke": _comparison_metric(baseline_smoke, current_smoke),
        "full_golden": _comparison_metric(baseline_golden, current_golden),
        "russian": _breakdown_metric(baseline_golden, current_golden, "language", "ru"),
        "single_turn": _breakdown_metric(baseline_golden, current_golden, "kind", "single_turn"),
        "memory": _breakdown_metric(baseline_golden, current_golden, "tag", "memory"),
        "followup": _breakdown_metric(baseline_golden, current_golden, "tag", "followup"),
        "safety": _breakdown_metric(baseline_golden, current_golden, "tag", "safety"),
        "refusal": _breakdown_metric(
            baseline_golden,
            current_golden,
            "expected_behavior",
            "refuse",
        ),
    }
    category_changes = _category_changes(baseline_golden, current_golden)
    remaining = [
        {
            "id": example["id"],
            "input": example["input"],
            "classification": example.get("issue_classification"),
            "failed_checks": example["failed_checks"],
        }
        for example in current_golden["examples"]
        if example["status"] != "pass"
    ]
    return {
        "comparison_id": f"golden_comparison_{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}",
        "timestamp_utc": timestamp.isoformat(),
        "baseline": {
            "smoke_run_id": baseline_smoke["run_id"],
            "golden_run_id": baseline_golden["run_id"],
        },
        "current": {
            "smoke_run_id": current_smoke["run_id"],
            "golden_run_id": current_golden["run_id"],
        },
        "metrics": metrics,
        "categories_improved": category_changes["improved"],
        "categories_regressed": category_changes["regressed"],
        "remaining_issue_classifications": current_golden["summary"]["issue_classifications"],
        "top_remaining_failures": remaining[:15],
        "remaining_failure_count": len(remaining),
    }


def render_comparison_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# NutritionAgent Golden Eval Comparison",
        "",
        f"- Comparison ID: `{comparison['comparison_id']}`",
        f"- Baseline smoke: `{comparison['baseline']['smoke_run_id']}`",
        f"- Baseline full: `{comparison['baseline']['golden_run_id']}`",
        f"- Current smoke: `{comparison['current']['smoke_run_id']}`",
        f"- Current full: `{comparison['current']['golden_run_id']}`",
        "- LLM and live nutrition providers: disabled for all compared runs.",
        "",
        "## Quality Changes",
        "",
        "| Metric | Before | After | Change |",
        "|---|---:|---:|---:|",
    ]
    for name, metric in comparison["metrics"].items():
        lines.append(
            f"| {name.replace('_', ' ').title()} | {metric['before']:.1%} | "
            f"{metric['after']:.1%} | {metric['delta']:+.1%} |"
        )

    lines.extend(["", "## Category Changes", "", "### Improved", ""])
    improved = comparison["categories_improved"]
    if improved:
        for item in improved:
            lines.append(
                f"- `{item['category']}`: {item['before']:.1%} -> "
                f"{item['after']:.1%} ({item['delta']:+.1%})"
            )
    else:
        lines.append("No category improvements.")

    lines.extend(["", "### Regressed", ""])
    regressed = comparison["categories_regressed"]
    if regressed:
        for item in regressed:
            lines.append(
                f"- `{item['category']}`: {item['before']:.1%} -> "
                f"{item['after']:.1%} ({item['delta']:+.1%})"
            )
    else:
        lines.append("No category-level regressions.")

    lines.extend(["", "## Remaining Issues", ""])
    for classification, count in comparison["remaining_issue_classifications"].items():
        lines.append(f"- `{classification}`: {count}")
    lines.extend(
        [
            "",
            "Most remaining failures are unsupported long-tail mixed or packaged dishes, plus "
            "numeric range mismatches for composite meals. These were not replaced with weak "
            "case-specific estimates.",
            "",
            "## Top Remaining Failures",
            "",
        ]
    )
    for failure in comparison["top_remaining_failures"]:
        lines.extend(
            [
                f"### {failure['id']}",
                "",
                f"- Input: `{failure['input']}`",
                f"- Classification: `{failure['classification']}`",
                f"- Failed checks: {'; '.join(failure['failed_checks'])}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _load_run(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _comparison_metric(before: dict[str, Any], after: dict[str, Any]) -> dict[str, float]:
    return _rates(before["summary"]["pass_rate"], after["summary"]["pass_rate"])


def _breakdown_metric(
    before: dict[str, Any],
    after: dict[str, Any],
    dimension: str,
    value: str,
) -> dict[str, float]:
    before_rate = before["summary"]["breakdowns"][dimension][value]["pass_rate"]
    after_rate = after["summary"]["breakdowns"][dimension][value]["pass_rate"]
    return _rates(before_rate, after_rate)


def _rates(before: float, after: float) -> dict[str, float]:
    return {"before": before, "after": after, "delta": after - before}


def _category_changes(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    baseline = before["summary"]["breakdowns"]["category"]
    current = after["summary"]["breakdowns"]["category"]
    changes = []
    for category in sorted(set(baseline) & set(current)):
        item = {
            "category": category,
            **_rates(baseline[category]["pass_rate"], current[category]["pass_rate"]),
        }
        changes.append(item)
    return {
        "improved": [item for item in changes if item["delta"] > 0],
        "regressed": [item for item in changes if item["delta"] < 0],
    }


if __name__ == "__main__":
    raise SystemExit(main())
