# Live Golden Evaluation - 2026-06-24

## Executive Result

The real production LLM path improves the deterministic fallback result, but only
modestly and with meaningful regressions.

- The deterministic off lane passed **69/111 (62.16%)**.
- Two real-LLM, provider-off repeats passed **74/111 (66.67%)** and
  **72/111 (64.86%)**.
- Of the off lane's 42 failures, the real LLM path fixed the same **9 cases in both
  repeats (21.43%)**. The other **33 failed in both repeats (78.57%)**.
- The live path also broke cases that pass off: **4 regressions in repeat 1** and
  **6 in repeat 2**, with 8 distinct regression cases across the two runs.
- All live-only regressions ended at the bounded critic loop's iteration cap. The
  critic fixed none of the 42 off-lane failures.
- The live end-to-end provider run passed **66/111 (59.46%)**. On the 91 estimate
  cases with an acceptable calorie range, **47 (51.65%)** overlapped the range,
  32 missed it, and 12 could not be evaluated because no calorie estimate was
  parseable.
- End-to-end calorie MAPE was **30.10%** on 78 parsed, non-zero-calorie reference
  cases. MAE was **118.7 kcal** on 79 parsed reference cases.

The 62% off-lane score is partly a measurement artifact, but not mainly one. A real
parser reliably recovers 9 failures, while 33 remain production-path failures.
Real provider data did not improve the aggregate score in this run.

## 1. Setup And Provenance

All official runs used the same repository state:

- Commit: `afbec09687e1b1d7c65b1ceeb780f1256daaa53c`
- Date: 2026-06-24
- Dataset:
  `evals/datasets/nutrition_agent_phoenix_eval_datasets_v2.jsonl`
- Dataset size: 111 examples (101 single-turn, 10 conversations)
- Text model alias: `gpt-4.1-mini`
- Model snapshot reported by the API: `gpt-4.1-mini-2025-04-14`
- Critic model alias: `gpt-4.1-mini`
- Temperature: `0.0`
- Critic maximum iterations: `2`
- OpenAI moderation: enabled in live lanes
- Macro range checks: advisory; calorie overlap is the strict numeric gate
- Live-parser repeats: 2 full 111-case runs
- Product code changes: none
- Deployment: none

The eval runner was extended before measurement, in commit `afbec09`, to record
elapsed time, LangChain token usage, estimated cost, graph state, critic activity,
retrieval diagnostics, selected provider identity, and provider warnings. These
changes are confined to `app/evals/` and tests.

### Commands

Run A, fallback with providers off:

```bash
uv run python -m app.evals.run_golden_eval \
  --dataset evals/datasets/nutrition_agent_phoenix_eval_datasets_v2.jsonl \
  --llm-mode off \
  --output-dir reports/eval/live_golden_20260624/off
```

Run B, circular stub control with providers off:

```bash
uv run python -m app.evals.run_golden_eval \
  --dataset evals/datasets/nutrition_agent_phoenix_eval_datasets_v2.jsonl \
  --llm-mode stub \
  --output-dir reports/eval/live_golden_20260624/stub
```

Runs C1 and C2, real parser with providers off:

```bash
uv run python -m app.evals.run_golden_eval \
  --dataset evals/datasets/nutrition_agent_phoenix_eval_datasets_v2.jsonl \
  --llm-mode live \
  --allow-paid-api \
  --output-dir reports/eval/live_golden_20260624/live_parser_1
```

The same command was repeated with output directory `live_parser_2`.

Run D, real parser and live providers:

```bash
NUTRITION_CACHE_DIR=/tmp/nutrition-agent-live-eval-cache-afbec09 \
uv run python -m app.evals.run_golden_eval \
  --dataset evals/datasets/nutrition_agent_phoenix_eval_datasets_v2.jsonl \
  --llm-mode live \
  --allow-paid-api \
  --live-providers \
  --output-dir reports/eval/live_golden_20260624/live_providers
```

The Run D cache directory did not exist before the command. It was not committed.

Pairwise comparisons were generated with:

```bash
uv run python -m app.evals.compare_golden_lanes \
  --fallback-run <left-run.json> \
  --llm-run <right-run.json> \
  --output-dir reports/eval/live_golden_20260624/comparisons/<comparison>
```

Comparisons recorded: A-C1, A-C2, B-C1, B-C2, and A-D.

### Cost Control And Actual Usage

