# Integrity And Privacy Implementation

Date: 2026-09-29. Base: `90fe38e8e554dd88a9a5402a268e700bc4784b18` on
`main`. Measurements below use the local implementation diff, not the unchanged
base commit. No production inspection/deployment or paid model calls occurred.

## Scope And Decisions

The controlled LangGraph design, SQLite storage, provider set and shipped model
names are unchanged. This pass implements the review's correctness/privacy work
and bounded execution/measurement groundwork. It does not claim completion of
paid model comparisons, real-photo benchmarking or optional self-hosting work.

### Meal Integrity

- A shared semantic validator runs before retrieval for local, text-model,
  product and vision meals. Invalid text-model output gets one bounded repair;
  failure cannot return the rejected original. Clarification meals cannot carry
  ingredients into calculation.
- Meals have at most 12 ingredients, finite weights, bounded individual masses
  and explicit-total conservation checks (70-130% of stated mass). These are
  safety bounds, not proof that an inferred recipe is correct.
- Repeated food occurrences keep independently owned quantities. Explicit mass
  overrides household conversion. Decimal kg/oz quantities survive normalization.
  Adjacent aliases for one food still coalesce.
- Preparation survives retrieval normalization. Unsupported raw/dry requests
  clarify rather than silently reuse cooked nutrition. Pan-frying can use a
  disclosed low-confidence oil assumption; see the retrieval documentation.
- Detectable parser mass omissions and any unresolved retrieved component
  now cause clarification instead of a misleading complete-meal total. Inferable
  role-prior backfills remain available, but must pass candidate validation.
- Source uncertainty uses separate factors, not rewritten physical grams.
  Diagnostics retain per-occurrence candidate identity, mass, factors and
  calculated contribution. The calculator remains the sole owner of totals.

### Memory And Privacy

The SQLite migration adds `memory_generations(user_id, generation)`. Context
loads carry a generation; writes compare it in the same immediate transaction as
message/fact writes. `/forget` deletes memory and increments the generation, so
requests started before deletion cannot recreate that memory. Generation
tombstones remain; usage accounting is unchanged.

Telegram records a turn only after all reply chunks are delivered. A failed
delivery records no turn, even if earlier chunks reached the user. Local/eval
callers retain immediate recording. Memory storage failures are logged by class
and do not discard a completed answer.

Stable facts require explicit personal assertions or direct measurement
instructions. Negative assertions retract matching facts; third-person claims
are excluded conservatively. Ambiguous prose may yield no fact. Assistant
messages and compacted summaries are never parser evidence; recent user messages
are supplied only for an unresolved task. Existing incorrectly stored facts are
not automatically reinterpreted; `/forget` clears them.

OpenInference content hiding is explicit. A final exporter allowlist removes
inputs, outputs, images, arbitrary metadata, exception events and status
descriptions, while keeping approved IDs, model/token/timing metadata. Tests
inspect actual exported instrumented spans. Exception logs retain classes rather
than validation input/traceback contents. This does not erase historical traces,
backups or records held by Telegram/OpenAI; approved identity metadata remains
personally identifying. See [observability](observability.md).

### Critic, Packaging And Resource Limits

Qualitative criticism may request only a typed presentation repair that would
change the answer. Unactionable/repeated qualitative revisions stop without
replacing a hard-validated answer. Hard checks and the bounded hard-check
clarification path remain authoritative; repeated identical hard-check issues
stop early with clarification. `QUALITATIVE_CRITIC_ENABLED=false` is
available for a future paired value/latency experiment; its default remains true.

Packaging now has a dedicated `PackagingObservation`/`ObservedNutritionLabel`
schema and prompt. It transcribes visible label numbers, not invented nutrition.
The basis must be per 100 g or per serving with a readable mass; consumed mass
must be supplied. Conversion is deterministic. Text-only parsing cannot introduce
label nutrition. Unreadable/non-food observations clarify. This is contract and
mock-test coverage, not demonstrated real-image accuracy.

- Input text is bounded to 8,192 characters; image reads to `MAX_IMAGE_BYTES`
  (10 MB by default), also checked before Telegram download when size is known.
- Chat output caps are task-specific (text/vision 2,048; scope/critic 512).
- Plain-text Telegram replies split losslessly below 4,000 UTF-16 units; no
  assumptions are silently truncated.
- `REQUEST_DEADLINE_SECONDS=90` bounds new network work cooperatively. SDK retries
  are disabled inside this budget; explicit provider retries check it. Existing
  blocking calls, SQLite work and per-phase network timeouts mean this is **not**
  a hard wall-clock deadline or cancellation of running worker threads.
- Provider HTTP clients share a pool; USDA search candidates are ranked and
  deduplicated before at most three detail fetches per ingredient. No early exit
  bypasses ranking/validation. Mock cold/warm-cache and detail-limit tests run
  offline; live latency/quality confirmation remains pending.

Unused Pillow was removed. Targeted lock updates patch AnyIO and pip; the local
dependency audit reports no known vulnerabilities. This is a point-in-time audit,
not an assurance against undisclosed vulnerabilities.

## Reproducible Offline Measurements

Prevent accidental use of local credentials/config when reproducing:

```bash
export OPENAI_API_KEY='' TELEGRAM_BOT_TOKEN='' USDA_API_KEY=''
export FATSECRET_CLIENT_ID='' FATSECRET_CLIENT_SECRET=''
export ENABLE_PHOENIX_TRACING=false ENABLE_USDA=false
export ENABLE_FATSECRET=false ENABLE_OPEN_FOOD_FACTS=false
export RUN_LIVE_NUTRITION_TESTS=0
uv sync --frozen --extra dev
uv run --frozen ruff check .
uv run --frozen mypy app
uv run --frozen pytest --cov=app --cov-report=term-missing --cov-fail-under=75
uv run --frozen python -m app.evals.run_eval --mock
uv run --frozen python -m app.evals.run_retrieval_smoke
uv run --frozen python -m app.evals.run_golden_gate
uv run --frozen python -m app.evals.run_golden_eval --split smoke
uv run --frozen pip-audit --progress-spinner off
```

Final verification: **434 passed, 2 live-provider tests skipped**, **82.66% app
coverage**, 381.78 seconds on this workstation. Ruff and mypy pass; dependency
audit reports no known vulnerabilities. Mock adversarial evaluation passes 29/29;
retrieval smoke completes; golden smoke passes 18/18; the full golden gate passes.
The final confirmation run is
`reports/eval/golden_baseline_all_20260929T104140482687Z.json` (102/111, zero
unknown, zero LLM calls). Its slower 151.446-second duration was recorded while
tests were also running and must not be used as a latency comparison. Test
stdout is ignored at `reports/eval/integrity_20260929/final_verification_stdout.log`.

Run each dataset with `uv run --frozen python -m app.evals.run_golden_eval
--dataset <path> --output-dir reports/eval/integrity_20260929`. LLM mode defaults
to off; providers are disabled. Full legacy golden runs intentionally return a
nonzero status for known failing cases after saving JSON/Markdown.

| Dataset | Before | After | Unknown |
| --- | ---: | ---: | ---: |
| Single-turn v2 | 92/101 | 93/101 | 0 |
| Conversations v1 | 9/10 | 9/10 | 0 |
| Combined Phoenix v2 | 101/111 | 102/111 (91.9%) | 0 |
| New integrity regressions | not run | 10/10 | 0 |

The combined dataset duplicates single-turn/conversation rows: 111 distinct
legacy cases, not 222. The ten new cases are review-derived regressions despite
their `holdout` filename, not an untouched independent benchmark.

Local machine-readable artifacts are ignored under
`reports/eval/integrity_20260929/`:

- Conversations: `golden_baseline_all_20260929T103059254192Z.json`.
- Single-turn: `golden_baseline_all_20260929T103109483456Z.json`.
- Integrity: `golden_baseline_all_20260929T103205073809Z.json`.
- Combined: `golden_baseline_all_20260929T103208803302Z.json`.

The combined run took 59.663 seconds and delivered 94 estimates, 14
clarifications and 3 refusals. This is local, sequential, offline timing, not a
production SLA or evidence of faster external calls. Case `030` now respects
explicit 32 g rather than a 28 g household conversion. Remaining failures are
`053`, `054`, `065`, `075`, `076`, `081`, `088`, `098` and conversation `010`.
They are not fixed by changing golden references or tuning priors. Missing-food
cases now fail honestly with clarification; recipe/portion expectations and the
existing policy/text-check tensions remain.

Protected results: basic 22/22, branded 6/6, cafe 3/3, packaged 11/11,
memory-tagged 8/8, safety/refusal 3/3. Mixed dishes remain 42/49. EN is 49/53;
RU is 53/58. Of 86 numerically scored estimates, calorie MAE is 21.20 kcal,
MAPE 6.65%, p90 absolute error 65 kcal, maximum error 285 kcal, mean interval
width 47.33 kcal and reference coverage 63.95%. Protein/fat/carbohydrate MAE is
1.62/1.66/3.24 g. Case `088` still predicts 195 kcal against a 480 kcal reference;
the portion assumption needs independent evidence, not reference-fitting. A
literal below-half-reference test also flags Zero cola's rounded 0 versus 1 kcal,
which is not a materially catastrophic underestimate.

Numeric scoring now excludes hidden totals on delivered clarifications/refusals,
so numeric aggregates are not directly comparable to old reports that included
them. Macro errors remain advisory. Required language labels, dataset completeness,
missing safety buckets, protected category failures and unknown statuses are
checked. CI's overall floor increases from 60% to 90%; it does not claim that a
passing gate establishes broad safety from only three legacy refusal examples.

## Deferred Measurements And Residual Limits

The new `app.evals.benchmark_models` driver requires `--allow-paid-api`, defaults
to three examples/two repeats, alternates model order, freezes local provider
priors and records prompt/dataset hashes. It has not been run against paid APIs.
Task-specific reasoning settings avoid applying a text experiment's parameters
to the shipped critic/vision configuration. Model-name compatibility and output
bounds are tested with constructor mocks; remote account/model/schema support
still needs a real canary before a full run. Luna defaults explicitly to reasoning
`none`, following [model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna)
and [parameter guidance](https://developers.openai.com/api/docs/guides/latest-model).

Before promotion: obtain authorization for paired paid trials, freeze an
independent EN/RU holdout, and add licensed/labeled real food, packaging, non-food
and caption-conflict images. No supplied golden row contains a real image;
synthetic schema tests are not a substitute. Image moderation, component-recall
annotations and live-provider latency/quality measurements remain follow-ups.
Do not change default models, add a new provider or deploy on the basis of these
offline results alone.

Other retained limitations: incomplete vocabulary, conservative fact extraction,
startup-only retention pruning, synchronous small auth reads in async handlers,
HTTP liveness rather than Telegram-polling readiness, and no dollar-denominated
spend ceiling. Conserving stated mass does not prove ingredient recall: allocations
can still miss unknown composition without annotated components or a validated
model extraction. Optional other-provider/self-hosted experiments remain deferred.
