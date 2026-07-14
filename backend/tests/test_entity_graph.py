import uuid

from fastapi.testclient import TestClient

from app.main import app


def _import(client, tmp_path, text: str, case_id: int) -> int:
    marker = uuid.uuid4().hex
    p = tmp_path / f"chat_{marker}.txt"
    p.write_text(f"{text}\nref {marker}", encoding="utf-8")
    r = client.post("/evidence/import-file", json={"path": str(p), "case_id": case_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_graph_excludes_russian_pronouns(tmp_path):
    # the graph was drawing Она/Это/Нет as if they were people
    with TestClient(app) as client:
        case = client.post("/cases", json={"name": f"g_{uuid.uuid4().hex}"}).json()
        _import(
            client, tmp_path,
            "Она сказала что Марина видела Настю. Это правда. Нет, Марина ушла с Настей.",
            case["id"],
        )
        graph = client.get(
            "/entities/graph", params={"case_id": case["id"], "min_edge_weight": 1}
        ).json()
        names = {n["entity"] for n in graph["nodes"]}
        # real names survive. NOTE: Russian declines them (Настя/Настю/Настей),
        # so the same person can still appear as several nodes — that needs
        # lemmatisation, which is not done here.
        assert "Марина" in names
        assert any(n.startswith("Наст") for n in names)
        # the pronouns/particles that used to dominate the graph are gone
        assert not (names & {"Она", "Это", "Нет"})


def test_edges_are_capped_per_node_so_the_graph_is_not_a_hairball(tmp_path):
    # every name in one passage -> every pair co-occurs. Without a per-node cap
    # this is a complete graph, which shows nothing.
    with TestClient(app) as client:
        case = client.post("/cases", json={"name": f"g_{uuid.uuid4().hex}"}).json()
        _import(
            client, tmp_path,
            "Марина Настя Люда Света Наташа Алиса Костя Маша встретились вместе.",
            case["id"],
        )
        params = {"case_id": case["id"], "min_edge_weight": 1, "max_nodes": 8}
        capped = client.get(
            "/entities/graph", params={**params, "max_edges_per_node": 2}
        ).json()
        wide = client.get(
            "/entities/graph", params={**params, "max_edges_per_node": 10}
        ).json()

        nodes = len(capped["nodes"])
        complete = nodes * (nodes - 1) / 2
        assert len(wide["edges"]) > len(capped["edges"])
        assert len(capped["edges"]) < complete  # not a hairball


def test_only_people_hides_phones_and_plates(tmp_path):
    with TestClient(app) as client:
        case = client.post("/cases", json={"name": f"g_{uuid.uuid4().hex}"}).json()
        _import(client, tmp_path, "Марина позвонила Насте: 052-3545256.", case["id"])
        people = client.get(
            "/entities/graph", params={"case_id": case["id"], "only_people": True}
        ).json()
        assert not any(n["type"] == "phone" for n in people["nodes"])

        everything = client.get(
            "/entities/graph", params={"case_id": case["id"], "only_people": False}
        ).json()
        assert any(n["type"] == "phone" for n in everything["nodes"])
