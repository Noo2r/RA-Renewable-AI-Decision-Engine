"""Optional LLM wording adapter for the RA Assistant (Part 6, Step 11).

Disabled by default. The deterministic answer from
`ra_core.assistant.answer_question()` is ALWAYS generated first and is
fully functional on its own -- this adapter may only rewrite its `answer`
text for more natural phrasing when explicitly enabled. It never receives
permission to change facts, grounding, or the recommendation, and its
output is discarded (silently falling back to the deterministic answer)
on any timeout, error, or malformed response.

Environment variables (see .env.example at the repo root):
  RA_ASSISTANT_LLM_ENABLED           "true" to enable (default: disabled)
  RA_ASSISTANT_LLM_BASE_URL          OpenAI-compatible chat-completions URL
  RA_ASSISTANT_LLM_API_KEY           API key (never hardcoded, never logged)
  RA_ASSISTANT_LLM_MODEL             model name
  RA_ASSISTANT_LLM_TIMEOUT_SECONDS   request timeout in seconds (default 5)

Uses only the Python standard library (urllib) -- no SDK is installed for
this optional feature, keeping it a genuinely lightweight add-on.
"""
import json
import os
import urllib.error
import urllib.request


def _enabled() -> bool:
    return os.environ.get("RA_ASSISTANT_LLM_ENABLED", "").strip().lower() in ("1", "true", "yes")


def _build_prompt(result: dict) -> str:
    facts_text = "; ".join(
        f"{f['label']}: {f['value']}{(' ' + f['unit']) if f.get('unit') else ''}"
        for f in result.get("facts", [])
    )
    return (
        "Rewrite the following answer from a renewable-energy dashboard assistant in clearer, "
        "more natural language. Do NOT change any numbers, facts, or the recommendation. Do NOT "
        "add new information beyond what is given. Keep it to 2-6 sentences.\n\n"
        f"Intent: {result['intent']}\n"
        f"Supporting facts: {facts_text}\n"
        f"Deterministic answer: {result['answer']}"
    )


def maybe_rewrite_with_llm(result: dict) -> dict:
    """result: the full deterministic answer dict from
    ra_core.assistant.answer_question(). Returns it byte-for-byte unchanged
    unless the adapter is enabled, fully configured, and a rewrite
    genuinely succeeds -- in which case only `answer` and
    `grounding.mode` are updated (never `facts`, `intent`, or
    `station_id`)."""
    if not _enabled():
        return result
    if result.get("intent") == "out_of_scope":
        # Safety/refusal wording is never handed to the LLM to rephrase.
        return result

    base_url = os.environ.get("RA_ASSISTANT_LLM_BASE_URL", "").strip()
    api_key = os.environ.get("RA_ASSISTANT_LLM_API_KEY", "").strip()
    model = os.environ.get("RA_ASSISTANT_LLM_MODEL", "").strip()
    if not base_url or not api_key or not model:
        return result

    try:
        timeout = float(os.environ.get("RA_ASSISTANT_LLM_TIMEOUT_SECONDS", "5"))
    except ValueError:
        timeout = 5.0

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": _build_prompt(result)}],
        "temperature": 0.2,
        "max_tokens": 300,
    }).encode("utf-8")

    request = urllib.request.Request(
        base_url, data=payload, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        rewritten = body["choices"][0]["message"]["content"].strip()
        if not rewritten:
            return result
        rewritten_result = dict(result)
        rewritten_result["answer"] = rewritten
        rewritten_result["grounding"] = {**result["grounding"], "mode": "llm_rewrite"}
        return rewritten_result
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError, OSError):
        return result
