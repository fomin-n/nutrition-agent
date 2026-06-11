#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${PHOENIX_COMPOSE_FILE:-deploy/phoenix/docker-compose.yml}"
COMMAND="${1:-status}"

case "$COMMAND" in
  start)
    docker compose -f "$COMPOSE_FILE" up -d
    ;;
  stop)
    docker compose -f "$COMPOSE_FILE" down
    ;;
  logs)
    docker compose -f "$COMPOSE_FILE" logs -f phoenix
    ;;
  status)
    docker compose -f "$COMPOSE_FILE" ps
    ;;
  pull)
    docker compose -f "$COMPOSE_FILE" pull
    ;;
  *)
    echo "Usage: $0 {start|stop|logs|status|pull}" >&2
    exit 2
    ;;
esac
