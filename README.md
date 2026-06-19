# nutrition-agent

`nutrition-agent` is an experimental agentic nutrition-estimation bot. It accepts a meal description and, optionally, a food photo through Telegram, then returns an approximate calorie and macronutrient range with explicit assumptions.

The project is designed as an engineering MVP: language and vision models help classify and structure uncertain meal input, while calorie and macro arithmetic is deterministic Python.

This is not a medical product and does not provide diagnosis, treatment plans, eating-disorder advice, or medical nutrition therapy.

## What It Solves

Meal logging is often too slow because users must manually search foods, estimate portions, and enter each ingredient. This project explores a controlled agent workflow that can turn natural meal descriptions or photos into a practical estimate:

1. A user sends a food description or photo to the Telegram bot.
2. The bot verifies that the sender is authorized.
3. The graph rejects off-topic, unsafe, or prompt-injection attempts.
4. The graph extracts ingredients and portion ranges.
5. Nutrition sources are retrieved for each ingredient.
6. A deterministic calculator computes calories, protein, fat, and carbs.
7. The response is sanity checked and returned with assumptions and confidence.

Example response shape:

```text
Estimated calories: 520-650 kcal
Protein: 35-45 g
Fat: 15-22 g
Carbs: 55-75 g
Main assumptions:
* cooked rice: 180-220 g
* cooked chicken breast: 120-160 g
* olive oil: 8-14 g
Confidence: medium
```

## Architecture

```mermaid
flowchart TD
    A["Telegram user input"] --> B["Access-key authorization gate"]
    B -->|Unauthorized| C["Minimal login message"]
    B -->|Authorized| D["Input moderation"]
    D --> E["Scope classifier"]
    E -->|Off-topic or unsafe| F["Refusal"]
    E -->|Food request| G["Coordinator / router"]
    G --> H["Text meal parser"]
    G --> I["Image meal recognizer"]
    G --> J["Packaging / OCR recognizer"]
    H --> K["Nutrition retrieval"]
    I --> K
    J --> K
    K --> L["Deterministic macro calculator"]
    L --> M["Answer synthesizer"]
    M --> N["Critic / sanity checker"]
    N --> O["Output moderation"]
    O --> P["Telegram response"]
```

## Pipeline Stages

- **Telegram input** handles text messages and one photo with an optional caption.
- **Authorization gate** blocks unauthenticated users before any model call, image download, nutrition lookup, or graph execution.
- **Input moderation** applies conservative local checks and can use OpenAI moderation when configured.
- **Scope classifier** decides whether the request is food-related, off-topic, unsafe, or needs clarification. English and Russian meal requests are supported; image-only requests default to English responses.
- **Coordinator/router** sends the request to a text, image, combined image+text, or packaged-food branch.
- **Text meal parser** extracts ingredients and practical gram ranges from a written meal description.
- **Image meal recognizer** uses a vision-capable model to identify visible food and estimate portion ranges.
- **Packaging/OCR recognizer** supports a basic packaged-food branch for product names, labels, and future barcode/OCR work.
- **Nutrition retrieval** normalizes provider results into ranked candidates from USDA FoodData Central, FatSecret, Open Food Facts, and explicit local food/category fallbacks. Candidates must pass category and product-variant validation before reaching the deterministic calculator.
- **Deterministic macro calculator** computes calories, protein, fat, and carbs from ingredient gram ranges and nutrition data.
- **Answer synthesizer** formats the result with ranges, assumptions, warnings, and confidence.
- **Critic/sanity checker** catches missing detail, inconsistent ranges, and overly wide estimates before output.
- **Output moderation** prevents unsafe or out-of-scope final content.

## Memory

The bot has a lightweight memory layer in `app/memory/service.py`. It is intentionally SQLite-backed and deterministic; there is no vector database or unconstrained agent loop.

- Short-term memory is keyed by `(user_id, conversation_id)`, where Telegram uses the user ID and chat ID passed into `process_request`. This keeps users and separate chats isolated.
- Short-term memory stores recent user/assistant messages, a compact older-summary string, and one current unresolved nutrition task such as `chicken` with missing `cut`, `quantity`, or `preparation`.
- Follow-up answers are resolved before the graph runs. For example, after “How many calories are in chicken?” the bot stores the unresolved chicken task; “100 g, fried.” becomes “chicken, 100 g, fried” internally, so the bot only asks for the still-missing cut.
- Long-term memory stores only stable nutrition context extracted from user text: allergies, dietary preferences, measurement preferences, and recurring goals. It does not promote every message into long-term memory.
- Conversation compaction keeps the most recent 10 messages by default. When a conversation exceeds 16 messages, older messages are appended to a bounded plain-text summary, capped at 2000 characters by default.
- SQLite writes use short transactions with `BEGIN IMMEDIATE`, WAL mode, and composite keys, so concurrent requests cannot mix users or corrupt a conversation record.
- Previous assistant estimates are retained for conversation display/compaction but are excluded from parser evidence; only unresolved tasks, stable facts, the bounded summary, and recent user messages are supplied as context.

Memory configuration:

