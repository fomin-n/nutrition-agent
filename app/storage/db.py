from pathlib import Path


def ensure_storage_dir(path: str | Path) -> Path:
    storage_dir = Path(path)
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir

