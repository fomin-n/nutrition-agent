import hashlib
import json
from pathlib import Path
from typing import Any


class JsonFileCache:
    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path_for_key(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path_for_key(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        path = self._path_for_key(key)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