- `MEMORY_DB_PATH`: optional SQLite path. Defaults to `memory.sqlite3` next to `AUTH_DB_PATH`.
- `MEMORY_RECENT_MESSAGES`: recent short-term messages to retain, default `10`.
- `MEMORY_SUMMARIZE_AFTER_MESSAGES`: compaction threshold, default `16`.
- `MEMORY_SUMMARY_MAX_CHARS`: compact summary character cap, default `2000`.

## Model Map

Model names are configurable through environment variables so the project can move with API availability:

- `OPENAI_TEXT_MODEL`: structured scope classification and text meal parsing when LLM mode is enabled.
- `OPENAI_VISION_MODEL`: food-photo recognition and image+caption interpretation.
- `OPENAI_CRITIC_MODEL`: reserved for model-backed critic checks; the current MVP uses deterministic critic logic.
- Answer synthesis is deterministic in the current MVP; the graph does not ask the model to invent totals or perform arithmetic.
- User-facing estimates, clarifications, and refusals are localized for English and Russian text requests. If the user sends only an image, the default response language is English.

## Safety Design

- The graph is a controlled LangGraph state machine, not an unconstrained agent loop.
- LLM outputs that affect control flow are validated with Pydantic schemas.
- Untrusted user text, OCR-like text, image observations, and external data are treated as data, not instructions.
- Off-topic, hacking, prompt-extraction, unsafe diet, and medical-treatment requests are refused.
- Unauthorized Telegram users receive only a minimal login prompt and cannot trigger expensive work.
- Access keys are one-time by default. The application stores HMAC-SHA256 digests, not raw keys.
- Final answers pass a critic/sanity-check step and output moderation before delivery.

## Data Sources

- USDA FoodData Central lookup when `USDA_API_KEY` is configured. Generic ingredients prefer Foundation/SR Legacy data, and prepared dishes prefer FNDDS where relevant.
- FatSecret Platform API lookup when `FATSECRET_CLIENT_ID` and `FATSECRET_CLIENT_SECRET` are configured. Branded products and restaurant menu items prefer FatSecret first.
- Open Food Facts lookup remains available for packaged-food fallback.
- Local fallback nutrition table for common foods and explicit category profiles such as regular/zero-sugar cola and standard Snickers, Twix, and Bounty bars.

Provider outputs are normalized into a common candidate schema with a stable `source + source_id + serving_id` identity, serving metadata, per-100 g values when safely available, and deterministic ranking score components. Unknown single ingredients, branded products, and beverages never use the generic mixed-food fallback; the bot asks for a brand, serving, or label when no semantically valid candidate exists. The app does not persist FatSecret raw API responses or tokens.

Regular Coca-Cola aliases in English and Russian normalize to one branded sugary-soft-drink product. A can defaults to 330 ml, and volume is converted to calculator grams only for this recorded water-density beverage profile. Candidate validation rejects soft-drink records with implausible protein/fat or a regular/zero-sugar mismatch.

Common international packaged products use a small deterministic alias registry before provider lookup. Russian forms such as `Сникерс`, `Сникерсе`, `Твикс`, `Твиксе`, and `Баунти` map to canonical English product names and bounded provider-query expansions such as `Snickers bar`. Explicit package weights are used exactly; otherwise the documented standard product serving is assumed. If structured providers fail, a product-specific per-100 g profile is used instead of `generic_mixed_food`. Values may differ by market or variant, so unusual editions still require a label photo.

Retrieval diagnostics log the request UUID, canonical query, amount, provider queries, candidate identities, scores, validation reasons, selected identity, fallback path, and calculated totals. Raw user context is excluded by default. Set `NUTRITION_DIAGNOSTICS_INCLUDE_RAW=true` only during a controlled investigation; `NUTRITION_DIAGNOSTICS_MAX_PAYLOAD_CHARS` bounds and redacts that context.

See [docs/nutrition-retrieval.md](docs/nutrition-retrieval.md) for the audit, runtime call chain, provider priority, and known limitations.

External nutrition data can be incomplete or inconsistent, especially for packaged products. The app surfaces assumptions rather than claiming precision.

## Phoenix Observability

The project includes a minimal self-hosted Arize Phoenix setup for LangChain/LangGraph tracing. Phoenix is optional and disabled by default.

Start Phoenix on the server:

```bash
./scripts/phoenix.sh start
```

Phoenix stores SQLite-backed data in the Docker volume `nutrition_agent_phoenix_data` and binds only to localhost:

- `127.0.0.1:6006` for the UI and OTLP HTTP collector.
- `127.0.0.1:4317` for the OTLP gRPC collector.

Access the UI through an SSH tunnel:

```bash
ssh -L 6006:127.0.0.1:6006 <user>@<server-ip>
```

Then open:

```text
http://localhost:6006
```

Enable tracing for the bot by setting:

```bash
ENABLE_PHOENIX_TRACING=true
PHOENIX_PROJECT_NAME=nutrition-agent
PHOENIX_COLLECTOR_ENDPOINT=http://127.0.0.1:6006/v1/traces
```

