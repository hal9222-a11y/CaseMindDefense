"""Cross-phone identity unification: the same human saved as different names
in different phones' contact books shares a phone number — suggest the join,
and merging folds everything into one person without losing links."""
import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import get_engine
from app.main import app
from app.models.evidence import Person, PersonLink


def _setup_case(client):
    case = client.post("/cases", json={"name": f"uni_{uuid.uuid4().hex[:8]}"}).json()
    return case["id"]


def _person(session, case_id, name, phones=(), desc=""):
    p = Person(case_id=case_id, name=name, description=desc)
    session.add(p)
    session.commit()
    session.refresh(p)
    for phone in phones:
        session.add(PersonLink(person_id=p.id, kind="phone", value=phone))
    session.commit()
    return p


def test_shared_phone_suggests_unification():
    with TestClient(app) as client:
        case_id = _setup_case(client)
        with Session(get_engine()) as session:
            _person(session, case_id, "Малой", phones=("972545642339",))
            _person(session, case_id, "אמיר גורי", phones=("054-564-2339",), desc="הנאשם")
            _person(session, case_id, "Юля", phones=("972528772478",))

        suggestions = client.get(f"/persons/suggest-phone-identities?case_id={case_id}").json()
        assert len(suggestions) == 1
        names = {m["name"] for m in suggestions[0]["members"]}
        assert names == {"Малой", "אמיר גורי"}  # different formats, same digits
        assert suggestions[0]["confidence"] == 0.9


def test_merge_folds_links_and_relations():
    with TestClient(app) as client:
        case_id = _setup_case(client)
        with Session(get_engine()) as session:
            canon = _person(session, case_id, "אמיר גורי", phones=("0545642339",), desc="הנאשם")
            dup = _person(session, case_id, "Малой", phones=("972545642339", "0521111111"), desc="כינוי מהסמסונג")
            witness = _person(session, case_id, "עד ראייה")
            # the witness has a relation pointing at the duplicate
            session.add(PersonLink(person_id=witness.id, kind="relation", related_person_id=dup.id, value="חבר של"))
            session.commit()
            canon_id, dup_id, witness_id = canon.id, dup.id, witness.id

        r = client.post("/persons/merge", json={"case_id": case_id, "canonical_id": canon_id, "merge_ids": [dup_id]}).json()
        assert r["merged"] == ["Малой"]

        with Session(get_engine()) as session:
            assert session.get(Person, dup_id) is None  # folded away
            links = session.exec(select(PersonLink).where(PersonLink.person_id == canon_id)).all()
            by_kind = {}
            for l in links:
                by_kind.setdefault(l.kind, []).append(l.value)
            assert "Малой" in by_kind["alias"]                 # name preserved as alias
            assert "0521111111" in by_kind["phone"]            # extra phone moved over
            # the witness's relation now points at the canonical person
            rel = session.exec(select(PersonLink).where(PersonLink.person_id == witness_id, PersonLink.kind == "relation")).one()
            assert rel.related_person_id == canon_id
            canonical = session.get(Person, canon_id)
            assert "כינוי מהסמסונג" in canonical.description

        # after the merge there is nothing left to suggest
        assert client.get(f"/persons/suggest-phone-identities?case_id={case_id}").json() == []


def test_merge_rejects_cross_case():
    with TestClient(app) as client:
        case_a, case_b = _setup_case(client), _setup_case(client)
        with Session(get_engine()) as session:
            pa = _person(session, case_a, "איש א")
            pb = _person(session, case_b, "איש ב")
            pa_id, pb_id = pa.id, pb.id
        r = client.post("/persons/merge", json={"case_id": case_a, "canonical_id": pa_id, "merge_ids": [pb_id]})
        assert r.status_code == 404
