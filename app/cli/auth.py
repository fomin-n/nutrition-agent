import argparse
import sys
from collections.abc import Sequence
from typing import Any

from app.auth.service import AuthConfigurationError, AuthService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage nutrition-agent Telegram access.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-key", help="Create a one-time access key.")
    create.add_argument("--label", help="Human-readable label for this key.")
    create.add_argument("--expires-at", help="Optional ISO-8601 UTC timestamp.")

    subparsers.add_parser("list-keys", help="List access keys without raw secrets.")

    revoke_key = subparsers.add_parser("revoke-key", help="Revoke an access key.")
    revoke_key.add_argument("key_id")

    subparsers.add_parser("list-users", help="List authorized Telegram users.")

    revoke_user = subparsers.add_parser("revoke-user", help="Revoke an authorized Telegram user.")
    revoke_user.add_argument("telegram_user_id", type=int)

    args = parser.parse_args(argv)
    try:
        service = AuthService.from_settings()
    except AuthConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.command == "create-key":
        created = service.create_key(label=args.label, expires_at=args.expires_at)
        print(f"key_id: {created.key_id}")
        print(f"label: {created.label or ''}")
        print(f"expires_at: {created.expires_at or ''}")
        print(f"access_key: {created.raw_key}")
        print("Store this access key now. It is shown exactly once and cannot be recovered later.")
        return 0

    if args.command == "list-keys":
        rows = service.list_keys()
        _print_table(
            ["id", "label", "created_at", "expires_at", "used_at", "used_by_user_id", "revoked_at"],
            rows,
        )
        return 0

    if args.command == "revoke-key":
        ok = service.revoke_key(args.key_id)
        print("revoked" if ok else "not_found")
        return 0 if ok else 1

    if args.command == "list-users":
        rows = service.list_users()
        _print_table(
            ["telegram_user_id", "username", "display_name", "authorized_at", "revoked_at"],
            rows,
        )
        return 0

    if args.command == "revoke-user":
        ok = service.revoke_user(args.telegram_user_id)
        print("revoked" if ok else "not_found")
        return 0 if ok else 1

    parser.print_help()
    return 2


def _print_table(headers: list[str], rows: Sequence[Any]) -> None:
    print("\t".join(headers))
    for row in rows:
        print("\t".join(str(row[header] or "") for header in headers))


if __name__ == "__main__":
    raise SystemExit(main())
