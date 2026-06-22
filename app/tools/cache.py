import hashlib
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


class JsonFileCache:
    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def key_digest(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _path_for_key(self, key: str) -> Path:
        digest = self.key_digest(key)
        return self.cache_dir / f"{digest}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path_for_key(key)
        with self._lock:
            if not path.exists():
                LOGGER.debug("Nutrition cache hit=false key_digest=%s", self.key_digest(key))
                return None
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                LOGGER.debug("Nutrition cache hit=true key_digest=%s", self.key_digest(key))
                return value
            except (OSError, json.JSONDecodeError):
                LOGGER.warning("Nutrition cache unreadable key_digest=%s", self.key_digest(key))
                return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        path = self._path_for_key(key)
        payload = json.dumps(value, ensure_ascii=False, indent=2)
        with self._lock:
            file_descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=self.cache_dir,
                text=True,
            )
            try:
                with os.fdopen(file_descriptor, "w", encoding="utf-8") as temp_file:
                    temp_file.write(payload)
                    temp_file.flush()
                    os.fsync(temp_file.fileno())
                os.replace(temp_name, path)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
        LOGGER.debug("Nutrition cache write key_digest=%s", self.key_digest(key))
