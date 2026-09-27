from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    """The contract every LLM source in this project implements."""

    # Anything that yields string chunks one at a time qualifies as an LLM client here.
    # The orchestrator never imports a concrete class, only this protocol, which lets
    # the scripted, Gemini and Ollama clients drop in interchangeably.
    def stream_response(self, prompt: str) -> AsyncIterator[str]: ...

    def register_interruption(self, spoken: list[str], unspoken: list[str]) -> None:
        """Tell the source it was interrupted mid-reply.

        Optional: history-keeping clients (Gemini, Ollama) record a note so the next
        turn is interruption-aware. Stateless sources may no-op.
        """


def format_interruption_note(spoken: list[str], unspoken: list[str]) -> str:
    """Build the note injected into LLM history after a barge-in / keyboard interrupt.

    ``spoken`` contains completed utterances. ``unspoken`` contains text whose
    playback did not complete; its first sentence may have been partly delivered.
    """
    spoken_text = " ".join(s.strip() for s in spoken if s.strip()).strip()
    unspoken_text = " ".join(s.strip() for s in unspoken if s.strip()).strip()

    parts = ["[SYSTEM NOTE: The user interrupted you while you were still speaking."]
    if spoken_text:
        parts.append(f' Playback completed for: "{spoken_text}".')
    if unspoken_text:
        parts.append(f' Playback did not complete for: "{unspoken_text}". Its beginning may have been heard; the exact audible cutoff is unknown.')
    else:
        parts.append(" You were cut off near the very end of your reply.")
    parts.append(
        " Acknowledge that you were interrupted and respond to what the user says next."
        " Do not simply repeat what you were going to say.]"
    )
    return "".join(parts)


class ScriptedLLMClient:
    """Development-only source that replays a finished string as streamed output."""

    def __init__(self, response_text: str, chunk_size: int = 24) -> None:
        self.response_text = response_text
        self.chunk_size = max(1, chunk_size)

    async def stream_response(self, prompt: str) -> AsyncIterator[str]:
        del prompt

        for index in range(0, len(self.response_text), self.chunk_size):
            await asyncio.sleep(0.1)
            yield self.response_text[index : index + self.chunk_size]

    def register_interruption(self, spoken: list[str], unspoken: list[str]) -> None:
        # Stateless replay source  nothing to remember between turns.
        del spoken, unspoken
