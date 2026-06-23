# NutritionAgent Eval Investigation - 2026-06-23

## Scope

This was an investigation-only pass on `main`. No product code was changed and no service was deployed.

- Commit: `8e941a03b36a1afa8a5591f15848bbffaf3c5dc0`
- Commit subject: `8e941a0 Centralize food vocabulary and add shadow linker`
- Branch: `main`
- Run date: `2026-06-23`
- Main combined eval timestamp: `2026-06-23T15:54:57.071035+00:00`
- Golden eval config: `use_llm=false`, `live_providers=false`, `macro_ranges_are_advisory=true`
- Fresh generated artifacts: `reports/eval/investigation_20260623/`
- Note: generated eval artifacts are ignored and are not part of this report commit.

## Step 1 - Fresh Results

### Commands

```bash
git rev-parse HEAD
git log -1 --oneline
```

```bash
rm -rf reports/eval/investigation_20260623
mkdir -p reports/eval/investigation_20260623

(
  /usr/bin/time -p -o reports/eval/investigation_20260623/pytest.time \
    uv run pytest -q \
    > reports/eval/investigation_20260623/pytest.out 2>&1
  echo $? > reports/eval/investigation_20260623/pytest.exit
) &

(
  /usr/bin/time -p -o reports/eval/investigation_20260623/single_turn.time \
    uv run python -m app.evals.run_golden_eval \
      --dataset evals/datasets/nutrition_agent_golden_single_turn_v2.jsonl \
      --output-dir reports/eval/investigation_20260623 \
    > reports/eval/investigation_20260623/single_turn.out 2>&1
  echo $? > reports/eval/investigation_20260623/single_turn.exit
) &

(
  /usr/bin/time -p -o reports/eval/investigation_20260623/conversations.time \
    uv run python -m app.evals.run_golden_eval \
      --dataset evals/datasets/nutrition_agent_golden_conversations_v1.jsonl \
      --output-dir reports/eval/investigation_20260623 \
    > reports/eval/investigation_20260623/conversations.out 2>&1
  echo $? > reports/eval/investigation_20260623/conversations.exit
) &

(
  /usr/bin/time -p -o reports/eval/investigation_20260623/phoenix.time \
    uv run python -m app.evals.run_golden_eval \
      --dataset evals/datasets/nutrition_agent_phoenix_eval_datasets_v2.jsonl \
      --output-dir reports/eval/investigation_20260623 \
    > reports/eval/investigation_20260623/phoenix.out 2>&1
  echo $? > reports/eval/investigation_20260623/phoenix.exit
) &

wait
```

```bash
/usr/bin/time -p -o reports/eval/investigation_20260623/mock_eval.time \
  uv run python -m app.evals.run_eval --mock \
  > reports/eval/investigation_20260623/mock_eval.out 2>&1

/usr/bin/time -p -o reports/eval/investigation_20260623/retrieval_smoke.time \
  uv run python -m app.evals.run_retrieval_smoke \
  > reports/eval/investigation_20260623/retrieval_smoke.out 2>&1

/usr/bin/time -p -o reports/eval/investigation_20260623/nutrition_eval.time \
  uv run python -m app.evals.run_nutrition_eval --max-examples 3 \
  > reports/eval/investigation_20260623/nutrition_eval.out 2>&1

/usr/bin/time -p -o reports/eval/investigation_20260623/food_linker_shadow.time \
  uv run python -m app.evals.food_linker_shadow_report \
    --threshold 0.62 \
    --output-dir reports/eval/investigation_20260623 \
  > reports/eval/investigation_20260623/food_linker_shadow.out 2>&1
```

### Test And Eval Summary

| Run | Dataset / Scope | Exit | Wall time | Passed | Failed | Total | Pass rate |
|---|---|---:|---:|---:|---:|---:|---:|
| Unit tests | `uv run pytest -q` | 0 | 43.07s | 212 | 0 | 214 | 212 passed, 2 skipped |
| Golden single-turn | `nutrition_agent_golden_single_turn_v2.jsonl` | 1 | 7.69s | 60 | 41 | 101 | 59.41% |
| Golden conversations | `nutrition_agent_golden_conversations_v1.jsonl` | 1 | 4.58s | 9 | 1 | 10 | 90.00% |
| Golden combined / Phoenix | `nutrition_agent_phoenix_eval_datasets_v2.jsonl` | 1 | 9.20s | 69 | 42 | 111 | 62.16% |
| Mock eval | `app.evals.run_eval --mock` | 0 | 3.32s | 20 | 0 | 20 | 100.00% |
| Retrieval smoke | `app.evals.run_retrieval_smoke` | 0 | 2.15s | n/a | n/a | n/a | Passed |
| Tiny nutrition eval | OpenIntro fastfood sample, 3 examples | 0 | 3.14s | n/a | n/a | 3 | calorie-in-range 0.00% |
| Food linker shadow | golden rows, threshold `0.62` | 0 | 2.59s | 107 agreements | 14 disagreements | 121 | 88.43% agreement |

