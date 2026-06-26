# Observability And Phoenix Runbook

The project includes optional Arize Phoenix tracing for LangChain, LangGraph, OpenAI, and nutrition-provider spans. Tracing is disabled by default and the bot continues normally if Phoenix is unavailable.

## Localhost Phoenix

Start Phoenix:

```bash
./scripts/phoenix.sh start
```

Useful commands:

```bash
./scripts/phoenix.sh status
./scripts/phoenix.sh logs
./scripts/phoenix.sh stop
```

The Compose file is [deploy/phoenix/docker-compose.yml](../deploy/phoenix/docker-compose.yml). It uses a named Docker volume, `nutrition_agent_phoenix_data`, and binds Phoenix only to localhost:

- `127.0.0.1:6006` for the UI and OTLP HTTP collector.
- `127.0.0.1:4317` for the OTLP gRPC collector.

Access a remote Phoenix UI through an SSH tunnel:

```bash
ssh -L 6006:127.0.0.1:6006 <user>@<server-ip>
```

Then open:

```text
http://localhost:6006
```

## Bot Configuration

Enable tracing in the bot environment:

```bash
ENABLE_PHOENIX_TRACING=true
PHOENIX_PROJECT_NAME=nutrition-agent
PHOENIX_COLLECTOR_ENDPOINT=http://127.0.0.1:6006/v1/traces
```

If the app later runs in Docker Compose on the same network as Phoenix, use:

```bash
PHOENIX_COLLECTOR_ENDPOINT=http://phoenix:6006/v1/traces
```

## Trace Shape

Each processed request creates a `nutrition_agent.request` root span. Existing LangGraph, LangChain, OpenAI, and nutrition-provider spans remain children of that request span.

Phoenix uses:

- `user.id` for the Telegram user ID.
- `session.id` for the Telegram chat ID.
- `request_id` for the app-generated request UUID.

Additional request metadata may include:

- `telegram.update.id`
- `telegram.user.id`
- `telegram.user.username`
- `telegram.user.first_name`
- `telegram.user.last_name`
- `telegram.user.display_name`
- `telegram.user.language_code`
- `telegram.user.is_bot`
- `telegram.chat.id`
- `telegram.chat.type`
- `telegram.chat.title`
- `telegram.chat.username`
- `telegram.chat.is_forum`
- `telegram.conversation.id`
- `telegram.message.id`
- `telegram.message.thread_id`
- `telegram.message.date`
- `telegram.message.media_group_id`
- `telegram.message.is_topic_message`
- `source`
- `request_type`
- `request_language`
- `app_version`
- `graph_version`
- configured model names
- critic configuration

Optional Telegram fields are omitted when unavailable.

## Privacy And Logging

Phoenix metadata can include Telegram names and usernames because those are useful for controlled user-level investigation. Keep Phoenix bound to localhost and restrict SSH/UI access.

Do not add the following to trace metadata or logs:

- message text or captions;
- complete Telegram updates;
- authorization keys;
- API keys;
- bot tokens;
- FatSecret client secrets or access tokens;
- Authorization headers;
- raw provider responses.

Application logs include OpenTelemetry `trace_id` and `span_id` values plus request/user/chat/message numeric IDs where relevant. They should not include Telegram names, message contents, credentials, or raw provider payloads.

## Smoke Check

1. Start Phoenix with `./scripts/phoenix.sh start`.
2. Open the UI through the SSH tunnel if Phoenix is remote.
3. Set `ENABLE_PHOENIX_TRACING=true` and restart the bot.
4. Send one meal request.
5. Confirm a `nutrition_agent.request` trace appears under the `nutrition-agent` project.
6. Confirm the trace has the expected `user.id`, `session.id`, request ID, and available `telegram.*` metadata.
7. Disable tracing and restart the bot.
8. Confirm the bot still answers normally.
