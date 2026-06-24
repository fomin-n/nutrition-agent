# Live Golden Eval Artifacts - 2026-06-24

Official runs and comparisons for
[`docs/live-golden-eval-2026-06-24.md`](../../../docs/live-golden-eval-2026-06-24.md).

- `COMMIT_SHA`: immutable code revision used by every run.
- `off/`: Run A, deterministic fallback and providers off.
- `stub/`: Run B, circular fixture stub and providers off.
- `live_parser_1/`: Run C1, real LLM and providers off.
- `live_parser_2/`: Run C2, real LLM repeat and providers off.
- `live_providers/`: Run D, real LLM and providers on.
- `comparisons/`: A-C1, A-C2, B-C1, B-C2, and A-D status comparisons.
- `MANIFEST.sha256`: SHA-256 checksums for committed artifacts.

The local `logs/` directory and the cold provider cache are intentionally not
committed. They contain duplicate console output or transient provider cache
material and are not required to reproduce the reported metrics.