`run_golden_eval` exits non-zero when examples fail, so the three golden eval exit codes are expected.

Fresh per-case result files:

- Single-turn: `reports/eval/investigation_20260623/golden_baseline_all_20260623T155457071144Z.json`
- Conversations: `reports/eval/investigation_20260623/golden_baseline_all_20260623T155457064650Z.json`
- Combined/Phoenix: `reports/eval/investigation_20260623/golden_baseline_all_20260623T155457071035Z.json`
- Food linker shadow: `reports/eval/investigation_20260623/food_linker_shadow_20260623_155611.json`
- Tiny nutrition eval: `reports/eval/nutrition_eval_20260623T155607Z.json`

### Combined Golden Breakdown

The combined dataset is the most useful single summary because it contains the single-turn and conversation examples.

| Dimension | Bucket | Passed | Failed | Total | Pass rate |
|---|---|---:|---:|---:|---:|
| kind | `single_turn` | 60 | 41 | 101 | 59.41% |
| kind | `conversation` | 9 | 1 | 10 | 90.00% |
| language | `en` | 33 | 20 | 53 | 62.26% |
| language | `ru` | 36 | 22 | 58 | 62.07% |
| expected behavior | `estimate` | 58 | 40 | 98 | 59.18% |
| expected behavior | `clarify` | 8 | 2 | 10 | 80.00% |
| expected behavior | `refuse` | 3 | 0 | 3 | 100.00% |
| category | `basic` | 22 | 0 | 22 | 100.00% |
| category | `branded` | 6 | 0 | 6 | 100.00% |
| category | `cafe` | 3 | 0 | 3 | 100.00% |
| category | `conversation_memory` | 9 | 1 | 10 | 90.00% |
| category | `edge_case` | 9 | 1 | 10 | 90.00% |
| category | `mixed_dish` | 12 | 37 | 49 | 24.49% |
| category | `packaged` | 8 | 3 | 11 | 72.73% |

Key observation: the service is not generally failing Russian, routing, refusals, basic foods, branded/cafe cases, or memory. The dominant weakness is mixed dishes.

### Auxiliary Eval Notes

The tiny nutrition eval is intentionally only a smoke-quality eval. It still highlights the offline local-table gap:

- `mean_absolute_calorie_error`: `220.0`
- `mean_absolute_calorie_percentage_error`: `68.0`
- `calorie_within_range_rate`: `0.0`
- `mean_expected_ingredient_recall`: `0.3333`
- FatSecret logged `api_error_code=21 message=account or IP restriction`, so that run effectively relied on local/offline behavior.

The food-linker shadow report is not production behavior yet because embedding linking remains disabled by default. At threshold `0.62`, it reported `107/121` agreements and `14` disagreements. Several disagreements are exactly in the mixed-dish area (`куриный суп`, `гречка с курицей`, `fish and chips`, `салат с помидорами и моцареллой`), so enabling it as primary would be premature.

## Step 2 - Comparison Against Previous Runs

### Available Baselines

Committed eval artifacts exist under:

- `reports/eval/baseline/`
- `reports/eval/post_change/`

Additional local ignored runs exist under `reports/eval/`, including runs from `2026-06-22` and `2026-06-23`. I did not query a live Phoenix server or external Phoenix experiments for this investigation. No Phoenix experiment export was found in the repository beyond the local JSON/Markdown eval reports.

### Metric-Level Comparison