If the app runs in Docker Compose on the same network as Phoenix, use `PHOENIX_COLLECTOR_ENDPOINT=http://phoenix:6006/v1/traces` instead. If Phoenix is disabled or unavailable, the app logs a warning and continues without tracing.

Useful commands:

```bash
./scripts/phoenix.sh status
./scripts/phoenix.sh logs
./scripts/phoenix.sh stop
```

Smoke check:

1. Start Phoenix.
2. Open the UI through the SSH tunnel.
3. Enable tracing and restart the bot.
4. Send one meal request.
5. Confirm a trace appears under the `nutrition-agent` project.
6. Disable tracing and confirm the bot still answers normally.

## Evaluation

Current checks include:

- Unit tests for calculator aggregation, fallback lookup, graph routing, refusal behavior, auth, and secret hygiene.
- A local adversarial eval suite for off-topic, prompt-injection, hacking, unsafe diet, and medical requests.
- Mock evaluation mode that can run without API keys.
- A tiny nutrition-quality eval using 3 rows derived from OpenIntro's public `fastfood` dataset.

Run the adversarial safety eval:

```bash
uv run python -m app.evals.run_eval --mock
```

Run the tiny nutrition eval:

```bash
uv run python -m app.evals.run_nutrition_eval --max-examples 3
```

The nutrition eval uses the OpenIntro `fastfood` dataset because it is public, small, downloadable as CSV without authentication, and includes calories plus protein, fat, and carbohydrate values. The tiny committed sample lives in `app/evals/fastfood_tiny_sample.jsonl`; the full dataset is not committed. OpenIntro describes the dataset as 515 fast-food items with nutrition fields such as calories, total fat, total carbs, and protein. OpenIntro's license page says most OpenIntro resources are released under Creative Commons BY-SA 3.0; see the dataset and license pages for attribution details:

- Dataset: https://www.openintro.org/data/index.php?data=fastfood
- CSV: https://www.openintro.org/data/csv/fastfood.csv
- License: https://www.openintro.org/license/

By default, the nutrition eval runs exactly 3 examples with `use_llm=False`, so it exercises the deterministic/local graph path and does not call OpenAI. Processing more than 3 examples requires `--allow-more-examples`; using LLM-backed graph paths requires both `--use-llm` and `--allow-paid-api`.

Metrics are intentionally simple: predicted calorie midpoint versus ground-truth calories, absolute error, percentage error, mean absolute calorie error, and macro errors for protein, fat, and carbs when present. Results are written to `reports/eval/` as timestamped JSON and Markdown files; generated result files are ignored by git.

This first nutrition eval is a smoke test, not a benchmark. Fast-food menu rows describe full prepared items, while the default no-LLM parser may map them to generic ingredients with assumed portions. Portion estimates are recorded for debugging but not scored because the dataset does not include serving weights.

Future evaluation targets:

- Nutrition5k for image meal evaluation.
- NutriBench for text meal evaluation.
- NutritionVerse-Real for real food image evaluation.

Large datasets are intentionally not downloaded by this repository.

## Known Limitations

- Portion estimation from images is approximate.
- Hidden oils, sauces, dressings, and mixed ingredients are difficult.
- Packaged-food data can be incomplete or user-contributed.
- The current packaging branch is basic and does not perform robust barcode scanning.
- The project is not medical advice and should not be used for medical nutrition therapy.

## Local Development

```bash
uv sync --extra dev
cp .env.example .env
uv run python -m app.bot.telegram_bot
```

Required environment variables:

- `OPENAI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `BOT_AUTH_SECRET`

Optional environment variables:

- `USDA_API_KEY`
- `FATSECRET_CLIENT_ID`
- `FATSECRET_CLIENT_SECRET`
- `ENABLE_USDA`
- `ENABLE_FATSECRET`
- `ENABLE_OPEN_FOOD_FACTS`
- `OPENAI_TEXT_MODEL`
- `OPENAI_VISION_MODEL`
- `OPENAI_CRITIC_MODEL`
- `OPENAI_MODERATION_ENABLED`
- `AUTH_DB_PATH`
- `MEMORY_DB_PATH`
- `MEMORY_RECENT_MESSAGES`
- `MEMORY_SUMMARIZE_AFTER_MESSAGES`
- `MEMORY_SUMMARY_MAX_CHARS`

Generate a local access key:

```bash
uv run python -m app.cli.auth create-key --label "demo-user"
```

Run checks:

```bash
uv run pytest
uv run ruff check .
uv run python -m app.evals.run_eval --mock
uv run python -m app.evals.run_retrieval_smoke
```

Live nutrition-provider tests are disabled by default. To run them intentionally:

```bash
RUN_LIVE_NUTRITION_TESTS=1 uv run pytest tests/test_live_nutrition_providers.py
uv run python -m app.evals.run_retrieval_smoke --live
```

## Deployment

Deployment is intentionally documented with placeholders only. Do not commit real server addresses, usernames, bot tokens, API keys, auth databases, logs, downloaded images, or environment files.

See [AGENTS.md](AGENTS.md) for contributor-oriented technical notes.
