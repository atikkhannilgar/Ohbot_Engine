from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from .client import format_interruption_note


class OllamaAPIError(RuntimeError):
    pass


async def list_ollama_models(base_url: str) -> list[str]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            r = await client.get(f"{base_url}/api/tags")
        except httpx.HTTPError as exc:
            raise OllamaAPIError(f"could not reach Ollama at {base_url}: {exc}") from exc

    if r.status_code != 200:
        raise OllamaAPIError(f"Ollama /api/tags returned {r.status_code}: {r.text[:200]}")

    payload = r.json()
    models = [m.get("name", "") for m in payload.get("models", [])]
    return sorted(m for m in models if m)


class OllamaLLMClient:
    """Streams responses from a remote Ollama server reached via a pre-opened SSH tunnel.

    The caller passes ``base_url`` already pointing at the local-bound tunnel port
    (e.g. ``http://127.0.0.1:54321``); this client does not manage the tunnel itself.
    """

    def __init__(self, base_url: str, model: str, system_prompt: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.system_prompt = system_prompt
        # Ollama wants the system prompt as the first entry in the messages list, in contrast
        # to Gemini where the system instruction lives in a separate top level field.
        self._messages: list[dict] = [{"role": "system", "content": system_prompt}]
        # Folded into the next user turn after an interrupt (see GeminiLLMClient).
        self._pending_note: str | None = None

    async def __aenter__(self) -> "OllamaLLMClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def register_interruption(self, spoken: list[str], unspoken: list[str]) -> None:
        self._pending_note = format_interruption_note(spoken, unspoken)

    async def stream_response(self, prompt: str) -> AsyncIterator[str]:
        if self._pending_note:
            prompt = f"{self._pending_note}\n\n{prompt}"
            self._pending_note = None
        self._messages.append({"role": "user", "content": prompt})

        body = {
            "model": self.model,
            "messages": self._messages,
            "stream": True,
            # Qwen3.5+ "thinking" can burn tens of seconds before the first spoken
            # token; disable it so voice turns stay responsive.
            "think": False,
        }

        collected: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=15.0)) as client:
                try:
                    async with client.stream("POST", f"{self.base_url}/api/chat", json=body) as response:
                        if response.status_code != 200:
                            text = (await response.aread()).decode("utf-8", errors="replace")
                            raise OllamaAPIError(
                                f"Ollama /api/chat returned {response.status_code}: {text[:200]}"
                            )

                        # Ollama uses NDJSON: one JSON object per line. The last object has
                        # "done": true and may contain summary stats but no extra content.
                        async for line in response.aiter_lines():
                            if not line.strip():
                                continue
                            try:
                                payload = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            content = payload.get("message", {}).get("content", "")
                            if content:
                                collected.append(content)
                                yield content
                            if payload.get("done"):
                                break
                except httpx.HTTPError as exc:
                    raise OllamaAPIError(f"network error while streaming: {exc}") from exc
        finally:
            # Persist partial output too, so an interrupt mid-stream still leaves the
            # assistant turn in history (see GeminiLLMClient for the rationale).
            if collected:
                self._messages.append({"role": "assistant", "content": "".join(collected)})
