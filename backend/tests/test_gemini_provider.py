import io
import json

from app.services import llm_service


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_gemini_is_opt_in_default_is_local():
    # the default must stay local: evidence does not leave the machine unless the
    # user deliberately switches provider
    assert llm_service.LLM_PROVIDER in ("ollama", "gemini")
    # a fresh process with nothing set defaults to ollama
    import os
    assert os.getenv("CASEMIND_LLM_PROVIDER", "ollama").lower() == llm_service.LLM_PROVIDER


def test_gemini_call_builds_the_right_request(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        return _FakeResponse(json.dumps({
            "candidates": [{"content": {"parts": [{"text": "יוליה פגשה את דמיטרי"}]}}]
        }).encode())

    monkeypatch.setattr(llm_service, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_service, "GEMINI_MODEL", "gemini-2.0-flash")
    monkeypatch.setattr(llm_service.urllib.request, "urlopen", fake_urlopen)

    out = llm_service._gemini_call([
        {"role": "system", "content": "Translate to Hebrew."},
        {"role": "user", "content": "Юлия встретила Дмитрия"},
    ])

    assert out == "יוליה פגשה את דמיטרי"
    assert "gemini-2.0-flash:generateContent" in captured["url"]
    assert "key=test-key" in captured["url"]
    # system turn goes to systemInstruction, not into contents
    assert captured["body"]["systemInstruction"]["parts"][0]["text"] == "Translate to Hebrew."
    assert captured["body"]["contents"][0]["parts"][0]["text"] == "Юлия встретила Дмитрия"


def test_gemini_without_a_key_returns_none_not_a_crash(monkeypatch):
    monkeypatch.setattr(llm_service, "GEMINI_API_KEY", None)
    assert llm_service._gemini_call([{"role": "user", "content": "hi"}]) is None


def test_provider_dispatch_routes_to_gemini(monkeypatch):
    monkeypatch.setattr(llm_service, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm_service, "_gemini_call", lambda messages: "from-gemini")
    monkeypatch.setattr(llm_service, "_ollama_call", lambda model, messages: "from-ollama")
    assert llm_service._chat_call("ignored", [{"role": "user", "content": "x"}]) == "from-gemini"

    monkeypatch.setattr(llm_service, "LLM_PROVIDER", "ollama")
    assert llm_service._chat_call("m", [{"role": "user", "content": "x"}]) == "from-ollama"


def test_active_model_reports_gemini_when_selected(monkeypatch):
    monkeypatch.setattr(llm_service, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm_service, "GEMINI_API_KEY", "k")
    monkeypatch.setattr(llm_service, "GEMINI_MODEL", "gemini-2.0-flash")
    assert llm_service.active_model() == "gemini-2.0-flash"
    assert llm_service.ollama_available() is True   # "an LLM is available"

    monkeypatch.setattr(llm_service, "GEMINI_API_KEY", None)
    assert llm_service.active_model() is None