| Baseline | Baseline total | Baseline pass | Current comparable pass | Common IDs | Fail -> Pass | Pass -> Fail | Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| `reports/eval/baseline/golden_baseline_golden_20260620T012752900266Z.json` | 110 | 28 / 110, 25.45% | 68 / 110, 61.82% | 110 | 43 | 3 | Current dataset adds `na_golden_101` |
| `reports/eval/post_change/golden_baseline_golden_20260621T002820068183Z.json` | 110 | 67 / 110, 60.91% | 68 / 110, 61.82% | 110 | 1 | 0 | Current dataset adds `na_golden_101` |
| `reports/eval/golden_baseline_golden_20260622T192933227868Z.json` | 111 | 69 / 111, 62.16% | 69 / 111, 62.16% | 111 | 0 | 0 | Same current outcome |

The large improvement happened between the first committed baseline and the post-change baseline. Since the `2026-06-21` post-change baseline, current deterministic golden performance is essentially stable, with one additional pass on the common 110 examples and no pass-to-fail flips.

### Per-Case Flips

Against the first committed baseline, the current run has 43 common examples that flipped from fail to pass:

`na_conv_007_pending_then_new_food_not_merged`, `na_conv_009_salad_stays_clarification`, `na_golden_001`, `na_golden_003`, `na_golden_004`, `na_golden_005`, `na_golden_009`, `na_golden_010`, `na_golden_011`, `na_golden_013`, `na_golden_015`, `na_golden_017`, `na_golden_018`, `na_golden_019`, `na_golden_020`, `na_golden_023`, `na_golden_024`, `na_golden_025`, `na_golden_026`, `na_golden_027`, `na_golden_028`, `na_golden_029`, `na_golden_031`, `na_golden_032`, `na_golden_033`, `na_golden_034`, `na_golden_035`, `na_golden_036`, `na_golden_037`, `na_golden_040`, `na_golden_041`, `na_golden_042`, `na_golden_044`, `na_golden_045`, `na_golden_052`, `na_golden_056`, `na_golden_062`, `na_golden_073`, `na_golden_079`, `na_golden_084`, `na_golden_092`, `na_golden_093`, `na_golden_094`.

Against that same first baseline, 3 examples flipped from pass to fail:

- `na_golden_030`
- `na_golden_059`
- `na_golden_086`

Against the `2026-06-21` post-change baseline, only `na_golden_045` flipped from fail to pass, with no pass-to-fail flips. This suggests recent architecture changes have not created a broad regression in the deterministic golden set.

Relevant eval-related commits in recent history:

```text
8e941a0 Centralize food vocabulary and add shadow linker
538eaa3 Add bounded hybrid critic correction loop
cd4752a Fix verified zero-calorie water estimates
0bd9e54 Improve deterministic multilingual food parsing
7644a14 Commit golden evaluation baseline
c963ccb Add golden evaluation workflow
89d2db3 Improve nutrition retrieval providers
342f3d0 Add tiny nutrition eval workflow
4ef5b5a Prepare repository for public release
```

## Step 3 - Error Analysis

### Failure Clusters

The current combined run has 42 failures.

| Cluster | Count | Share of failures | Case IDs |
|---|---:|---:|---|
| Over-clarification / unsupported mixed dish | 23 | 54.76% | `na_golden_043`, `047`, `048`, `049`, `051`, `053`, `054`, `055`, `057`, `061`, `064`, `066`, `067`, `068`, `069`, `070`, `071`, `072`, `074`, `075`, `078`, `082`, `085` |
| Numeric calorie miss after producing an estimate | 17 | 40.48% | `na_golden_030`, `038`, `039`, `046`, `058`, `059`, `065`, `076`, `077`, `080`, `081`, `083`, `086`, `087`, `088`, `089`, `090` |
| Under-clarification / estimate-first policy too permissive | 1 | 2.38% | `na_golden_098` |
| Clarification wording mismatch | 1 | 2.38% | `na_conv_010_photo_missing_stays_clarification` |

By metadata:

- Language: `ru` 22 failures, `en` 20 failures. This is balanced and does not indicate a Russian-only regression.
- Kind: `single_turn` 41 failures, `conversation` 1 failure.
- Category: `mixed_dish` 37 failures, `packaged` 3 failures, `edge_case` 1 failure, `conversation_memory` 1 failure.
- Issue classification from the eval runner: `unsupported_current_behavior` 23, `real_system_failure` 18, `likely_dataset_issue` 1.

### Representative Failures

`na_golden_043` asks in Russian for a 400 g plate of chicken soup. Expected behavior is an estimate, but the service asks for chicken cut/preparation:

```text
Нужно еще немного информации для надежной оценки: Уточните, пожалуйста: какая часть курицы, как продукт был приготовлен.
```

This is a mixed dish being treated like a generic single chicken request.

`na_golden_076` asks for fish and chips, about 450 g. The answer estimates only `potato chips: 450 g`, producing `2410 kcal` against an acceptable range of `808-1092 kcal`:

```text
Estimated calories: 2410-2410 kcal
Protein: 32-32 g
Fat: 158-158 g
Carbs: 238-238 g
Main assumptions:
* potato chips: 450-450 g (explicit gram weight).
```

This is a bad food link plus bad total-weight allocation.

`na_golden_098` asks `How many calories in chicken and rice?`. The dataset expects clarification, but the service estimates a standard chicken-and-rice portion. This is a policy boundary issue rather than a technical parsing failure.

`na_conv_010_photo_missing_stays_clarification` correctly clarifies, but the wording does not contain one of the expected terms about photo/description. This is best classified as either evaluator wording strictness or low-priority copy improvement.

### Numeric Misses

Numeric failures are not random; most are portion allocation or local-profile issues.

| ID | Category | Predicted calories | Acceptable calories | Likely failure mode |
|---|---|---:|---:|---|
| `na_golden_030` | packaged | 160 | 162-218 | local profile/range mismatch; near boundary |
| `na_golden_038` | packaged | 350 | 238-322 | mozzarella profile/portion mismatch |
| `na_golden_039` | packaged | 170 | 204-276 | hummus profile/portion mismatch |
| `na_golden_046` | mixed dish | 220 | 366-494 | dish profile too low / missing components |
| `na_golden_058` | mixed dish | 750 | 442-598 | dish profile/portion too high |
| `na_golden_059` | mixed dish | 580 | 612-828 | near-ish under-estimate |
| `na_golden_065` | mixed dish | 930 | 552-748 | component/default portions too high |
| `na_golden_076` | mixed dish | 2410 | 808-1092 | `chips` linked as potato chips and assigned full 450 g |
| `na_golden_077` | mixed dish | 440 | 765-1035 | missing/under-weighted steak and fries composition |
| `na_golden_080` | mixed dish | 580-640 | 306-414 | soup composition too dense |
| `na_golden_081` | mixed dish | 560-690 | 366-494 | total oatmeal weight assigned incorrectly across ingredients |
| `na_golden_083` | mixed dish | 210 | 408-552 | missing/under-weighted muesli/yogurt composition |
| `na_golden_086` | mixed dish | 1040-1220 | 646-874 | component/default portions too high |
| `na_golden_087` | mixed dish | 870-900 | 357-483 | 300 g salad weight assigned to mozzarella plus defaults |
| `na_golden_088` | mixed dish | 160-230 | 408-552 | missing toast/fat or insufficient portion |
| `na_golden_089` | mixed dish | 70 | 298-402 | missing dressing/portion composition |
| `na_golden_090` | mixed dish | 300 | 306-414 | near boundary |

## Step 4 - Architecture Review And Root Causes

### Current Pipeline

The graph is still a controlled pipeline, not an unconstrained agent loop. In `app/graph/graph.py`, the flow is:

1. `normalize_input`
2. `input_moderation`
3. `scope_classifier`
4. `route`
5. one of `refuse`, `ask_clarification`, `parse_text_meal`, `recognize_dish_photo`, `combine_text_and_image`, or `recognize_packaging`
6. `retrieve_nutrition`
7. `calculate_macros`
8. `synthesize_answer`
9. `critic`
10. `output_moderation`, or bounded answer regeneration through `prepare_critic_revision`

`process_request` loads per-user/per-session memory before graph invocation, rewrites short follow-ups when appropriate, invokes the graph, and records the turn afterward.

The text path is currently a local parser first. In `app/graph/nodes/text_parser.py`, `parse_text_meal` calls `parse_text_locally`; with `use_llm=false`, evals do not use the LLM parser. The local parser:

- derives unresolved generic tasks such as chicken/fish/rice/yogurt;
- asks clarification for some single-food requests;
- detects food mentions through `find_food_mentions`;
- estimates portions with `estimate_portion`;
- returns deterministic `IngredientEstimate` rows.

Nutrition totals are deterministic in `app/graph/nodes/calculator.py`: each ingredient gets a per-100 g candidate, is scaled by `grams_min/max`, and then summed. The critic checks internal consistency and output formatting, but it does not reparse food, rerun retrieval, or change totals.

