import os

import pytest

from app.db import reset_engine_cache


@pytest.fixture(scope="session", autouse=True)
def isolated_test_environment(tmp_path_factory):
    root = tmp_path_factory.mktemp("casemind_test")

    db = root / "test.db"
    evidence_store = root / "evidence_store"

    os.environ["CASEMIND_DATABASE_URL"] = f"sqlite:///{db}"
    os.environ["CASEMIND_EVIDENCE_STORE"] = str(evidence_store)
    # the background translator would otherwise run against the test DB and race
    # the assertions; tests drive translate_one() directly instead
    os.environ["CASEMIND_BACKGROUND_TRANSLATE"] = "0"
    # same for the startup resume thread: it leaks across TestClient instances,
    # holds _RESUME_LOCK between tests, and races assertions (three flaky tests);
    # tests call resume_pending_indexing() directly instead
    os.environ["CASEMIND_BACKGROUND_RESUME"] = "0"

    reset_engine_cache()

    yield

    reset_engine_cache()