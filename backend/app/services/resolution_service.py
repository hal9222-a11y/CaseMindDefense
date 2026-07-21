"""Entity resolution: the same human appears as Рина in a Russian chat, Rina
in a WhatsApp export and רינה in a court document — and until these are one
identity, every count, search and graph in the system is split three ways.

Matching is rule-based and offline (deterministic transliteration to a shared
Hebrew key + Russian diminutive stems + fuzzy ratio); the LLM is NOT in this
path, so resolution works with Ollama down and gives the same answer twice.
Nothing merges silently: suggestions carry a confidence, a reason and a
citation per name, and applying them writes ordinary Person/alias rows that
the user can see and delete."""
from __future__ import annotations

import difflib
import logging
from collections import defaultdict

from sqlmodel import Session, select

import re

from app.models.evidence import Evidence, ExtractedEntity, Person, PersonLink
from app.services.audit_service import log_event
from app.services.entity_service import is_noise_name

# a resolvable name is written in one of the case's three scripts. OCR of bad
# scans emits Cyrillic-LOOKALIKE letters (Эɥɱɢɤ — those are IPA characters);
# every unknown char transliterates to nothing, so junk names collapse onto
# identical short keys and merge into confident false clusters.
_VALID_NAME_RE = re.compile(r"^[֐-׿a-zA-Zа-яёА-ЯЁ'\- ]+$")

logger = logging.getLogger(__name__)

# a name must be seen at least this often to take part in resolution — one-off
# OCR garbage must not merge into a real person
MIN_MENTIONS = 2
FUZZY_MIN_RATIO = 0.85          # same bar person_service uses cross-script
AUTO_ACCEPT_CONFIDENCE = 0.9    # auto-resolve applies only at/above this

PERSON_LABELS = {"person", "name"}

# --- transliteration to a shared Hebrew comparison key ---------------------
# Practical name-transliteration conventions, not linguistics: mid-word
# a/e/э-type vowels drop (Наталья -> נטליה), final а/я become ה. Deviations are
# absorbed by the fuzzy ratio.
_RU_DIGRAPHS = {"ю": "יו", "я": "יא", "ё": "יו", "ж": "ז", "ч": "צ", "ш": "ש", "щ": "ש", "х": "ח", "ц": "צ"}
_RU_MAP = {
    "а": "", "б": "ב", "в": "ו", "г": "ג", "д": "ד", "е": "", "з": "ז", "и": "י",
    "й": "י", "к": "ק", "л": "ל", "м": "מ", "н": "נ", "о": "ו", "п": "פ", "р": "ר",
    "с": "ס", "т": "ט", "у": "ו", "ф": "פ", "ы": "י", "э": "", "ь": "", "ъ": "",
}
_EN_DIGRAPHS = {"sh": "ש", "ch": "צ", "kh": "ח", "ts": "צ", "th": "ת", "ya": "יא", "yu": "יו", "oo": "ו", "ee": "י"}
_EN_MAP = {
    "a": "", "b": "ב", "c": "ק", "d": "ד", "e": "", "f": "פ", "g": "ג", "h": "ה",
    "i": "י", "j": "ג", "k": "ק", "l": "ל", "m": "מ", "n": "נ", "o": "ו", "p": "פ",
    "q": "ק", "r": "ר", "s": "ס", "t": "ט", "u": "ו", "v": "ו", "w": "ו", "x": "קס",
    "y": "י", "z": "ז",
}
# Hebrew final forms fold to their base so רינה and mid-word forms compare equal
_HE_FINALS = str.maketrans("ךםןףץ", "כמנפצ")


def _translit_word(word: str, digraphs: dict[str, str], table: dict[str, str]) -> str:
    low = word.lower()
    # final а/я/a becomes a trailing ה by convention (Рина -> רינה), not a
    # regular letter — translate the rest and append it
    trailing = ""
    if low and low[-1] in ("а", "я", "a"):
        trailing = "ה"
        low = low[:-1]

    out: list[str] = []
    i = 0
    while i < len(low):
        pair = low[i:i + 2]
        if pair in digraphs:  # true digraphs (sh, ch, kh...)
            out.append(digraphs[pair])
            i += 2
            continue
        ch = low[i]
        # single letters with multi-letter output (ю -> יו) live in digraphs too
        out.append(digraphs.get(ch, table.get(ch, "")))
        i += 1

    # a word-initial vowel is written with א when it would otherwise start with
    # nothing or with ו (Алина -> אלינה, Ольга -> אולגה) — but not before י
    # (Юлия -> יוליה, not איוליה)
    if low and low[0] in "аеэоуиыюяaeiou":
        if not out or not out[0] or out[0][0] == "ו":
            out.insert(0, "א")
    return "".join(out) + trailing


