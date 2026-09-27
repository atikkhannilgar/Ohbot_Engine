from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from .client import format_interruption_note

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiAPIError(RuntimeError):
    """Wraps any failure returned by the Gemini REST API."""


async def list_gemini_models(api_key: str) -> list[str]:
    # Fetched live from the API so the model list always matches what the key can actually use.
    # Filters out models that do not support content generation (e.g. embedding only models).
    if not api_key:
        raise GeminiAPIError("gemini_api_key is empty, fill it in config.json.")

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            r = await client.get(f"{GEMINI_BASE}/models", params={"key": api_key})
        except httpx.HTTPError as exc:
            raise GeminiAPIError(f"could not reach Gemini API: {exc}") from exc

    if r.status_code != 200:
        raise GeminiAPIError(f"Gemini /models returned {r.status_code}: {r.text[:200]}")

    payload = r.json()
    models: list[str] = []
    for entry in payload.get("models", []):
        name = entry.get("name", "")
        if not name.startswith("models/"):
            continue
        methods = entry.get("supportedGenerationMethods", [])
        if "generateContent" not in methods and "streamGenerateContent" not in methods:
            continue
        models.append(name[len("models/"):])
    return sorted(models)


class GeminiLLMClient:
    """Streams responses from Google's Gemini REST API. Maintains conversation history."""

    def __init__(self, api_key: str, model: str, system_prompt: str) -> None:
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        # Multi turn history. Each call appends the new user turn and, after streaming
        # completes, the assembled assistant turn, so the next prompt sees prior context.
        self._contents: list[dict] = []
        # If the previous turn was interrupted, this note is folded into the *next* user
        # turn (rather than added as its own turn) so the user/model roles keep
        # alternating, which the Gemini API requires.
        self._pending_note: str | None = None

    async def __aenter__(self) -> "GeminiLLMClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def register_interruption(self, spoken: list[str], unspoken: list[str]) -> None:
        self._pending_note = format_interruption_note(spoken, unspoken)

    async def stream_response(self, prompt: str) -> AsyncIterator[str]:
        if self._pending_note:
            prompt = f"{self._pending_note}\n\n{prompt}"
            self._pending_note = None
        self._contents.append({"role": "user", "parts": [{"text": prompt}]})

        body = {
            "system_instruction": {"parts": [{"text": self.system_prompt}]},
            "contents": self._contents,
        }
        url = f"{GEMINI_BASE}/models/{self.model}:streamGenerateContent"
        params = {"alt": "sse", "key": self.api_key}

        collected: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
                try:
                    async with client.stream("POST", url, params=params, json=body) as response:
                        if response.status_code != 200:
                            text = (await response.aread()).decode("utf-8", errors="replace")
                            raise GeminiAPIError(
                                f"Gemini stream returned {response.status_code}: {text[:200]}"
                            )

                        # Gemini streams Server Sent Events. Each meaningful line starts with "data:"
                        # followed by a JSON payload. Comments and blank keepalive lines are ignored.
                        async for line in response.aiter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            data = line[len("data:"):].strip()
                            if not data:
                                continue
                            try:
                                payload = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            for candidate in payload.get("candidates", []):
                                parts = candidate.get("content", {}).get("parts", [])
                                for part in parts:
                                    text = part.get("text")
                                    if text:
                                        collected.append(text)
                                        yield text
                except httpx.HTTPError as exc:
                    raise GeminiAPIError(f"network error while streaming: {exc}") from exc
        finally:
            # Persist whatever was generated  even if the stream was closed early by an
            # interrupt or errored partway  so history reflects what the model actually
            # produced this turn.
            if collected:
                self._contents.append({"role": "model", "parts": [{"text": "".join(collected)}]})
