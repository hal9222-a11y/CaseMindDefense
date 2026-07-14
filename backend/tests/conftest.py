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

    reset_engine_cache()

    yield

    reset_engine_cache()