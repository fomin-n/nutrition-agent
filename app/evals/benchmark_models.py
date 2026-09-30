"""Opt-in paired text-model measurements with fixed local nutrition providers."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

from app.evals.golden import DEFAULT_GOLDEN_DATASET, load_golden_examples
from app.evals.run_golden_eval import run_golden_eval, write_golden_results
from app.llm.client import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_GOLDEN_DATASET)
    parser.add_argument("--models", nargs="+", default=["gpt-4.1-mini", "gpt-6-luna"])
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--max-examples", type=int, default=3)
    parser.add_argument("--allow-paid-api", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/eval/model_comparison"))
    args = parser.parse_args(argv)
    if not args.allow_paid_api:
        parser.error("paired live measurements require --allow-paid-api")
    if (
        not 1 <= args.repeats <= 3
        or not 1 <= args.max_examples <= 111
        or not 1 <= len(args.models) <= 3
    ):
        parser.error("bounded to 3 models, 3 repeats, and 111 examples per lane")
    examples = load_golden_examples(args.dataset)[: args.max_examples]
    prompts = Path("app/prompts")
    fingerprint = hashlib.sha256(
        b"".join(p.read_bytes() for p in sorted(prompts.glob("*.md")))
    ).hexdigest()
    paths = []
    for repeat in range(args.repeats):
        # Alternate ordering to reduce first-run/cache bias.
        for model in args.models if repeat % 2 == 0 else reversed(args.models):
            with patch.dict(
                os.environ,
                {
                    "OPENAI_TEXT_MODEL": model,
                    "OPENAI_TEXT_REASONING_EFFORT": "none" if model.startswith("gpt-6") else "null",
                },
            ):
                os.environ.pop("OPENAI_REASONING_EFFORT", None)
                # Optional settings fields use absence, not a literal null env value.
                if not model.startswith("gpt-6"):
                    os.environ.pop("OPENAI_TEXT_REASONING_EFFORT", None)
                get_settings.cache_clear()
                try:
                    run = run_golden_eval(
                        examples, dataset_path=args.dataset, llm_mode="live", live_providers=False
                    )
                    run["comparison"] = {
                        "repeat": repeat + 1,
                        "text_model": model,
                        "prompt_sha256": fingerprint,
                        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
                    }
                    paths.append(str(write_golden_results(run, args.output_dir)[0]))
                finally:
                    get_settings.cache_clear()
    print(json.dumps({"runs": paths}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