### Root Cause 1 - Mixed Dishes Lack Enough Deterministic Dish Priors

Evidence: `mixed_dish` accounts for 37 of 42 failures, and 23 of those are over-clarifications. Basic foods, branded cases, cafe cases, refusals, and most memory examples pass.

The local parser has a concept of `CONVENTIONAL_DISH_PRIORS`, but the current vocabulary is sparse relative to the golden mixed-dish set. When the parser sees a known generic ingredient inside a dish name, it can treat the request as an under-specified generic ingredient instead of as a conventional dish. `na_golden_043` is the clearest example: `куриный суп 400 г` becomes a chicken-detail clarification.

This is an implementation weakness, not a language weakness. The same pattern appears in English examples such as fish and chips, ramen, pad thai, burrito/wrap/sandwich-style meals, and pancakes.

### Root Cause 2 - Total Dish Weight Is Assigned To The Nearest Ingredient

Evidence: many numeric misses show the full gram amount applied to a single component:

- `fish and chips, about 450g` became `potato chips: 450 g`.
- `салат с помидорами и моцареллой 300 г` over-counted because the explicit total weight was assigned to mozzarella while other components still received defaults.
- oatmeal/milk/banana and other multi-component meals show the same pattern.

The relevant logic is in `app/tools/food_normalization.py`: `_quantity_for_mention` gives the only quantity to the only mention, or with multiple mentions assigns the nearest quantity if it is within 32 characters. This is simple and useful for single foods, but it is not a valid model for total-weight mixed dishes.

The calculator then correctly sums what it receives. The arithmetic is not the problem; the parsed ingredient weights are.

### Root Cause 3 - Offline Local Profiles Are Good Enough For Basic Items But Thin For Composite Foods

Evidence: basic foods are 22/22 and branded/cafe are 9/9 combined, but mixed dishes are 12/49. The deterministic offline eval disables live providers, so retrieval is mostly local fallback behavior. This is expected for a low-cost eval, but it means composite dish quality depends heavily on the local vocabulary and fallback profiles.

The local tables have improved enough to pass many high-value cases, including Russian basics, cola, water, branded/cafe examples, and memory follow-ups. The remaining gap is not provider availability; it is deterministic composition knowledge for common dishes.

### Root Cause 4 - The Critic Cannot Catch Semantic Food-Linking Or Portion-Allocation Errors

The critic is intentionally bounded. It accepts clarifications/refusals, checks missing totals, zero-calorie estimates, too-wide ranges, inverted ranges, and answer consistency with deterministic totals. This is the right safety shape, but it means wrong candidate identity or wrong portion allocation can pass if the final answer matches the deterministic totals.

`na_golden_076` is the representative example. The critic has no reason to reject `2410 kcal` if the calculator totals and answer text agree. The fix should be upstream in parsing/linking/portioning, not in a free-form critic rewrite.

### Root Cause 5 - The Embedding Linker Is Not Ready To Become Primary

The new shadow linker is useful, but at threshold `0.62` it still disagrees on 14 of 121 rows. Some disagreements are beneficial-looking, but others are clearly risky, for example mapping Russian blini with sour cream to `borscht with sour cream`.

This supports keeping the linker in shadow mode while using its disagreements to improve the deterministic vocabulary and alias data.

## Step 5 - Ranked Next Improvements

### 1. Add Data-Driven Mixed-Dish Templates For Common Dishes

Problem addressed: 23 over-clarification failures and a large share of the 37 mixed-dish failures.

Proposal: extend the YAML vocabulary with dish-level aliases and fallback dish profiles for common mixed dishes in the golden set and likely real usage: chicken soup, syrniki, blini with sour cream, buckwheat with chicken, shakshuka, sandwiches/wraps/burritos/shawarma, lasagna, sushi set, ramen, pho, pad thai, fried rice, falafel wrap, kebab plate, risotto, nuggets, pancakes, fish and chips, steak with fries, lentil soup, oatmeal bowls, muesli/yogurt bowls, salads with cheese, scrambled eggs with toast.

Expected impact: directly targets at least 23/42 failures, and likely improves part of the 17 numeric failures because dish-level profiles avoid component misallocation.

Effort: medium. Most work is data curation plus tests.

Risk: low to medium if implemented as deterministic data, not LLM behavior. The main risk is over-broad aliases accidentally matching ordinary ingredient mentions. Mitigate with explicit aliases and golden shadow tests.

