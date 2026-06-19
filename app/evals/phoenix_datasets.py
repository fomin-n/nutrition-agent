import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from app.evals.golden import DEFAULT_GOLDEN_DATASET, GoldenExample, load_golden_examples


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or update a Phoenix golden dataset.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_GOLDEN_DATASET)
    parser.add_argument("--name", required=True)
    parser.add_argument("--description", default="NutritionAgent deterministic golden evaluation cases.")
    parser.add_argument("--split")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--base-url", default=_default_base_url())
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    try:
        examples = load_golden_examples(args.dataset, split=args.split, tags=args.tag)
        if not examples:
            raise ValueError("No examples matched the requested filters")
        result = upload_golden_dataset(
            examples,
            name=args.name,
            description=args.description,
            base_url=args.base_url,
            api_key=os.getenv("PHOENIX_API_KEY"),
            timeout=args.timeout,
        )
    except (OSError, ValueError, httpx.HTTPError) as exc:
        print(
            json.dumps(
                {
                    "uploaded": False,
                    "error": str(exc),
                    "base_url": args.base_url,
                    "hint": "Start Phoenix with ./scripts/phoenix.sh start or set PHOENIX_BASE_URL.",
                },
                indent=2,
            )
        )
        return 1

    print(json.dumps(result, indent=2))
    return 0


def upload_golden_dataset(
    examples: Sequence[GoldenExample],
    *,
    name: str,
    description: str,
    base_url: str,
    api_key: str | None = None,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    owns_client = client is None
    if client is None:
        client = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout)
    try:
        response = client.get("/v1/datasets", params={"name": name, "limit": 100})
        response.raise_for_status()
        existing = any(item.get("name") == name for item in response.json().get("data", []))
        payload = _upload_payload(
            examples,
            name=name,
            description=description,
            action="update" if existing else "create",
        )
        response = client.post("/v1/datasets/upload", params={"sync": "true"}, json=payload)
        if response.status_code == 409 and not existing:
            payload["action"] = "update"
            response = client.post("/v1/datasets/upload", params={"sync": "true"}, json=payload)
        response.raise_for_status()
        data = response.json().get("data", {})
        return {
            "uploaded": True,
            "name": name,
            "action": payload["action"],
            "example_count": len(examples),
            "dataset_id": data.get("dataset_id"),
            "version_id": data.get("version_id"),
            "num_created_examples": data.get("num_created_examples"),
            "num_updated_examples": data.get("num_updated_examples"),
            "num_deleted_examples": data.get("num_deleted_examples"),
        }
    finally:
        if owns_client:
            client.close()


def _upload_payload(
    examples: Sequence[GoldenExample],
    *,
    name: str,
    description: str,
    action: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "action": action,
        "inputs": [example.input.model_dump(mode="json") for example in examples],
        "outputs": [example.output.model_dump(mode="json") for example in examples],
        "metadata": [example.metadata.model_dump(mode="json") for example in examples],
        "splits": [example.splits for example in examples],
        "example_ids": [example.metadata.id for example in examples],
    }


def _default_base_url() -> str:
    if base_url := os.getenv("PHOENIX_BASE_URL"):
        return base_url
    collector = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:6006")
    return collector.removesuffix("/v1/traces").rstrip("/")


if __name__ == "__main__":
    raise SystemExit(main())
