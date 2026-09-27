from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EventKind = Literal["sentence", "action", "status", "emotion", "delay"]


@dataclass(frozen=True)
class InterruptionResult:
    """Outcome of a single :meth:`RobotPipeline.run` turn.

    ``spoken`` holds completed controller utterances. ``unspoken`` is retained
    for API compatibility and contains text not completed, including a sentence
    cut short. ``partial`` identifies started but incomplete sentences. These
    software records do not identify exactly which words a listener heard.
    """

    interrupted: bool
    spoken: list[str] = field(default_factory=list)
    unspoken: list[str] = field(default_factory=list)
    partial: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SpeechMarker:
    """An inline tag ([Nod], (Happy)) anchored to a character position in a sentence.

    The speech engine converts ``char_pos`` into a playback time via the word
    timeline, so the gesture fires while the matching word is being voiced.
    """

    kind: Literal["action", "emotion"]
    name: str
    char_pos: int


@dataclass(frozen=True)
class StreamChunk:
    """A small piece of raw text streamed from the LLM."""

    text: str
    source: str = "llm"


@dataclass(frozen=True)
class PipelineEvent:
    """A normalized event passed between pipeline stages."""

    kind: EventKind
    payload: str
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "payload": self.payload,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineEvent":
        return cls(
            kind=data["kind"],
            payload=data["payload"],
            metadata=dict(data.get("metadata", {})),
        )