def hebrew_key(name: str) -> str:
    """A script-independent comparison key: the (approximate) Hebrew consonant
    skeleton of the name, lowercase/final-form-normalized, per word."""
    words = []
    for word in (name or "").split():
        if any("а" <= ch <= "я" or ch in "ёЁ" for ch in word.lower()):
            words.append(_translit_word(word, _RU_DIGRAPHS, _RU_MAP))
        elif any("a" <= ch <= "z" for ch in word.lower()):
            words.append(_translit_word(word, _EN_DIGRAPHS, _EN_MAP))
        else:
            # already Hebrew: normalize finals, drop the one vowel-letter that
            # the transliterations above never emit mid-word
            words.append(word.translate(_HE_FINALS))
    return " ".join(w for w in words if w)


# --- Russian diminutives ----------------------------------------------------
# Риночка/Ринка/Риночек are Рина. Strip a known diminutive suffix and compare
# stems; requiring a 3+ char stem stops Ка- names collapsing together.
_DIMINUTIVE_SUFFIXES = (
    "очка", "ечка", "ичка", "онька", "енька", "ушка", "юшка", "ышка",
    "уля", "уся", "юша", "очек", "ёчек", "очка", "ка", "ша", "ик", "чик",
)


def _diminutive_stem(word: str) -> str | None:
    low = (word or "").lower()
    for suffix in sorted(_DIMINUTIVE_SUFFIXES, key=len, reverse=True):
        # a long, unambiguous suffix (ечка) may leave a 2-char stem (Юлечка ->
        # юл); the short generic ones (ка, ик) need 3+ or everything matches
        min_stem = 2 if len(suffix) >= 4 else 3
        if low.endswith(suffix) and len(low) - len(suffix) >= min_stem:
            return low[: len(low) - len(suffix)]
    return None


_HEBREW_CHAR_RE = re.compile("[֐-׿]")
# vowels normalized across scripts so Rina and Рина compare equal (и=i, а=a)
_VOWEL_NORM = {
    "а": "a", "е": "e", "ё": "o", "и": "i", "о": "o", "у": "u", "ы": "i",
    "э": "e", "ю": "u", "я": "a",
    "a": "a", "e": "e", "i": "i", "o": "o", "u": "u", "y": "i",
}


def _vowel_string(name: str) -> str:
    return "".join(_VOWEL_NORM[ch] for ch in name.lower() if ch in _VOWEL_NORM)


def _same_person_score(a: str, b: str) -> tuple[float, str] | None:
    """Confidence that two written names are the same human, with the reason.
    None = no evidence they match. Order of checks = strongest first.

    Only same-script matches where the VOWELS also agree reach auto-accept
    strength: the transliteration key drops vowels, so Алина and Элина —
    different women — share a key, and a Hebrew name has no vowel information
    at all. Anything vowel-ambiguous is a suggestion for a human, never an
    automatic merge."""
    if a == b:
        return None  # identical strings are not a merge, they are one mention
    key_a, key_b = hebrew_key(a), hebrew_key(b)
    # a 1-2 letter key carries too little signal to declare identity (short or
    # heavily-vowelled names collapse together)
    if len(key_a) >= 3 and key_a == key_b:
        hebrew_involved = _HEBREW_CHAR_RE.search(a) or _HEBREW_CHAR_RE.search(b)
        if not hebrew_involved and _vowel_string(a) == _vowel_string(b):
            return 0.95, "תעתיק זהה"
        if hebrew_involved:
            return 0.85, "תעתיק זהה"
        return 0.8, "תעתיק זהה (תנועות שונות)"
    stem_a, stem_b = _diminutive_stem(a), _diminutive_stem(b)
    low_a, low_b = a.lower(), b.lower()
    if stem_a and (low_b.startswith(stem_a) or stem_a == _diminutive_stem(b)):
        return 0.85, "צורת חיבה"
    if stem_b and low_a.startswith(stem_b):
        return 0.85, "צורת חיבה"
    if key_a and key_b and difflib.SequenceMatcher(None, key_a, key_b).ratio() >= FUZZY_MIN_RATIO:
        return 0.8, "תעתיק דומה"
    return None


# --- clustering --------------------------------------------------------------

def _case_name_mentions(session: Session, case_id: int) -> dict[str, list[tuple[int, int]]]:
    """name -> [(evidence_id, chunk_index)] for person-labeled entities of the
    case, noise filtered, rare names dropped."""
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
    mentions: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for text, label, evidence_id, chunk_index in rows:
        name = " ".join((text or "").split())
        if (
            label in PERSON_LABELS
            and len(name) >= 3
            and not is_noise_name(name)
            and _VALID_NAME_RE.match(name)
        ):
            mentions[name].append((evidence_id, chunk_index))
    return {n: locs for n, locs in mentions.items() if len(locs) >= MIN_MENTIONS}


def _alias_index(session: Session, case_id: int) -> dict[str, int]:
    """every known written form (person name or accepted alias) -> person_id"""
    index: dict[str, int] = {}
    persons = session.exec(select(Person).where(Person.case_id == case_id)).all()
    for p in persons:
        index[" ".join(p.name.split())] = p.id
    ids = [p.id for p in persons]
    if ids:
        for ln in session.exec(
            select(PersonLink).where(PersonLink.person_id.in_(ids), PersonLink.kind == "alias")
        ).all():
            index[" ".join((ln.value or "").split())] = ln.person_id
    return index


