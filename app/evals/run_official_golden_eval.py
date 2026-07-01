import argparse
import gzip
import hashlib
import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evals.golden import DEFAULT_GOLDEN_DATASET, load_golden_examples
from app.evals.metrics_history import row_from_run, write_history_rows
from app.evals.run_golden_eval import LLM_MODES, run_golden_eval, write_golden_results

DEFAULT_OUTPUT_ROOT = Path("reports/eval/official")
DEFAULT_HISTORY_PATH = Path("reports/eval/metrics_history.jsonl")


@dataclass(frozen=True)
class OfficialArtifacts:
    directory: Path
    markdown_path: Path
    raw_json_gz_path: Path
    provenance_path: Path
    commit_sha_path: Path
    manifest_path: Path
    metrics_history_path: Path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an official golden eval and persist artifacts.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_GOLDEN_DATASET)
    parser.add_argument("--split")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--max-examples", type=int)
    parser.add_argument("--label", required=True, help="Short label used in the official report directory.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--metrics-history", type=Path, default=DEFAULT_HISTORY_PATH)
    parser.add_argument("--llm-mode", choices=LLM_MODES, default="off")
    parser.add_argument("--allow-paid-api", action="store_true")
    parser.add_argument("--live-providers", action="store_true")
    parser.add_argument("--commit", action="store_true", help="Commit the official artifacts after writing.")
    parser.add_argument("--push", action="store_true", help="Push the current branch after committing artifacts.")
    args = parser.parse_args(argv)

    if args.llm_mode == "live" and not args.allow_paid_api:
        parser.error("--llm-mode live requires --allow-paid-api")
    if args.max_examples is not None and args.max_examples < 1:
        parser.error("--max-examples must be at least 1")

    examples = load_golden_examples(args.dataset, split=args.split, tags=args.tag)
    if args.max_examples is not None:
        examples = examples[: args.max_examples]
    if not examples:
        parser.error("No examples matched the requested filters")

    run_output = run_golden_eval(
        examples,
        dataset_path=args.dataset,
        split=args.split,
        tags=args.tag,
        llm_mode=args.llm_mode,
        live_providers=args.live_providers,
    )
    artifacts = write_official_artifacts(
        run_output,
        label=args.label,
        output_root=args.output_root,
        metrics_history_path=args.metrics_history,
        cli_args=vars(args),
    )
    if args.commit:
        _commit_artifacts(artifacts, label=args.label)
    if args.push:
        _push_current_branch()
    print(
        json.dumps(
            {
                "summary": run_output["summary"],
                "directory": str(artifacts.directory),
                "markdown_path": str(artifacts.markdown_path),
                "raw_json_gz_path": str(artifacts.raw_json_gz_path),
                "provenance_path": str(artifacts.provenance_path),
                "manifest_path": str(artifacts.manifest_path),
                "metrics_history_path": str(artifacts.metrics_history_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def write_official_artifacts(
    run_output: dict[str, Any],
    *,
    label: str,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    metrics_history_path: Path = DEFAULT_HISTORY_PATH,
    cli_args: dict[str, Any] | None = None,
) -> OfficialArtifacts:
    safe_label = _safe_label(label)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = output_root / f"{timestamp}_{safe_label}"
    output_dir.mkdir(parents=True, exist_ok=False)

    raw_json_path, markdown_path = write_golden_results(run_output, output_dir)
    raw_json_gz_path = raw_json_path.with_suffix(raw_json_path.suffix + ".gz")
    with raw_json_path.open("rb") as source, gzip.open(raw_json_gz_path, "wb", compresslevel=9) as target:
        target.write(source.read())
    raw_json_path.unlink()

    commit = run_output.get("git_commit") or _git_output(["rev-parse", "HEAD"]) or "unknown"
    commit_sha_path = output_dir / "COMMIT_SHA"
    commit_sha_path.write_text(f"{commit}\n", encoding="utf-8")

    provenance_path = output_dir / "provenance.json"
    provenance_path.write_text(
        json.dumps(
            _provenance(run_output, cli_args=cli_args),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    row = row_from_run(run_output)
    row["source_path"] = str(raw_json_gz_path)
    write_history_rows([row], metrics_history_path, append=True)

    manifest_path = output_dir / "MANIFEST.sha256"
    _write_manifest(output_dir, manifest_path)
    return OfficialArtifacts(
        directory=output_dir,
        markdown_path=markdown_path,
        raw_json_gz_path=raw_json_gz_path,
        provenance_path=provenance_path,
        commit_sha_path=commit_sha_path,
        manifest_path=manifest_path,
        metrics_history_path=metrics_history_path,
    )


def _provenance(run_output: dict[str, Any], *, cli_args: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "run_id": run_output.get("run_id"),
        "timestamp_utc": run_output.get("timestamp_utc"),
        "git_commit": run_output.get("git_commit"),
        "git_status_short": _git_output(["status", "--short"]) or "",
        "dataset_path": run_output.get("dataset_path"),
        "filters": run_output.get("filters"),
        "config": run_output.get("config"),
        "summary": {
            key: run_output.get("summary", {}).get(key)
            for key in ("total", "passed", "failed", "unknown", "pass_rate", "duration_seconds")
        },
        "cli_args": _jsonable_args(cli_args or {}),
    }


def _jsonable_args(args: dict[str, Any]) -> dict[str, Any]:
    return {key: str(value) if isinstance(value, Path) else value for key, value in args.items()}


def _safe_label(label: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", label.strip()).strip("._-")
    return safe or "golden"


def _write_manifest(directory: Path, manifest_path: Path) -> None:
    rows: list[str] = []
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        if path == manifest_path:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{digest}  {path.relative_to(directory).as_posix()}")
    manifest_path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _commit_artifacts(artifacts: OfficialArtifacts, *, label: str) -> None:
    paths = [
        artifacts.directory,
        artifacts.metrics_history_path,
    ]
    subprocess.run(["git", "add", *(str(path) for path in paths)], check=True)
    subprocess.run(
        ["git", "commit", "-m", f"Record official golden eval {label}"],
        check=True,
    )


def _push_current_branch() -> None:
    branch = _git_output(["branch", "--show-current"])
    if not branch:
        raise RuntimeError("Cannot push: current branch could not be determined")
    subprocess.run(["git", "push", "origin", branch], check=True)


def _git_output(args: list[str]) -> str | None:
    try:
        return subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
