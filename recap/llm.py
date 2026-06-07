from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class LLMError(RuntimeError):
    pass


def summarize_with_openai(prompt: str, model: str | None = None) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise LLMError("OPENAI_API_KEY is not set. Run without --llm, or set the key and try again.")

    body = {
        "model": model or os.environ.get("OPENAI_MODEL", "gpt-5.5"),
        "input": prompt,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LLMError(f"OpenAI request failed with HTTP {exc.code}: {detail[:500]}") from exc
    except OSError as exc:
        raise LLMError(f"OpenAI request failed: {exc}") from exc

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
