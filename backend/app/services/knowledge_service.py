"""Knowledge graph: the case as one network of RESOLVED identities, phones,
locations and organizations — not raw strings. Before resolution, Рина, Rina
and רינה are three nodes and the picture lies about who is central; after,
mentions of every written form fold into one person node.

Every edge carries a citation (evidence_id + chunk) — in an evidence tool a
connection you cannot open and read is worth nothing."""
from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations

from sqlmodel import Session, select

from app.models.evidence import Evidence, ExtractedEntity, Person, PersonLink
from app.services.entity_service import is_noise_name

PERSON_LABELS = {"person", "name"}
THING_LABELS = {"phone": "phone", "location": "location", "organization": "organization",
                "vehicle_plate": "vehicle", "israeli_id": "id"}
MIN_THING_MENTIONS = 2

EDGE_LABELS = {
    ("person", "person"): "הוזכרו יחד",
    ("person", "phone"): "טלפון בהקשר",
    ("person", "location"): "מקום בהקשר",
    ("person", "organization"): "ארגון בהקשר",
    ("person", "vehicle"): "רכב בהקשר",
    ("person", "id"): "ת\"ז בהקשר",
}


def _label_for(type_a: str, type_b: str) -> str:
    return EDGE_LABELS.get((type_a, type_b)) or EDGE_LABELS.get((type_b, type_a)) or "קשר"