Why this is robust: it keeps the controlled graph, schema outputs, and deterministic calculator. It adds knowledge where the eval proves knowledge is missing.

### 2. Add Total-Portion Allocation For Multi-Ingredient Meals

Problem addressed: numeric failures caused by assigning whole dish grams to one ingredient, especially `na_golden_076`, `na_golden_081`, `na_golden_087`, and similar cases.

Proposal: when a quantity phrase describes a whole dish/portion rather than a nearby ingredient, allocate the total weight across ingredients using a dish template or simple deterministic fractions. Do not assign the full total to one component and then add default portions for other components. Add diagnostics that say whether a quantity was interpreted as item weight, component weight, or total dish weight.

Expected impact: targets most of the 17 numeric failures. Combined with dish templates, this addresses the dominant mixed-dish numeric gap.

Effort: medium.

Risk: medium. Portion allocation can introduce regressions in simple multi-item requests where the user really means one component. Mitigate with conservative triggers and tests for existing passing examples.

Why this is robust: it fixes a concrete deterministic bug in representation. It does not ask the LLM or critic to invent numbers.

### 3. Calibrate A Few Local Packaged/Simple Profiles

Problem addressed: 3 packaged numeric failures: peanut butter, mozzarella, hummus.

Proposal: review local fallback profiles and acceptable eval ranges against a documented source. Adjust either the local profiles or the eval ranges where the dataset is too strict. `na_golden_030` is only 2 kcal under the acceptable minimum after rounding, so it may be an evaluator tolerance/range issue rather than a system issue.

Expected impact: up to 3/42 failures.

Effort: low.

Risk: low if sources are documented and changes are narrow.

Why this is robust: these are ordinary lookup/profile calibration issues, not architecture changes.

### 4. Improve Missing-Image Clarification Copy

Problem addressed: 1 conversation failure where behavior is correct but wording misses expected photo/description terms.

Proposal: when text references a photo but no image is attached, ask for the image or a text description explicitly in the localized clarification.

Expected impact: 1/42 failures.

Effort: low.

Risk: low.

Why this is robust: it improves user experience and test clarity without changing estimation logic.

### 5. Add Failure-Cluster Reporting To The Eval Runner

Problem addressed: manual analysis is currently needed to quantify failures by category, behavior, language, issue classification, and numeric failure type.

Proposal: extend `app.evals.run_golden_eval` or add a companion script that writes a small cluster summary and per-case CSV/JSON. It should include expected behavior, actual behavior, failed checks, parsed nutrients, category, language, tags, and issue classification.

Expected impact: does not directly improve pass rate, but makes future changes safer and faster to judge.

Effort: low to medium.

Risk: low.

Why this is robust: it improves the regression loop without touching production behavior.

### 6. Keep The Embedding Linker In Shadow Mode For Now

Problem addressed: typo/alias coverage and future vocabulary discovery.

Proposal: continue using the embedding linker as a shadow diagnostic. Do not enable it as primary until disagreements are reviewed and either fixed or allowed by tests. The current `88.43%` agreement rate is useful but not high enough for production routing.

Expected impact: speculative. It may help aliases and typos, but current disagreements include unsafe mappings.

Effort: medium if promoted safely.

Risk: medium to high if enabled too early.

Why this is robust: the current best use is as a vocabulary-improvement signal, not as a primary decision-maker.

## Non-Recommendations

- Do not replace the controlled LangGraph with an unconstrained agent loop. The failures are deterministic parsing/portioning gaps, not a need for broader autonomy.
- Do not move macro arithmetic into the LLM. The deterministic calculator is working as intended; wrong inputs are the issue.
- Do not add a vector database for this problem. The eval evidence points to small, explicit food/dish knowledge and portion allocation, not semantic document retrieval.
- Do not change production behavior solely to maximize this golden score. `na_golden_098` shows a real policy tension: estimate-first behavior may be better UX even when a dataset expects clarification.

## Bottom Line

The current service is stable compared with the latest stored baseline and much better than the first committed golden baseline. The main weakness is now narrow and actionable: deterministic mixed-dish understanding.

The best next move is not a larger model loop. It is a data-driven mixed-dish layer plus total-portion allocation, backed by the existing golden evals and the shadow linker report. That targets roughly 40 of 42 current failures while respecting the project guardrails: controlled graph, schema-validated structured data, deterministic retrieval/calculation, and bounded critic behavior.
