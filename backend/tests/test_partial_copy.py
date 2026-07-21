"""A copy into the evidence store that dies midway (disk full, unplugged
drive) must not leave a truncated file that a later import would trust."""
import shutil
import tempfile
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.core.settings import get_settings
from app.services import evidence_service


def test_failed_copy_leaves_no_file_and_retry_succeeds(monkeypatch, tmp_path):
    src = tmp_path / "evidence.txt"
    src.write_text("wiretap transcript", encoding="utf-8")

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(get_settings(), "evidence_store_dir", tmp_path / "store")

    real_copy = shutil.copy2

    def dying_copy(a, b):
        Path(b).write_bytes(b"trunc")  # simulate a partial write...
        raise OSError(28, "No space left on device")  # ...then disk full

    monkeypatch.setattr(shutil, "copy2", dying_copy)
    with Session(engine) as session:
        with pytest.raises(OSError):
            evidence_service.register_evidence(session, str(src))

    store = tmp_path / "store"
    leftovers = list(store.glob("*")) if store.exists() else []
    assert leftovers == [], f"truncated file left in store: {leftovers}"

    # the retry (disk freed) must produce a correct, complete copy
    monkeypatch.setattr(shutil, "copy2", real_copy)
    with Session(engine) as session:
        ev = evidence_service.register_evidence(session, str(src))
        stored_path = ev.stored_path
    assert Path(stored_path).read_text(encoding="utf-8") == "wiretap transcript"
