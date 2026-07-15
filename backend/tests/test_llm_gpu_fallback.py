"""When the GPU is busy (Whisper transcribing for days on the shared 4GB card),
Ollama's llama-server crashes loading the LLM with HTTP 500. The call must fall
back to CPU, not fail the user's translation/AI request."""
import io
import urllib.error
from unittest.mock import patch

from app.services import llm_service


def _http_500(body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "http://x/api/chat", 500, "Internal Server Error", {}, io.BytesIO(body)
    )


def test_gpu_oom_signatures_detected():
    crash = _http_500(
        b'{"error":"llama-server process has terminated: exit status 0xc0000409: '
        b'stack-based buffer overrun"}'
    )
    assert llm_service._looks_like_gpu_oom(crash)
    assert llm_service._looks_like_gpu_oom(_http_500(b'{"error":"CUDA out of memory"}'))
    # a 404 (model genuinely absent) is NOT this class — must not retry on CPU
    assert not llm_service._looks_like_gpu_oom(
        urllib.error.HTTPError("http://x", 404, "not found", {}, io.BytesIO(b"nope"))
    )
    assert not llm_service._looks_like_gpu_oom(TimeoutError("slow"))


def test_call_retries_on_cpu_after_gpu_crash():
    calls = []

    def fake_post(model, messages, num_gpu):
        calls.append(num_gpu)
        if num_gpu is None:            # the GPU attempt
            raise _http_500(b'{"error":"llama-server has terminated: buffer overrun"}')
        return "התשובה מה-CPU"          # the CPU retry

    with patch.object(llm_service, "_post_chat", side_effect=fake_post):
        out = llm_service._ollama_call("gemma4:latest", [{"role": "user", "content": "hi"}])

    assert out == "התשובה מה-CPU"
    assert calls == [None, 0]           # tried GPU, then forced CPU


def test_non_gpu_error_does_not_retry():
    calls = []

    def fake_post(model, messages, num_gpu):
        calls.append(num_gpu)
        raise TimeoutError("model is slow")

    with patch.object(llm_service, "_post_chat", side_effect=fake_post):
        out = llm_service._ollama_call("gemma4:latest", [{"role": "user", "content": "hi"}])

    assert out is None
    assert calls == [None]              # a timeout is not retried on CPU
