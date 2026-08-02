"""Part 6 tests: app.llm_adapter -- the optional, disabled-by-default LLM
wording adapter. The RA Assistant must be fully functional with none of
these environment variables set; these tests confirm that guarantee and
the adapter's safe-fallback behavior when it IS enabled but misconfigured
or the network call fails.
"""
from app.llm_adapter import maybe_rewrite_with_llm


def _deterministic_result():
    return {
        "intent": "explain_current_status",
        "station_id": "hybrid-01",
        "answer": "The deterministic answer text.",
        "facts": [{"label": "Generation", "value": 10.0, "unit": "kW"}],
        "generated_from": ["current_state"],
        "grounding": {
            "scenario": "sunny", "current_index": 136, "timestamp": "2026-07-02T10:00:00",
            "station_id": "hybrid-01", "what_if_included": False, "mode": "offline_deterministic",
        },
    }


def test_disabled_by_default_returns_result_unchanged(monkeypatch):
    monkeypatch.delenv("RA_ASSISTANT_LLM_ENABLED", raising=False)
    result = _deterministic_result()
    out = maybe_rewrite_with_llm(result)
    assert out == result
    assert out["grounding"]["mode"] == "offline_deterministic"


def test_explicitly_disabled_returns_result_unchanged(monkeypatch):
    monkeypatch.setenv("RA_ASSISTANT_LLM_ENABLED", "false")
    result = _deterministic_result()
    assert maybe_rewrite_with_llm(result) == result


def test_enabled_but_missing_config_returns_result_unchanged(monkeypatch):
    monkeypatch.setenv("RA_ASSISTANT_LLM_ENABLED", "true")
    monkeypatch.delenv("RA_ASSISTANT_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("RA_ASSISTANT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("RA_ASSISTANT_LLM_MODEL", raising=False)
    result = _deterministic_result()
    assert maybe_rewrite_with_llm(result) == result


def test_out_of_scope_intent_is_never_sent_to_llm(monkeypatch):
    monkeypatch.setenv("RA_ASSISTANT_LLM_ENABLED", "true")
    monkeypatch.setenv("RA_ASSISTANT_LLM_BASE_URL", "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv("RA_ASSISTANT_LLM_API_KEY", "fake-key")
    monkeypatch.setenv("RA_ASSISTANT_LLM_MODEL", "fake-model")
    result = _deterministic_result()
    result["intent"] = "out_of_scope"
    out = maybe_rewrite_with_llm(result)
    assert out == result  # untouched -- refusal/safety wording is never rewritten


def test_network_failure_falls_back_to_deterministic_answer(monkeypatch):
    monkeypatch.setenv("RA_ASSISTANT_LLM_ENABLED", "true")
    monkeypatch.setenv("RA_ASSISTANT_LLM_BASE_URL", "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv("RA_ASSISTANT_LLM_API_KEY", "fake-key")
    monkeypatch.setenv("RA_ASSISTANT_LLM_MODEL", "fake-model")
    monkeypatch.setenv("RA_ASSISTANT_LLM_TIMEOUT_SECONDS", "1")

    import urllib.error

    def _raise(*args, **kwargs):
        raise urllib.error.URLError("simulated network failure")

    monkeypatch.setattr("urllib.request.urlopen", _raise)

    result = _deterministic_result()
    out = maybe_rewrite_with_llm(result)
    assert out == result
    assert out["grounding"]["mode"] == "offline_deterministic"


def test_successful_rewrite_only_changes_answer_and_mode(monkeypatch):
    monkeypatch.setenv("RA_ASSISTANT_LLM_ENABLED", "true")
    monkeypatch.setenv("RA_ASSISTANT_LLM_BASE_URL", "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv("RA_ASSISTANT_LLM_API_KEY", "fake-key")
    monkeypatch.setenv("RA_ASSISTANT_LLM_MODEL", "fake-model")

    import io
    import json as json_module

    class _FakeResponse:
        def __init__(self, payload):
            self._payload = json_module.dumps(payload).encode("utf-8")

        def read(self):
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _fake_urlopen(request, timeout=None):
        return _FakeResponse({"choices": [{"message": {"content": "A rewritten, more natural answer."}}]})

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    result = _deterministic_result()
    out = maybe_rewrite_with_llm(result)
    assert out["answer"] == "A rewritten, more natural answer."
    assert out["grounding"]["mode"] == "llm_rewrite"
    # Facts, intent, station_id, and every other grounding field are untouched.
    assert out["facts"] == result["facts"]
    assert out["intent"] == result["intent"]
    assert out["station_id"] == result["station_id"]
    assert out["grounding"]["scenario"] == result["grounding"]["scenario"]


def test_malformed_llm_response_falls_back_to_deterministic_answer(monkeypatch):
    monkeypatch.setenv("RA_ASSISTANT_LLM_ENABLED", "true")
    monkeypatch.setenv("RA_ASSISTANT_LLM_BASE_URL", "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv("RA_ASSISTANT_LLM_API_KEY", "fake-key")
    monkeypatch.setenv("RA_ASSISTANT_LLM_MODEL", "fake-model")

    import json as json_module

    class _FakeResponse:
        def __init__(self):
            self._payload = json_module.dumps({"unexpected": "shape"}).encode("utf-8")

        def read(self):
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=None: _FakeResponse())

    result = _deterministic_result()
    out = maybe_rewrite_with_llm(result)
    assert out == result
