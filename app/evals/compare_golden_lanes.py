import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare deterministic and LLM-path golden eval lanes.")
    parser.add_argument("--fallback-run", type=Path, required=True)
    parser.add_argument("--llm-run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/eval/lane_comparison"))
    args = parser.parse_args(argv)

    comparison = build_lane_comparison(_load(args.fallback_run), _load(args.llm_run))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_id = comparison["comparison_id"]
    json_path = args.output_dir / f"{run_id}.json"
    markdown_path = args.output_dir / f"{run_id}.md"
    json_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(comparison), encoding="utf-8")
    print(json.dumps({"json_path": str(json_path), "markdown_path": str(markdown_path)}, indent=2))
    return 0


def build_lane_comparison(fallback_run: dict[str, Any], llm_run: dict[str, Any]) -> dict[str, Any]:
    timestamp = datetime.now(UTC)
    fallback_examples = {example["id"]: example for example in fallback_run["examples"]}
    llm_examples = {example["id"]: example for example in llm_run["examples"]}
    common_ids = sorted(set(fallback_examples) & set(llm_examples))
    cases = [
        _case_row(example_id, fallback_examples[example_id], llm_examples[example_id])
        for example_id in common_ids
    ]
    fallback_passed = sum(case["fallback_status"] == "pass" for case in cases)
    llm_passed = sum(case["llm_status"] == "pass" for case in cases)
    fail_to_pass = [case for case in cases if case["fallback_status"] != "pass" and case["llm_status"] == "pass"]
    pass_to_fail = [case for case in cases if case["fallback_status"] == "pass" and case["llm_status"] != "pass"]
    return {
        "comparison_id": f"golden_lane_comparison_{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}",
        "timestamp_utc": timestamp.isoformat(),
        "fallback": {
            "run_id": fallback_run["run_id"],
            "config": fallback_run.get("config", {}),
            "pass_rate": fallback_run["summary"]["pass_rate"],
        },
        "llm": {
            "run_id": llm_run["run_id"],
            "config": llm_run.get("config", {}),
            "pass_rate": llm_run["summary"]["pass_rate"],
        },
        "common_total": len(cases),
        "fallback_passed": fallback_passed,
        "llm_passed": llm_passed,
        "pass_rate_delta": (llm_passed / len(cases) if cases else 0.0)
        - (fallback_passed / len(cases) if cases else 0.0),
        "fail_to_pass": fail_to_pass,
        "pass_to_fail": pass_to_fail,
        "cases": cases,
    }


def render_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# NutritionAgent Golden Lane Comparison",
        "",
        f"- Comparison ID: `{comparison['comparison_id']}`",
        f"- Fallback run: `{comparison['fallback']['run_id']}`",
        f"- LLM-path run: `{comparison['llm']['run_id']}`",
        f"- Fallback config: `{json.dumps(comparison['fallback']['config'], ensure_ascii=False)}`",
        f"- LLM config: `{json.dumps(comparison['llm']['config'], ensure_ascii=False)}`",
        f"- Common examples: {comparison['common_total']}",
        f"- Fallback passed: {comparison['fallback_passed']}",
        f"- LLM-path passed: {comparison['llm_passed']}",
        f"- Pass-rate delta: {comparison['pass_rate_delta']:+.1%}",
        "",
        "## Status Flips",
        "",
        f"- Fail -> pass: {len(comparison['fail_to_pass'])}",
        f"- Pass -> fail: {len(comparison['pass_to_fail'])}",
        "",
    ]
    for title, key in (("Fail -> Pass", "fail_to_pass"), ("Pass -> Fail", "pass_to_fail")):
        lines.extend([f"### {title}", ""])
        rows = comparison[key]
        if not rows:
            lines.append("None.")
            lines.append("")
            continue
        lines.extend(["| ID | Input | Fallback | LLM-path |", "|---|---|---|---|"])
        for row in rows:
            lines.append(
                f"| `{row['id']}` | `{row['input']}` | `{row['fallback_status']}` | `{row['llm_status']}` |"
            )
        lines.append("")
    lines.extend(["## Per-Case Status", "", "| ID | Fallback | LLM-path |", "|---|---|---|"])
    for row in comparison["cases"]:
        lines.append(f"| `{row['id']}` | `{row['fallback_status']}` | `{row['llm_status']}` |")
    return "\n".join(lines).rstrip() + "\n"


def _case_row(example_id: str, fallback: dict[str, Any], llm: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": example_id,
        "kind": llm.get("kind"),
        "language": llm.get("language"),
        "category": llm.get("category"),
        "tags": llm.get("tags", []),
        "input": llm.get("input"),
        "fallback_status": fallback.get("status"),
        "llm_status": llm.get("status"),
        "fallback_failed_checks": fallback.get("failed_checks", []),
        "llm_failed_checks": llm.get("failed_checks", []),
        "fallback_issue_classification": fallback.get("issue_classification"),
        "llm_issue_classification": llm.get("issue_classification"),
    }


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
