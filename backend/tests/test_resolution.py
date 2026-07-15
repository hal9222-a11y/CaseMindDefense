"""Entity resolution: the same person written in Russian, English and Hebrew
must resolve to one identity — and different people must NOT."""
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services.resolution_service import (
    _diminutive_stem,
    _same_person_score,
    hebrew_key,
)


def test_hebrew_key_folds_scripts_together():
    # the flagship case: Рина (ru) / Rina (en) / רינה (he) — one key
    assert hebrew_key("Рина") == hebrew_key("רינה") == hebrew_key("Rina")
    assert hebrew_key("Юлия") == hebrew_key("יוליה")


def test_hebrew_key_keeps_different_people_apart():
    assert hebrew_key("Рина") != hebrew_key("Алина")
    assert hebrew_key("Рина") != hebrew_key("דוד")


def test_diminutives():
    assert _diminutive_stem("Риночка") == "рин"
    assert _diminutive_stem("Юлечка") == "юл"
    assert _diminutive_stem("Ка") is None  # stem too short to mean anything


def test_ocr_lookalike_junk_is_rejected():
    # IPA chars that LOOK Cyrillic (bad OCR) must not enter resolution at all
    from app.services.resolution_service import _VALID_NAME_RE

    assert not _VALID_NAME_RE.match("Эɥɱɢɤ")
    assert not _VALID_NAME_RE.match("Наɬаɲ")
    assert _VALID_NAME_RE.match("Наташа")
    assert _VALID_NAME_RE.match("דוד לוי")
    assert _VALID_NAME_RE.match("Jean-Marc O'Neil")


def test_same_person_score_tiers():
    # cross-script: strong suggestion, but NEVER auto-merge strength — Hebrew
    # carries no vowels, so דנה could be Дана or Даня
    exact = _same_person_score("Рина", "רינה")
    assert exact and 0.85 <= exact[0] < 0.9

    # same script, same vowels: auto-merge strength
    same = _same_person_score("Rina", "Рина")
    assert same and same[0] >= 0.9

    dim = _same_person_score("Риночка", "Рина")
    assert dim and dim[0] >= 0.8

    # same consonants but different vowels = different women — review tier only
    vowels = _same_person_score("Алина", "Элина")
    assert vowels is None or vowels[0] < 0.85
    diana = _same_person_score("Дина", "Диана")
    assert diana is None or diana[0] < 0.85

    assert _same_person_score("Рина", "Алина") is None
    assert _same_person_score("דוד", "יוסי") is None
    # identical strings are one mention, not a merge
    assert _same_person_score("Рина", "Рина") is None


def test_end_to_end_resolution_via_api():
    """Index a chat mentioning one person in three scripts, resolve, and check
    the cluster lands on one Person with the other forms as aliases."""
    with TestClient(app) as client:
        case = client.post("/cases", json={"name": f"res_{uuid.uuid4().hex[:8]}"}).json()
        case_id = case["id"]

        import tempfile
        from pathlib import Path

        # entity extraction dedupes within a chunk, so MIN_MENTIONS=2 needs the
        # names in TWO documents — which is also the real scenario: the same
        # person across a Hebrew memo and a Russian chat
        bodies = [
            "פגישה עם רינה ועם דוד בתל אביב. רינה הגיעה מאוחר.",
            "Встреча: Рина приехала вовремя. Рина и Давид говорили долго.",
        ]
        from app.db import get_engine
        from app.services.evidence_service import index_evidence
        from sqlmodel import Session

        for i, body in enumerate(bodies):
            p = Path(tempfile.mktemp(suffix=f"_{i}_{uuid.uuid4().hex[:6]}.txt"))
            # both scripts in each file, so every form is seen in 2 chunks
            p.write_text(bodies[0] + "\n" + bodies[1] + f"\n({i})", encoding="utf-8")
            ev = client.post(
                "/evidence/import-file", json={"path": str(p), "case_id": case_id}
            ).json()
            # index synchronously so entities exist (the API defers to background)
            with Session(get_engine()) as session:
                index_evidence(session, ev["id"])

        suggestions = client.get(f"/persons/suggest-identities?case_id={case_id}").json()
        rina = next(
            (s for s in suggestions
             if any("רינה" in m["name"] for m in s["members"])
             and any(m["name"] == "Рина" for m in s["members"])),
            None,
        )
        assert rina is not None, f"no cross-script cluster found in {suggestions}"
        # cross-script clusters are strong suggestions but below auto-accept —
        # merging רינה with Рина is the user's call; accept it via /resolve
        assert 0.85 <= rina["confidence"] < 0.9
        applied = client.post(
            "/persons/resolve",
            json={
                "case_id": case_id,
                "canonical": rina["canonical"],
                "aliases": [
                    m["name"] for m in rina["members"] if m["name"] != rina["canonical"]
                ],
            },
        ).json()
        assert applied["aliases_added"], applied

        persons = client.get(f"/persons?case_id={case_id}").json()
        rina_person = next(
            p for p in persons if "רינה" in p["name"] or p["name"] == "Рина"
        )
        alias_values = {ln["value"] for ln in rina_person["links"] if ln["kind"] == "alias"}
        all_forms = {rina_person["name"]} | alias_values
        assert "Рина" in all_forms and any("רינה" in f for f in all_forms)

        # the knowledge graph folds both spellings into ONE person node
        graph = client.get(f"/persons/knowledge-graph?case_id={case_id}").json()
        rina_nodes = [
            n for n in graph["nodes"]
            if n["type"] == "person" and (
                "רינה" in n["label"] or n["label"] == "Рина"
                or any("רינה" in a or a == "Рина" for a in n.get("aliases", []))
            )
        ]
        assert len(rina_nodes) == 1 and rina_nodes[0].get("resolved"), (
            f"expected one resolved node, got {rina_nodes}"
        )

        client.delete(f"/cases/{case_id}")
