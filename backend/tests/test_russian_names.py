from fastapi.testclient import TestClient

from app.main import app
from app.services import llm_service
from app.services.entity_service import is_noise_name
from app.services.ner_service import extract_entities


def test_russian_pronouns_are_not_names():
    # these were the top-3 "names" in a real case: Russian capitalises the first
    # word of every sentence, so the regex swept up pronouns and particles
    for word in ("Она", "Это", "Нет", "Что", "Как", "Привет", "Хорошо",
                 "Потому", "Скажи", "Короче", "Слушай", "Блин"):
        assert is_noise_name(word), word
    assert is_noise_name("Ааа")  # interjection: one letter repeated
    # real names must survive
    for name in ("Юля", "Алиса", "Марина", "Дмитрий", "Рина", "Настя", "Костя"):
        assert not is_noise_name(name), name


def test_extraction_keeps_names_drops_noise():
    text = "Она сказала, что Марина встретила Дмитрия. Хорошо. Алиса тоже была там."
    names = {e["text"] for e in extract_entities(text) if e["label"] == "person"}
    assert {"Марина", "Алиса"} <= names
    assert not ({"Она", "Хорошо"} & names)


def test_trim_glued_function_words_from_name():
    # Natasha on chat text glues the next token onto a name: a contact saved
    # "Кроха Рина" became "Кроха Рина Он/Нет/Она/Ой/Ага" - one junk person per
    # trailing particle, which entity resolution then offered to merge as the
    # same endearment for everyone. The name core must survive, the tail must go.
    import pymorphy3

    from app.services.russian_ner import _trim_function_words

    morph = pymorphy3.MorphAnalyzer()
    for tail in ("Он", "Нет", "Она", "Ой", "Ага"):
        assert _trim_function_words(f"Кроха Рина {tail}", morph) == "Кроха Рина"
    # a real two-part name is untouched
    assert _trim_function_words("Алекс Голованов", morph) == "Алекс Голованов"
    # a span that is only function words collapses to nothing (entity dropped)
    assert len(_trim_function_words("Она Нет", morph)) < 2


def test_hebrew_names_endpoint(monkeypatch):
    monkeypatch.setattr(llm_service, "ollama_available", lambda: True)
    monkeypatch.setattr(llm_service, "active_model", lambda: "aya-expanse:8b")
    monkeypatch.setattr(
        llm_service, "to_hebrew_name",
        lambda name: {"Марина": "מרינה", "Юля": "יוליה"}.get(name, ""),
    )
    with TestClient(app) as client:
        r = client.post("/entities/hebrew-names",
                        json={"names": ["Марина", "Юля", "David", "אמיר"]})
        assert r.status_code == 200
        names = r.json()["names"]
        assert names == {"Марина": "מרינה", "Юля": "יוליה"}  # non-Cyrillic skipped


def test_hebrew_names_without_llm_returns_503(monkeypatch):
    monkeypatch.setattr(llm_service, "ollama_available", lambda: False)
    with TestClient(app) as client:
        r = client.post("/entities/hebrew-names", json={"names": ["Марина"]})
        assert r.status_code == 503