The pre-run ceiling was **$5**. Pricing used for estimation was the official
GPT-4.1 mini rate checked on 2026-06-24: $0.40 per million input tokens, $0.10 per
million cached input tokens, and $1.60 per million output tokens. Source:
[OpenAI GPT-4.1 mini model page](https://developers.openai.com/api/docs/models/gpt-4.1-mini).

| Run | Calls | Input tokens | Output tokens | Total tokens | Estimated cost |
|---|---:|---:|---:|---:|---:|
| C1 | 334 | 150,250 | 24,594 | 174,844 | $0.099450 |
| C2 | 333 | 150,037 | 24,187 | 174,224 | $0.098714 |
| D | 333 | 149,915 | 24,723 | 174,638 | $0.099523 |
| **Total official live runs** | **1,000** | **450,202** | **73,504** | **523,706** | **$0.297687** |

No callback-reported LLM errors occurred. The API reports token usage, not billed
currency, so dollar values are estimates from the recorded tokens and published
rates. A one-case preflight used an additional estimated $0.00213 and is excluded
from the official result table.

## 2. Lane Summary

| Lane | Providers | Passed | Failed | Pass rate | Runtime |
|---|---|---:|---:|---:|---:|
| A: off | off | 69 | 42 | 62.16% | 34.8 s |
| B: stub | off | 89 | 22 | 80.18% | 80.8 s |
| C1: live parser | off | 74 | 37 | 66.67% | 627.6 s |
| C2: live parser | off | 72 | 39 | 64.86% | 618.6 s |
| D: live end-to-end | on | 66 | 45 | 59.46% | 1,629.3 s |

The stub score is not a model-quality result. Its estimate fixtures scale known
local foods from golden reference calories, so many estimate cases pass by
construction. The fact that stub reaches 80.18% while live reaches 64.86-66.67%
quantifies the stub's circular optimism.

Pairwise status changes:

| Comparison | Fail to pass | Pass to fail | Net passed |
|---|---:|---:|---:|
| A vs C1 | 9 | 4 | +5 |
| A vs C2 | 9 | 6 | +3 |
| B vs C1 | 4 | 19 | -15 |
| B vs C2 | 4 | 21 | -17 |
| A vs D | 14 | 17 | -3 |

## 3. Headline: The 42 Off-Lane Failures

### Fixed By Live Parsing In Both Repeats: 9

| ID | Input | Result |
|---|---|---|
| `na_golden_030` | Macros in 2 tbsp peanut butter, 32g | pass in C1/C2 |
| `na_golden_051` | Сколько калорий в шакшуке 300 г? | pass in C1/C2 |
| `na_golden_054` | Calories and macros in a tuna sandwich | pass in C1/C2 |
| `na_golden_057` | Сколько БЖУ в буррито с курицей 400 г? | pass in C1/C2 |
| `na_golden_065` | Сколько калорий в поке с лососем 450 г? | pass in C1/C2 |
| `na_golden_069` | Сколько калорий в жареном рисе с яйцом и курицей 400 г? | pass in C1/C2 |
| `na_golden_075` | Сколько БЖУ в грибном ризотто 350 г? | pass in C1/C2 |
| `na_golden_090` | Calories in 250g cottage cheese with honey | pass in C1/C2 |
| `na_conv_010_photo_missing_stays_clarification` | На фото еда, посчитай | pass in C1/C2 |

### Still Failing In Both Repeats: 33

The clusters below are mutually exclusive primary diagnoses based on the captured
meal parse, retrieval failures, selected identities, totals, and final behavior.

#### Retrieval Coverage Or Unmatched Parsed Ingredients: 16 (48.5%)

The parser produced useful structure, but one or more important ingredients had no
valid nutrition candidate. Partial totals were then too low, absent, or converted
to clarification.

`na_golden_043`, `na_golden_047`, `na_golden_048`, `na_golden_049`,
`na_golden_053`, `na_golden_055`, `na_golden_058`, `na_golden_061`,
`na_golden_064`, `na_golden_066`, `na_golden_070`, `na_golden_071`,
`na_golden_074`, `na_golden_076`, `na_golden_081`, `na_golden_082`.

Examples include Russian `Куриный бульон`, `Блины`, `Гречневая крупа`,
`индейка`, `лаваш`, and English `Syrniki`, `Taco Shells`, `Ramen noodles`,
`Quinoa`, and `Pancakes`.

#### Wrong Food Link Or Omitted Main Components: 6 (18.2%)

| ID | Observed link/parse problem |
|---|---|
| `na_golden_046` | potato vareniki linked as boiled potato |
| `na_golden_059` | chicken curry with rice reduced to rice only |
| `na_golden_067` | pho bo linked as vegetable soup |
| `na_golden_083` | muesli, yogurt, and berries reduced to yogurt only |
| `na_golden_085` | whole chicken Caesar wrap linked as chicken breast |
| `na_golden_089` | grilled shrimp salad reduced to salad vegetables |

#### Portion Allocation Or Whole-Dish Decomposition Error: 5 (15.2%)

| ID | Observed portion problem |
|---|---|
| `na_golden_077` | 500 g steak-and-fries plate allocated up to 300 g to each component |
| `na_golden_080` | 400 g lentil soup counted as 400 g lentils plus 250-400 g soup |
| `na_golden_086` | 500 g beef udon counted as 500 g pasta plus 100-170 g beef |
| `na_golden_087` | 300 g salad components summed to roughly 545 g midpoint |
| `na_golden_088` | scrambled eggs and toast assumed only about 165 g midpoint and omitted cooking fat |

#### Reference/Profile Disagreement: 2 (6.1%)

- `na_golden_038`: 125 g mozzarella predicted 340-360 kcal versus a
  238-322 kcal acceptable range.
- `na_golden_039`: 100 g hummus predicted 170 kcal versus a 204-276 kcal
  acceptable range.

These parsed and linked correctly; the committed fallback profile and golden
reference disagree.

#### Over-Clarification Before A Useful Compound Parse: 3 (9.1%)

- `na_golden_068`: chicken pad thai
- `na_golden_072`: kebab plate with rice
- `na_golden_078`: six chicken nuggets

These ended with no parsed ingredients and a clarification despite sufficient
dataset detail for an approximate estimate.

#### Under-Clarification: 1 (3.0%)

- `na_golden_098`: "How many calories in chicken and rice?" should clarify the
  portion, but both live runs invented portions and returned an estimate.

## 4. Live-Only Regressions

Eight distinct cases passed in off mode but failed in at least one live repeat.

| ID | Input | C1 | C2 | Mechanism |
|---|---|---|---|---|
| `na_golden_001` | Сколько калорий в одном среднем банане? | fail | fail | critic cap -> clarification |
| `na_golden_023` | Сколько калорий в банке Coca-Cola Zero 330 мл? | fail | fail | critic cap -> clarification |
| `na_golden_014` | Calories in 250ml 2% milk | fail | pass | critic cap in C1 |
| `na_golden_028` | Calories in 100g baguette | fail | pass | critic cap in C1 |
| `na_golden_009` | Сколько калорий в двух кусках цельнозернового хлеба? | pass | fail | critic cap in C2 |
| `na_golden_010` | Macros for 100g avocado | pass | fail | critic cap in C2 |
| `na_golden_033` | Сколько БЖУ в пачке лапши быстрого приготовления 85 г? | pass | fail | critic cap in C2 |
| `na_golden_073` | Сколько калорий в тарелке хумуса с питой, примерно 300 г? | pass | fail | critic cap in C2 |

The two stable regressions are banana and Coca-Cola Zero. The other six are
stochastic regressions: they pass in one live repeat and fail in the other.

## 5. Compound-Dish Routing And Critic Loop

### Compound-Dish Routing

The six cases previously used to validate the compound-dish parser route were:

`na_golden_043`, `na_golden_049`, `na_golden_057`, `na_golden_069`,
`na_golden_071`, and `na_golden_085`.

The live parser was reached and produced structured meal output, so the routing
bypass itself is functioning. End results:

- Pass in both repeats: `na_golden_057` (chicken burrito) and
  `na_golden_069` (fried rice with egg and chicken).
- Still fail: `na_golden_043` (unmatched chicken broth/meat),
  `na_golden_049` (unmatched Russian buckwheat), `na_golden_071` (unmatched
  lavash/sauce), and `na_golden_085` (whole wrap linked as chicken breast).

Thus the machinery resolves **2/6** target cases end-to-end. The remaining errors
have moved downstream into retrieval/linking or nutrition accuracy.

### Bounded Critic Loop

| Metric | C1 | C2 |
|---|---:|---:|
| Cases entering revision loop | 7 | 7 |
| Revision-loop cases passing | 1 | 0 |
| Revision-loop cases failing | 6 | 7 |
| LLM critic decisions | 132 | 132 |
| `revise` decisions | 21 | 21 |
| Final deterministic critic-cap clarifications | 7 | 7 |

The one C1 revision-loop pass, `na_conv_004_en_rice_followup`, already passes in
off mode, so it is not evidence of a recovered failure. No one of the 42 off-lane
failures was fixed by critic revision.

Conversely, every live-only regression listed above reached
`critic_iteration=2` and settled on a clarification at the cap. On this dataset,
the bounded critic loop **hurts the measured result**: it introduces 4-6
regressions per run and produces no observed recovery of an off-lane failure.

This is an observational conclusion for these runs, not a general claim that a
critic can never help.

## 6. Live End-To-End Providers

Run D used a new empty cache and all configured providers.

### Accuracy

- Overall golden pass rate: **66/111 (59.46%)**
- Strict calorie-range eligible cases: 91
- Calorie range overlap: **47/91 (51.65%)**
- Calorie range miss: **32/91 (35.16%)**
- Unparseable/no calorie estimate: **12/91 (13.19%)**
- Overlap among cases with a parsed calorie estimate: **47/79 (59.49%)**
- MAE: **118.7 kcal** on 79 parsed references
- MAPE: **30.10%** on 78 parsed, non-zero references
- Median absolute percentage error: **17.42%**

Run D fixed 14 off failures but regressed 17 off passes, for a net change of -3
passes relative to Run A.

### Selected Nutrition Sources

Across 145 selected ingredient candidates:

| Selected source | Ingredients | Share |
|---|---:|---:|
| USDA | 114 | 78.6% |
| Explicit local fallback | 27 | 18.6% |
| Open Food Facts | 3 | 2.1% |
| Generic composite fallback | 1 | 0.7% |
| FatSecret | 0 | 0.0% |

Estimate-case attribution:

| Provider set | Cases | Parsed | Calorie pass/fail/unknown | MAPE |
|---|---:|---:|---|---:|
| USDA only | 64 | 61 | 32 / 25 / 3, plus 4 N/A | 35.40% |
| Local fallback only | 16 | 14 | 9 / 3 / 2, plus 2 N/A | 9.66% |
| USDA + fallback | 9 | 8 | 4 / 4 / 1 | 24.48% |
| Open Food Facts only | 3 | 2 | 1 / 0 / 1, plus 1 N/A | 0.72% |
| Generic fallback + USDA | 1 | 1 | 1 / 0 / 0 | 26.74% |
| No selected provider | 5 | 0 | 0 / 0 / 5 | N/A |

Small provider groups, especially Open Food Facts and generic fallback, are too
small for general conclusions.

### Provider Degradation

FatSecret returned `api_error_code=21` **249 times across 96 cases** and supplied
zero selected candidates. This is an account/IP restriction, not a model error.

There were also 43 other captured provider warnings across 18 cases:

- 41 USDA detail failures, primarily repeated HTTP 404 responses for returned food
  IDs, plus one timeout.
- 2 Open Food Facts HTTP 503 responses.

The provider-on score therefore measures the current real degradation behavior,
not an ideal all-provider environment.

## 7. Variance And Confidence

- Status was stable for **105/111 cases (94.59%)** across C1 and C2.
- Six cases flipped pass/fail: `na_golden_009`, `na_golden_010`,
  `na_golden_014`, `na_golden_028`, `na_golden_033`, and `na_golden_073`.
- All six flips were critic-cap outcomes, not changes among the 42 baseline
  failures.
- The 42 off-lane failures were **100% stable by status** across repeats:
  the same 9 passed and the same 33 failed.
- Of 80 cases with parsed calories in both repeats, 10 had a different calorie
  midpoint. Their median absolute midpoint difference was 42.5 kcal and the
  maximum was 85 kcal.
- Aggregate live-parser pass rates differed by 1.80 percentage points
  (66.67% versus 64.86%).

Confidence is high for the headline 9-fixed/33-remaining split because it repeated
exactly. Confidence is lower for the precise overall live pass rate and for any
single passing control case affected by the critic, because two repeats exposed
stochastic cap behavior.

## 8. Conclusion

The deterministic 62.16% score is not a fair production score, but its pessimism
is limited. A real GPT-4.1-mini parser raises the result to 64.86-66.67%, reliably
fixing 9 of 42 baseline failures. The other 33 failures remain, dominated by
retrieval coverage, semantic food linking, omitted dish components, and portion
allocation.

The current critic loop is not helping this benchmark. It consumes a substantial
fraction of live model calls, fixes no baseline failure, and causes every observed
live-only regression through cap-triggered clarification.

The real-provider result is worse at 59.46%, with 30.10% calorie MAPE. FatSecret
was unavailable throughout, USDA dominated selected candidates, and provider
failures were common. The next empirical priority indicated by these numbers is
the retrieval/link/portion path and critic reliability, not simply adding more
parser prompting.

No product changes or deployment were performed for this measurement.

## Artifacts

Raw run JSON/Markdown and pairwise comparisons are under:

`reports/eval/live_golden_20260624/`

The JSON artifacts contain per-case answers, evaluations, latency, token usage,
critic state, retrieval diagnostics, provider selections, and captured provider
warnings. `MANIFEST.sha256` records artifact checksums.
