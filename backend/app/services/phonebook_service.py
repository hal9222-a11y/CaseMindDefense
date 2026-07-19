"""Phone directory: a number -> the name(s) it is saved under, folded across
spelling/nickname variants and across every device's phonebook.

This is the "0542228282 is Нина Амид / נינה עבודה / Work Yulka" lookup done by the
machine. The contacts were extracted at index time (a contacts-directory chunk
per device, plus WhatsApp display labels) but never turned into anything
queryable. Here we read those clean name<->number pairs back out, group by
number, and cluster the names that are the same human written differently
(reusing resolution's Hebrew key), so one number resolves to its owner and every
alias it travels under — the cross-device "saved as X here, Y there" signal.

Read-only and deterministic: no Person rows are written, it recomputes on call.
ponytail: linear scan of the case's chunks per call; fine at tens of thousands,
memoize or index name<->phone at write time if it ever gets called hot.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from sqlmodel import Session, select

from app.models.evidence import Evidence, EvidenceChunk
from app.services.entity_service import is_noise_name
from app.services.resolution_service import _VALID_NAME_RE, hebrew_key

# contacts-directory line ("שם מלא: +972...") and WhatsApp display label
# ("972542228282@s.whatsapp.net | Нина Амид")
_CONTACT_LINE = re.compile(r"^\s*(.+?):\s*\+?(\d[\d\s\-]{7,})\s*$", re.MULTILINE)
_WA_LABEL = re.compile(r"(\d{9,15})@s\.whatsapp\.net\s*\|\s*([^|\n]{2,40})")

# call-log / table structure tokens that sit where a name would and are NOT names
_JUNK = {
    "from", "to", "account", "identifier", "direction", "participants", "body",
    "reply", "incoming", "outgoing", "missed", "answered", "not answered",
    "source", "whatsapp", "owner", "בעל המכשיר", "n/a", "unknown", "group",
}


def _norm_phone(raw: str) -> str:
    """Israeli-friendly comparison key: digits only, last 9 (drops 0 / +972 /
    country code) so 0542228282, +972542228282 and 972-54-222-8282 are one."""
    d = "".join(ch for ch in raw if ch.isdigit())
    return d[-9:] if len(d) >= 9 else d


def _clean_name(name: str) -> str | None:
    name = " ".join((name or "").split())
    low = name.lower()
    if len(name) < 2 or len(name) > 40:
        return None
    if low in _JUNK or is_noise_name(name):
        return None
    if not _VALID_NAME_RE.match(name):  # letters + space/hyphen only — drops "35 - ?"
        return None
    return name


def _harvest(session: Session, case_id: int) -> dict[str, Counter]:
    """number(9) -> Counter(name): every name a number is written under, from the
    contacts directories and WhatsApp labels of the case's evidence."""
    ev_ids = list(session.exec(
        select(Evidence.id).where(Evidence.case_id == case_id)
    ).all())
    phone_names: dict[str, Counter] = defaultdict(Counter)
    if not ev_ids:
        return phone_names
    rows = session.exec(
        select(EvidenceChunk.text, EvidenceChunk.source_location)
        .where(EvidenceChunk.evidence_id.in_(ev_ids))
    ).all()
    for text, loc in rows:
        text = text or ""
        if loc == "contacts":  # a device phonebook — every line is a real pair
            for name, phone in _CONTACT_LINE.findall(text):
                nm = _clean_name(name)
                if nm:
                    phone_names[_norm_phone(phone)][nm] += 1
        if "@s.whatsapp.net" in text:  # WhatsApp display labels (chat exports)
            for phone, name in _WA_LABEL.findall(text):
                nm = _clean_name(name)
                if nm:
                    phone_names[_norm_phone(phone)][nm] += 1
    return phone_names


def _ckey(name: str) -> str:
    """Order-independent identity key: the Hebrew skeleton of each word, sorted —
    so 'Катя Камилла' and 'Камилла Катя' (the same contact noted two ways) fold
    together instead of counting as two separate identities."""
    return " ".join(sorted(t for t in hebrew_key(name).split() if t))


def _cluster(names: Counter) -> list[list[str]]:
    """Group the names of ONE number into same-person variants (Нина / נינה /
    Nina, and word-order twins, share a key), most-seen name leading each group."""
    ordered = [n for n, _ in names.most_common()]
    groups: list[list[str]] = []
    keys: list[str] = []
    for name in ordered:
        k = _ckey(name)
        placed = False
        for i, gk in enumerate(keys):
            if k and gk and (k == gk or k in gk or gk in k):
                groups[i].append(name)
                placed = True
                break
        if not placed:
            groups.append([name])
            keys.append(k)
    return groups


def _entry(phone: str, names: Counter) -> dict:
    variants = _cluster(names)
    primary = variants[0][0] if variants else ""
    return {
        "phone": phone,
        "primary_name": primary,
        "distinct_identities": len(variants),  # >1 = one number, several people/aliases
        "names": [{"name": n, "count": names[n]} for n, _ in names.most_common()],
        "variant_groups": variants,
        "mentions": sum(names.values()),
    }


def phone_directory(session: Session, case_id: int, min_mentions: int = 1) -> list[dict]:
    """The whole case as number -> its name(s). Sorted so the numbers that carry
    the MOST distinct identities (the interesting 'saved as several names' ones)
    surface first."""
    harvested = _harvest(session, case_id)
    entries = [
        _entry(p, names) for p, names in harvested.items()
        if sum(names.values()) >= min_mentions
    ]
    entries.sort(key=lambda e: (-e["distinct_identities"], -e["mentions"]))
    return entries


def lookup_phone(session: Session, case_id: int, number: str) -> dict:
    """One number -> the name(s) it is saved under across the case ('' names if
    it appears nowhere with a name)."""
    key = _norm_phone(number)
    names = _harvest(session, case_id).get(key, Counter())
    return _entry(key, names) if names else {
        "phone": key, "primary_name": "", "distinct_identities": 0,
        "names": [], "variant_groups": [], "mentions": 0,
    }
