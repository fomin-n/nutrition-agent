# Text Model Default Release Check

Date: 2026-09-30 (UTC). The release changes text extraction and scope tiebreaks
from `gpt-4.1-mini` to `gpt-6-luna`; the wrapper explicitly selects reasoning
`none`. Vision, escalation, qualitative critic and moderation models are unchanged.
Only synthetic/public golden inputs were used, with fixed local nutrition priors.

## Evidence

The live Luna structured-schema canary returned one valid ingredient for
`100 g cooked chicken breast`. A 13-case subset then ran twice per model in
alternating order. It covers EN/RU basics, branded products, explicit mass,
mixed dishes, clarification, off-topic refusals and chicken follow-up memory.

| Model | Repeat | Pass | Unknown | Chat API errors | Time (s) | Estimated chat cost (USD) |
| --- | --- | --- | --- | --- | --- | --- |
| GPT-4.1 mini | 1 | 12/13 | 0 | 0 | 65.456 | 0.010125 |
| GPT-6 Luna | 1 | 12/13 | 0 | 0 | 64.310 | 0.004486 |
| GPT-6 Luna | 2 | 12/13 | 0 | 0 | 61.825 | 0.004486 |
| GPT-4.1 mini | 2 | 12/13 | 0 | 0 | 53.429 | 0.010108 |

All four lanes made 31 chat calls. Each failed only `na_golden_076`: fish and
chips asks clarification instead of estimating unsupported whole-meal coverage.
There were no case flips, including the two refusal examples per lane. Luna's
mean elapsed time was 63.068 s versus 59.442 s, about 6% slower, not a latency
improvement. Measured estimated chat cost fell about 56%; the four lanes together
cost an estimated $0.029205, excluding the preliminary schema canary. These are
token-based estimates, not invoices, and do not include hosting or provider costs.

This small, selected set does not establish full-dataset non-regression, broad
safety or photo quality. Keep those evaluations as follow-ups. The default change
was explicitly requested; no improvement to nutrition accuracy is claimed.

## Reproduction

`selection.jsonl` is an unchanged subset of the committed combined golden dataset.
No reference values were tuned. All four lanes record measured implementation
commit `011bda4` and use the same prompt and dataset
hashes, recorded in the raw results' `comparison` field. The later promotion commit
changes the model default, associated tests and documentation only.

```bash
ENABLE_PHOENIX_TRACING=false OPENAI_CRITIC_MODEL=gpt-4.1-mini \
OPENAI_VISION_MODEL=gpt-4.1-mini OPENAI_MAX_RETRIES=0 \
uv run --frozen python -m app.evals.benchmark_models \
  --dataset reports/eval/milestones/model_default_20260930/selection.jsonl \
  --max-examples 13 --repeats 2 --allow-paid-api \
  --output-dir reports/eval/model_default_reproduction
```

Requires a configured OpenAI key and makes paid calls. The JSON gzip files contain
per-case answers, graph snapshots, timing, token usage and config. No credentials,
raw provider payloads or Telegram user data are included. `MANIFEST.sha256`
checks the dataset and raw results. This subset is deliberately not appended to
the full-golden metrics history, to avoid mixing different denominators.

The default's reasoning/temperature compatibility follows the official
[Luna model reference](https://developers.openai.com/api/docs/models/gpt-6-luna)
and [migration guidance](https://developers.openai.com/api/docs/guides/latest-model).
For rollback, set `OPENAI_TEXT_MODEL=gpt-4.1-mini`, remove any
`OPENAI_TEXT_REASONING_EFFORT` override, and restart. Do not set a global reasoning
override while using GPT-4.1 for vision or critic work.
