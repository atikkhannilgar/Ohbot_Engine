from __future__ import annotations

import re
from dataclasses import dataclass

from .models import PipelineEvent

# The four token shapes the processor recognises in the stream.
# Order matters here: !Delay\d+ must be tried before the bare [.!?] alternative,
# otherwise the leading ! of a delay marker would be eaten as a sentence terminator.
TOKEN_RE = re.compile(r"\[[^\[\]]+\]|\([^()]+\)|!Delay\d+|[.!?]")

# Matches any prefix of "!Delay<digits>" sitting at the very end of the buffer.
# Used to detect a control token that got cut mid stream, so we can keep it for next chunk.
_INCOMPLETE_DELAY_TAIL_RE = re.compile(r"!(?:D(?:e(?:l(?:a(?:y\d*)?)?)?)?)?$")


@dataclass
class StreamProcessor:
    """Converts raw LLM text into sentence/action/emotion/delay events."""

    strip_action_tags: bool = True

    def __post_init__(self) -> None:
        self._buffer = ""
        self._sentence_parts: list[str] = []
        self._pending_actions: list[str] = []
        self._pending_emotions: list[str] = []
        self._pending_delays: list[str] = []

    def _normalize_sentence(self, sentence: str) -> str:
        return re.sub(r"\s+", " ", sentence).strip()

    def _current_len(self) -> int:
        return len(self._normalize_sentence("".join(self._sentence_parts)))

    def feed(self, text: str) -> list[PipelineEvent]:
        return self._consume(text, final=False)

    def _consume(self, text: str, *, final: bool) -> list[PipelineEvent]:
        self._buffer += text
        events: list[PipelineEvent] = []
        position = 0

        while True:
            match = TOKEN_RE.search(self._buffer, position)
            if match is None:
                break

            token = match.group(0)

            if not final and token == "!" and _INCOMPLETE_DELAY_TAIL_RE.fullmatch(self._buffer[match.start():]):
                # Do not consume punctuation before knowing whether it starts a delay.
                break

            if not final and token.startswith("!Delay") and match.end() == len(self._buffer):
                # A !Delay500 sitting at the very tail of the buffer might still be
                # growing (the next chunk could turn 500 into 5000), so leave it in
                # the buffer and let the next feed() decide.
                break

            part_before = self._buffer[position:match.start()]
            self._sentence_parts.append(part_before)
            position = match.end()

            # handle action tokens
            if token.startswith("["):
                action_name = token[1:-1].strip()
                if action_name:
                    self._pending_actions.append(f"{action_name}@{self._current_len()}")
                continue

            # handle emotion tokens
            if token.startswith("("):
                emotion_name = token[1:-1].strip()
                if emotion_name:
                    self._pending_emotions.append(f"{emotion_name}@{self._current_len()}")
                continue

            # handle delay tokens
            if token.startswith("!Delay"):
                ms = token[len("!Delay"):]
                if ms.isdigit():
                    self._pending_delays.append(f"{ms}@{self._current_len()}")
                continue

            self._sentence_parts.append(token)
            event = self._emit_sentence()
            if event is not None:
                events.append(event)

        remaining = self._buffer[position:]
        incomplete = self._find_incomplete_token(remaining)
        if incomplete is not None:
            self._sentence_parts.append(remaining[:incomplete])
            self._buffer = remaining[incomplete:]
        else:
            self._sentence_parts.append(remaining)
            self._buffer = ""

        return events

    def _find_incomplete_token(self, text: str) -> int | None:
        # Look at the tail of the unprocessed buffer for any opening control character
        # whose closing counterpart has not arrived yet. Returns the earliest such index
        # so everything from that point onward is preserved for the next chunk.
        candidates: list[int] = []

        last_open_sq = text.rfind("[")
        last_close_sq = text.rfind("]")
        if last_open_sq > last_close_sq:
            candidates.append(last_open_sq)

        last_open_rd = text.rfind("(")
        last_close_rd = text.rfind(")")
        if last_open_rd > last_close_rd:
            candidates.append(last_open_rd)

        delay_match = _INCOMPLETE_DELAY_TAIL_RE.search(text)
        if delay_match:
            candidates.append(delay_match.start())

        if not candidates:
            return None
        return min(candidates)

    def _emit_sentence(self) -> PipelineEvent | None:
        sentence = self._normalize_sentence("".join(self._sentence_parts))
        actions = list(self._pending_actions)
        emotions = list(self._pending_emotions)
        delays = list(self._pending_delays)
        self._pending_actions.clear()
        self._pending_emotions.clear()
        self._pending_delays.clear()
        self._sentence_parts.clear()

        if not sentence:
            return None

        metadata: dict[str, str] = {}
        if actions:
            metadata["actions"] = ",".join(actions)
        if emotions:
            metadata["emotions"] = ",".join(emotions)
        if delays:
            metadata["delays"] = ",".join(delays)

        return PipelineEvent(kind="sentence", payload=sentence, metadata=metadata)

    def flush(self) -> list[PipelineEvent]:
        events = self._consume("", final=True)
        if self._buffer:
            clean_tail = re.sub(r"(\[[^\]]*|\([^)]*|!(?:D(?:e(?:l(?:a(?:y\d*)?)?)?)?)?)$", "", self._buffer)
            self._sentence_parts.append(clean_tail)
            self._buffer = ""

        event = self._emit_sentence()
        if event is not None:
            events.append(event)
        return events
