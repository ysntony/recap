from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class LLMError(RuntimeError):
    pass


def summarize_with_openrouter(prompt: str, model: str | None = None) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise LLMError("OPENROUTER_API_KEY is not set. Run without --llm, or set the key and try again.")

    body = {
        "model": model or os.environ.get("OPENROUTER_MODEL", "openai/gpt-4.1"),
        "messages": [
            {"role": "system", "content": "You are Recap, a concise engineering work journal."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    response = post_json(
        os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/") + "/chat/completions",
        body,
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.environ.get("OPENROUTER_REFERER", "https://github.com/ysntony/recap"),
            "X-Title": os.environ.get("OPENROUTER_TITLE", "Recap"),
        },
    )
    try:
        text = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("OpenRouter response did not contain summary text.") from exc
    if not isinstance(text, str) or not text.strip():
        raise LLMError("OpenRouter response did not contain summary text.")
    return text.strip() + "\n"


def summarize_with_msh(prompt: str, model: str | None = None) -> str:
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("MSH_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = {
        "model": model or os.environ.get("MSH_MODEL", "kimi-k2.6"),
        "messages": [
            {"role": "system", "content": "You are Recap, a concise engineering work journal."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    response = post_json(
        os.environ.get("MSH_BASE_URL", "https://free-tokens.msh.team/v1").rstrip("/") + "/chat/completions",
        body,
        headers,
    )
    try:
        text = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("MSH internal response did not contain summary text.") from exc
    if not isinstance(text, str) or not text.strip():
        raise LLMError("MSH internal response did not contain summary text.")
    return text.strip() + "\n"


def summarize_with_openai(prompt: str, model: str | None = None) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise LLMError("OPENAI_API_KEY is not set. Run without --llm, or set the key and try again.")

    body = {
        "model": model or os.environ.get("OPENAI_MODEL", "gpt-5.5"),
        "input": prompt,
    }
    payload = post_json(
        "https://api.openai.com/v1/responses",
        body,
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    text = payload.get("output_text")
    if isinstance(text, str) and text.strip():
        return text.strip() + "\n"

    parts: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            content_text = content.get("text")
            if isinstance(content_text, str):
                parts.append(content_text)
    if parts:
        return "\n".join(parts).strip() + "\n"
    raise LLMError("OpenAI response did not contain summary text.")


def post_json(url: str, body: dict, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LLMError(f"LLM request failed with HTTP {exc.code}: {detail[:500]}") from exc
    except OSError as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc
