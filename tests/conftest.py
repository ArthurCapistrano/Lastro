from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LASTRO_STORAGE_PATH", str(tmp_path / "storage"))