def suggest_identities(session: Session, case_id: int) -> list[dict]:
    """Clusters of written names that are likely the same human. Each cluster:
    canonical name, members with per-name citation, confidence (weakest pair in
    the cluster — honesty over optimism) and the match reasons."""
    mentions = _case_name_mentions(session, case_id)
    known = _alias_index(session, case_id)
    names = sorted(set(mentions) | set(known))

    # union-find over pairwise matches
    parent: dict[str, str] = {n: n for n in names}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    # Only pairs at auto-merge strength (same script, same vowels) chain into
    # clusters transitively. Everything weaker stays a standalone two-name
    # suggestion: transitive chaining merged Алиса+Алёна+Алина (fuzzy) and the
    # whole Мар* family — Марина, Марго, Марьяна, different women — through a
    # shared diminutive stem, into confident-looking clusters on a real case.
    # Pairwise review is a few more clicks; a wrong merge is wrong evidence.
    CHAIN_MIN = 0.9
    pair_info: dict[frozenset[str], tuple[float, str]] = {}
    weak_pairs: list[tuple[str, str, float, str]] = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            # two names both already accepted onto DIFFERENT persons are the
            # user's explicit decision — never propose re-merging them
            if a in known and b in known and known[a] != known[b]:
                continue
            scored = _same_person_score(a, b)
            if not scored:
                continue
            if scored[0] >= CHAIN_MIN:
                pair_info[frozenset((a, b))] = scored
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb
            else:
                weak_pairs.append((a, b, scored[0], scored[1]))

    clusters: dict[str, list[str]] = defaultdict(list)
    for n in names:
        clusters[find(n)].append(n)

    suggestions: list[dict] = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        confidences, reasons = [], set()
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                info = pair_info.get(frozenset((a, b)))
                if info:
                    confidences.append(info[0])
                    reasons.add(info[1])
        if not confidences:
            continue
        # canonical: an existing person's name wins; else the most-mentioned form
        canonical = next(
            (m for m in members if m in known),
            max(members, key=lambda m: len(mentions.get(m, []))),
        )
        suggestions.append({
            "canonical": canonical,
            "person_id": known.get(canonical),
            "members": [
                {
                    "name": m,
                    "mentions": len(mentions.get(m, [])),
                    "citation": (mentions.get(m) or [(None, None)])[0],
                    "already_linked": m in known,
                }
                for m in sorted(members, key=lambda m: -len(mentions.get(m, [])))
            ],
            "confidence": round(min(confidences), 2),
            "reasons": sorted(reasons),
        })

    # fuzzy matches: one pair per suggestion, and only when the two names did
    # not already land in the same strong cluster
    for a, b, confidence, reason in weak_pairs:
        if find(a) == find(b):
            continue
        canonical = a if a in known or len(mentions.get(a, [])) >= len(mentions.get(b, [])) else b
        other = b if canonical == a else a
        suggestions.append({
            "canonical": canonical,
            "person_id": known.get(canonical),
            "members": [
                {
                    "name": m,
                    "mentions": len(mentions.get(m, [])),
                    "citation": (mentions.get(m) or [(None, None)])[0],
                    "already_linked": m in known,
                }
                for m in (canonical, other)
            ],
            "confidence": confidence,
            "reasons": [reason],
        })
    return sorted(suggestions, key=lambda s: -s["confidence"])


def apply_identity(session: Session, case_id: int, canonical: str, aliases: list[str]) -> dict:
    """Persist one resolved identity: find-or-create the Person, attach each
    alias as a PersonLink the user can inspect and remove. Idempotent."""
    canonical = " ".join((canonical or "").split())
    if not canonical:
        raise ValueError("canonical name is required")

    known = _alias_index(session, case_id)
    person: Person | None = None
    if canonical in known:
        person = session.get(Person, known[canonical])
    if person is None:
        person = Person(case_id=case_id, name=canonical, description="אוחד אוטומטית (AI)")
        session.add(person)
        session.commit()
        session.refresh(person)

    added = []
    for alias in aliases:
        alias = " ".join((alias or "").split())
        if not alias or alias == person.name or known.get(alias) == person.id:
            continue
        session.add(PersonLink(person_id=person.id, kind="alias", value=alias, confidence=0.9))
        added.append(alias)
    session.commit()
    log_event(
        session, "identity_resolved", case_id=case_id,
        person_id=person.id, canonical=canonical, aliases=added,
    )
    return {"person_id": person.id, "canonical": person.name, "aliases_added": added}


def auto_resolve(session: Session, case_id: int) -> dict:
    """Apply every suggestion at/above AUTO_ACCEPT_CONFIDENCE. Lower-confidence
    clusters stay suggestions for the user to judge."""
    applied, skipped = [], 0
    for suggestion in suggest_identities(session, case_id):
        if suggestion["confidence"] < AUTO_ACCEPT_CONFIDENCE:
            skipped += 1
            continue
        result = apply_identity(
            session, case_id, suggestion["canonical"],
            [m["name"] for m in suggestion["members"] if m["name"] != suggestion["canonical"]],
        )
        applied.append(result)
    return {"applied": applied, "left_for_review": skipped}
