from __future__ import annotations

import asyncio
import contextlib

from ..llm.client import LLMClient
from ..robot.actions import ActionRegistry, default_action_registry
from ..robot.controller import ObotController
from .interrupt import InterruptController
from .models import InterruptionResult, SpeechMarker
from .processor import StreamProcessor


def _parse_specs(raw: str) -> list[tuple[str, int]]:
    # Metadata format from the processor: "name@pos,name@pos,..."
    # The integer pos is the character index inside the sentence where the marker appeared,
    # used later to schedule the action or emotion at the matching point during speech.
    specs: list[tuple[str, int]] = []
    for spec in raw.split(","):
        if not spec:
            continue
        if "@" in spec:
            name, pos = spec.split("@", 1)
            try:
                pos_i = int(pos)
            except ValueError:
                pos_i = 0
        else:
            name = spec
            pos_i = 0
        specs.append((name, pos_i))
    return specs


class RobotPipeline:
    """Coordinates the LLM source, text processor, and robot controller.

    A turn runs two cooperating tasks:

    * a **producer** that streams the LLM, feeds the :class:`StreamProcessor`, records
      every generated sentence, queues sentence events for speech, and hints the
      controller so TTS for the *next* sentence renders while the current one plays;
    * a **consumer** (the speech loop) that voices queued sentences one at a time,
      handing each sentence's [Action]/(Emotion) markers to the controller, which
      schedules them at estimated word positions.

    When an :class:`InterruptController` trips, a watcher tells the controller to stop
    the current utterance (the speech engine finishes the word being voiced, then goes
    quiet), the consumer drops every remaining sentence, but the producer keeps
    draining the (cheap, text-only) stream so the full intended message is known.
    The difference between what was generated and what was spoken is "the rest it
    would have said", which is reported back to the LLM via ``register_interruption``.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        controller: ObotController,
        processor: StreamProcessor | None = None,
        action_registry: ActionRegistry | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.controller = controller
        self.processor = processor or StreamProcessor()
        self.action_registry = action_registry or default_action_registry()

    async def run(
        self,
        prompt: str,
        interrupt: InterruptController | None = None,
    ) -> InterruptionResult:
        speech_queue: asyncio.Queue[object | None] = asyncio.Queue()
        generated: list[str] = []
        spoken: list[str] = []
        partial: list[str] = []

        producer = asyncio.create_task(self._produce(prompt, generated, speech_queue))
        consumer = asyncio.create_task(self._speech_loop(speech_queue, spoken, partial, interrupt))

        watcher: asyncio.Task | None = None
        if interrupt is not None:
            watcher = asyncio.create_task(self._interrupt_watcher(interrupt))

        try:
            # Await the producer first: it always finishes the stream (even after an
            # interrupt) and posts the sentinel, so the consumer can then drain and exit.
            await producer
            await consumer
        finally:
            if watcher is not None:
                watcher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watcher
            # Free audio prefetched for sentences that were dropped by an interrupt.
            self.controller.turn_finished()

        interrupted = interrupt is not None and interrupt.is_set()
        unspoken = generated[len(spoken):] if interrupted else []
        if interrupted:
            # Optional protocol method  Gemini/Ollama implement it, Scripted no-ops.
            register = getattr(self.llm_client, "register_interruption", None)
            if callable(register):
                register(spoken, unspoken)

        return InterruptionResult(interrupted=interrupted, spoken=spoken, unspoken=unspoken, partial=partial)

    async def _produce(
        self,
        prompt: str,
        generated: list[str],
        speech_queue: asyncio.Queue[object | None],
    ) -> None:
        try:
            async for chunk in self.llm_client.stream_response(prompt):
                for event in self.processor.feed(chunk):
                    if event.kind == "sentence":
                        generated.append(event.payload)
                        # Prefetch: start synthesizing this sentence's audio now, so
                        # it's ready the moment the speech loop reaches it.
                        self.controller.prepare_sentence(event.payload)
                        await speech_queue.put(event)

            for event in self.processor.flush():
                if event.kind == "sentence":
                    generated.append(event.payload)
                    self.controller.prepare_sentence(event.payload)
                    await speech_queue.put(event)
        finally:
            # Sentinel: always posted so the consumer cannot hang, even if streaming
            # raised partway through.
            await speech_queue.put(None)

    async def _interrupt_watcher(self, interrupt: InterruptController) -> None:
        # Fires stop_speaking the instant the interrupt trips, instead of waiting for the
        # consumer to reach its next-sentence check. The speech engine then stops at the
        # end of the word currently being voiced.
        await interrupt.wait()
        await self.controller.stop_speaking()

    async def _speech_loop(
        self,
        speech_queue: asyncio.Queue[object | None],
        spoken: list[str],
        partial: list[str],
        interrupt: InterruptController | None,
    ) -> None:
        while True:
            event = await speech_queue.get()
            if event is None:
                return
            if event.kind != "sentence":
                continue
            if interrupt is not None and interrupt.is_set():
                # Interrupted: drop this and every later sentence, but keep consuming so
                # the producer's sentinel is reached and the turn can finish cleanly.
                continue

            completed = await self._speak_event(event)
            # Deliver a thread-safe stop queued during an immediately returning
            # custom controller call before deciding completion or starting next.
            await asyncio.sleep(0)
            # Older custom controllers return None; an interrupt makes completion
            # unknown, so do not claim their whole sentence was delivered.
            if completed is False or (completed is None and interrupt is not None and interrupt.is_set()):
                partial.append(event.payload)
            else:
                spoken.append(event.payload)

    async def _speak_event(self, event) -> bool | None:
        sentence = event.payload
        metadata = event.metadata or {}
        action_specs = _parse_specs(metadata.get("actions", ""))
        emotion_specs = _parse_specs(metadata.get("emotions", ""))
        delay_specs = _parse_specs(metadata.get("delays", ""))

        # Emotions placed at the very start of a sentence are applied before speech
        # starts, so the face is already in the right shape for the first word.
        pre_emotions = [name for name, pos in emotion_specs if pos == 0]
        for name in pre_emotions:
            await self.controller.set_emotion(name)

        markers = [
            SpeechMarker(kind="action", name=name, char_pos=pos)
            for name, pos in action_specs
        ] + [
            SpeechMarker(kind="emotion", name=name, char_pos=pos)
            for name, pos in emotion_specs
            if pos > 0
        ]

        async def on_marker(marker: SpeechMarker) -> None:
            if marker.kind == "action":
                await self.action_registry.execute(marker.name, self.controller)
            else:
                await self.controller.set_emotion(marker.name)

        # The controller times the markers: against the real word timeline when it
        # has audio, or a duration estimate when it does not (console mode).
        completed = await self.controller.speak_sentence(sentence, markers, on_marker)

        # A spoken sentence cannot be paused mid utterance once it is handed to TTS,
        # so any !DelayX inside a sentence is treated as a pause AFTER that sentence,
        # before the next one begins. Multiple delays on one sentence are summed.
        total_pause_ms = sum(int(ms) for ms, _ in delay_specs if ms.isdigit())
        if total_pause_ms and completed is not False:
            await asyncio.sleep(total_pause_ms / 1000)
        return completed