def knowledge_graph(
    session: Session,
    case_id: int,
    max_person_nodes: int = 25,
    max_thing_nodes: int = 20,
    min_edge_weight: int = 2,
    max_edges_per_node: int = 4,
) -> dict:
    persons = session.exec(select(Person).where(Person.case_id == case_id)).all()
    person_ids = [p.id for p in persons]

    # every accepted written form -> person node
    form_to_person: dict[str, int] = {" ".join(p.name.split()): p.id for p in persons}
    aliases_of: dict[int, list[str]] = defaultdict(list)
    phone_links: list[PersonLink] = []
    relation_links: list[PersonLink] = []
    if person_ids:
        for ln in session.exec(
            select(PersonLink).where(PersonLink.person_id.in_(person_ids))
        ).all():
            if ln.kind == "alias":
                form_to_person[" ".join((ln.value or "").split())] = ln.person_id
                aliases_of[ln.person_id].append(ln.value)
            elif ln.kind == "phone":
                phone_links.append(ln)
            elif ln.kind == "relation":
                relation_links.append(ln)

    rows = session.exec(
        select(
            ExtractedEntity.text, ExtractedEntity.label,
            ExtractedEntity.evidence_id, ExtractedEntity.chunk_index,
        ).where(
            ExtractedEntity.evidence_id.in_(
                select(Evidence.id).where(Evidence.case_id == case_id)
            )
        )
    ).all()

    # fold mentions into nodes: resolved persons by any written form; unresolved
    # frequent names stay person-typed nodes of their own; phones/places/orgs
    # become thing nodes
    person_mentions: Counter[int] = Counter()          # person_id -> mentions
    loose_names: Counter[str] = Counter()              # unresolved name -> count
    things: Counter[tuple[str, str]] = Counter()       # (text, type) -> count
    by_passage: dict[tuple[int, int], set] = defaultdict(set)  # passage -> node keys

    for text, label, evidence_id, chunk_index in rows:
        name = " ".join((text or "").split())
        if not name or is_noise_name(name):
            continue
        passage = (evidence_id, chunk_index)
        if label in PERSON_LABELS:
            pid = form_to_person.get(name)
            if pid is not None:
                person_mentions[pid] += 1
                by_passage[passage].add(("person", pid))
            elif len(name) >= 3:
                loose_names[name] += 1
                by_passage[passage].add(("loose", name))
        elif label in THING_LABELS:
            key = (name, THING_LABELS[label])
            things[key] += 1
            by_passage[passage].add(("thing", key))

    # node selection
    top_persons = {pid for pid, _ in person_mentions.most_common(max_person_nodes)}
    # people the user created but who have no folded mentions still belong
    top_persons |= {p.id for p in persons if not p.in_evidence or person_mentions[p.id] == 0}
    remaining = max(0, max_person_nodes - len(top_persons))
    top_loose = {n for n, c in loose_names.most_common(remaining) if c >= MIN_THING_MENTIONS}
    top_things = {k for k, c in things.most_common(max_thing_nodes) if c >= MIN_THING_MENTIONS}

    def node_key_id(kind, key) -> str:
        if kind == "person":
            return f"p:{key}"
        if kind == "loose":
            return f"n:{key}"
        return f"t:{key[1]}:{key[0]}"

    nodes: list[dict] = []
    persons_by_id = {p.id: p for p in persons}
    for pid in top_persons:
        p = persons_by_id.get(pid)
        if p is None:
            continue
        nodes.append({
            "id": f"p:{pid}", "type": "person", "label": p.name,
            "aliases": aliases_of.get(pid, []), "mentions": person_mentions.get(pid, 0),
            "resolved": True,
        })
    for name in top_loose:
        nodes.append({
            "id": f"n:{name}", "type": "person", "label": name,
            "aliases": [], "mentions": loose_names[name], "resolved": False,
        })
    for (text, typ) in top_things:
        nodes.append({
            "id": f"t:{typ}:{text}", "type": typ, "label": text,
            "mentions": things[(text, typ)],
        })
    kept_ids = {n["id"] for n in nodes}
    node_type = {n["id"]: n["type"] for n in nodes}

    # co-occurrence edges (per passage, like entity_graph — see its docstring)
    edge_weight: Counter[tuple[str, str]] = Counter()
    edge_citation: dict[tuple[str, str], tuple[int, int]] = {}
    for passage, members in by_passage.items():
        ids = sorted(
            node_key_id(kind, key) for kind, key in members
            if node_key_id(kind, key) in kept_ids
        )
        for a, b in combinations(ids, 2):
            edge_weight[(a, b)] += 1
            edge_citation.setdefault((a, b), passage)

    # top-k pruning per node keeps the strongest links readable (same rationale
    # as entity_graph: near-complete graphs show nothing)
    strongest: dict[str, list] = defaultdict(list)
    for pair, weight in edge_weight.most_common():
        if weight < min_edge_weight:
            continue
        strongest[pair[0]].append((weight, pair))
        strongest[pair[1]].append((weight, pair))
    kept_pairs: set = set()
    for node_edges in strongest.values():
        for _w, pair in sorted(node_edges, reverse=True)[:max_edges_per_node]:
            kept_pairs.add(pair)

    edges: list[dict] = []
    for a, b in sorted(kept_pairs, key=lambda p: -edge_weight[p]):
        cit = edge_citation[(a, b)]
        edges.append({
            "a": a, "b": b, "weight": edge_weight[(a, b)],
            "label": _label_for(node_type[a], node_type[b]),
            "kind": "co_mention",
            "evidence_id": cit[0], "chunk_index": cit[1],
        })

    # explicit, user/AI-accepted facts override statistics: linked phones and
    # declared relations are drawn even when co-occurrence is thin
    for ln in phone_links:
        a, b = f"p:{ln.person_id}", f"t:phone:{ln.value}"
        if a in kept_ids:
            if b not in kept_ids:
                nodes.append({"id": b, "type": "phone", "label": ln.value, "mentions": 0})
                kept_ids.add(b)
            edges.append({
                "a": a, "b": b, "weight": 0, "label": "טלפון מקושר",
                "kind": "linked", "evidence_id": ln.evidence_id, "chunk_index": None,
                "confidence": ln.confidence,
            })
    for ln in relation_links:
        a, b = f"p:{ln.person_id}", f"p:{ln.related_person_id}"
        if a in kept_ids and b in kept_ids:
            edges.append({
                "a": a, "b": b, "weight": 0, "label": ln.value or "קשר",
                "kind": "relation", "evidence_id": None, "chunk_index": None,
            })

    return {"nodes": nodes, "edges": edges}
