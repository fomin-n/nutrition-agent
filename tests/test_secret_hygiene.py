import subprocess
from pathlib import Path


def test_gitignore_covers_secret_and_runtime_files() -> None:
    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    for pattern in [".env", "*.log", "*.sqlite3", "*.db", ".venv/", "__pycache__/", "temp_images/", ".cache/"]:
        assert pattern in gitignore
    assert "!reports/eval/milestones/**" in gitignore
    assert "reports/eval/milestones/**/logs/**" in gitignore
    assert "!reports/eval/official/**" in gitignore
    assert "reports/eval/official/**/logs/**" in gitignore


def test_no_secret_files_tracked() -> None:
    tracked = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
    forbidden = {".env", "id_rsa", "id_ed25519"}
    assert not forbidden.intersection(tracked)
    assert not any(path.endswith(".log") for path in tracked)
    assert not any("/logs/" in path for path in tracked if path.startswith("reports/eval/milestones/"))
    assert not any("/logs/" in path for path in tracked if path.startswith("reports/eval/official/"))
