"""The custom say(): synthesis + playback + lips + precisely timed markers.

One :class:`SpeechEngine` instance owns the TTS chain and the audio player.
For every sentence it:

1. synthesizes PCM (Gemini or local voice, with prefetch so the next sentence
   is already rendered while the current one plays),
2. builds a word timeline and a mouth-openness track from the real audio,
3. streams playback while driving a ``mouth_sink`` (lip servo deltas) and
   firing ``markers`` ([Nod], (Happy), ...) at the exact word they were
   written on,
4. honours :meth:`request_stop` by stopping at the end of the current word.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from ..core.models import SpeechMarker
from .config import AIGestureSettings, SpeechSettings
from .player import AudioPlayer, PlaybackError
from .timeline import MouthTrack, SpeechTimeline, build_mouth_track, build_timeline
from .tts import TTSError, build_tts

if TYPE_CHECKING:
    from ..ml.inference import GestureModel, GesturePrediction

MouthSink = Callable[[float, float], None]  # (top_delta, bottom_delta) above rest
PoseSink = Callable[[Mapping[str, float]], None]  # {axis_name: absolute position 0..10}
MarkerCallback = Callable[[SpeechMarker], Awaitable[None]]


@dataclass(frozen=True)
class SpeechClip:
    text: str
    samples: np.ndarray
    sample_rate: int
    timeline: SpeechTimeline
    mouth: MouthTrack
    engine_name: str
    # None unless speech.gesture.enabled and the model loaded/predicted successfully --
    # when present, speak() drives pose_sink from this instead of the envelope mouth track.
    pose: "GesturePrediction | None" = None


@dataclass(frozen=True)
class SpeakResult:
    completed: bool          # False = cut off at a word boundary
    spoken_duration_s: float
    total_duration_s: float
    engine: str


def estimate_duration_s(text: str, wpm: float) -> float:
    """Pacing guess used when no real audio exists (console mode, TTS failure)."""
    words = max(1, len(text.split()))
    return words / max(60.0, wpm) * 60.0 + 0.3


class SpeechEngine:
    def __init__(self, settings: SpeechSettings, gemini_api_key: str = "") -> None:
        self.settings = settings
        self._tts = build_tts(settings.tts, gemini_api_key)
        self._player = AudioPlayer(settings.output_device_index)
        self._prefetch: dict[str, asyncio.Task[SpeechClip]] = {}
        # At most two synth calls in flight: the sentence about to play and the next.
        self._synth_sem = asyncio.Semaphore(2)
        self._stop_requested = False
        self._gesture_model = self._build_gesture_model(settings.gesture)
        # What the loaded model was built from, so reload_gesture_model() can tell a
        # real change from a config save that touched something else entirely.
        self._gesture_key = self._gesture_settings_key(settings.gesture)
        self._gesture_checkpoint = (
            settings.gesture.checkpoint_path if self._gesture_model is not None else None
        )

    @staticmethod
    def _gesture_settings_key(settings: AIGestureSettings) -> tuple:
        """The settings that decide *which* model object is in memory. intensity and
        control_hz are deliberately absent: those are read per sentence in
        _predict_pose(), so editing them already applies live with no reload."""
        return (settings.enabled, settings.checkpoint_path, settings.device)

    @property
    def gesture_checkpoint(self) -> str | None:
        """Checkpoint currently loaded, or None when the scripted mouth track is in use."""
        return self._gesture_checkpoint

    def reload_gesture_model(self, force: bool = False) -> bool:
        """Rebuild the AI gesture model from the live ``settings.gesture``.

        The control server mutates the config in place, which is enough for the
        per-sentence knobs -- but enabling the feature, pointing it at another
        checkpoint, or switching device only takes effect when the model object is
        rebuilt, which normally happens once at session start. This is how the GUI's
        ML Control page applies those to a running session. Pass ``force`` to reload
        the same path again after re-training it. Returns True when a model is loaded
        afterwards. Blocking (imports torch, reads the file): call it off the loop.
        """
        settings = self.settings.gesture
        key = self._gesture_settings_key(settings)
        if not force and key == self._gesture_key:
            return self._gesture_model is not None

        self._gesture_key = key
        self._gesture_model = self._build_gesture_model(settings)
        self._gesture_checkpoint = (
            settings.checkpoint_path if self._gesture_model is not None else None
        )
        return self._gesture_model is not None

    @staticmethod
    def _build_gesture_model(settings: AIGestureSettings) -> "GestureModel | None":
        if not settings.enabled or not settings.checkpoint_path:
            return None
        try:
            # torch is heavy and optional -- only imported when gesture driving is on.
            from ..ml.inference import GestureModel

            return GestureModel(settings.checkpoint_path, device=settings.device)
        except Exception as exc:  # noqa: BLE001 - any load failure just disables the feature
            print(f"[speech] AI gesture model unavailable ({exc}); using the scripted mouth track.")
            return None

    def _predict_pose(self, samples: np.ndarray, sample_rate: int) -> "GesturePrediction | None":
        if self._gesture_model is None:
            return None
        try:
            audio = samples.astype(np.float32) / 32768.0
            return self._gesture_model.predict(
                audio, sample_rate,
                control_hz=self.settings.gesture.control_hz,
                intensity=self.settings.gesture.intensity,
            )
        except Exception as exc:  # noqa: BLE001 - fall back to the mouth track for this sentence
            print(f"[speech] AI gesture prediction failed ({exc}); using the scripted mouth track.")
            return None

    # -- synthesis --------------------------------------------------------------------

    def prepare(self, text: str) -> None:
        """Start synthesizing ``text`` in the background (called as sentences stream in).

        By the time the speech loop reaches this sentence the audio is usually
        ready, which hides the Gemini TTS round-trip behind the previous
        sentence's playback.
        """
        key = text.strip()
        if not key or key in self._prefetch:
            return
        task = asyncio.create_task(self._synthesize(key))
        # Retrieve exceptions if the sentence is later dropped by an interrupt,
        # so abandoned prefetches never warn "exception was never retrieved".
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
        self._prefetch[key] = task

    async def synthesize(self, text: str) -> SpeechClip:
        key = text.strip()
        task = self._prefetch.pop(key, None)
        if task is not None:
            return await task
        return await self._synthesize(key)

    async def _synthesize(self, text: str) -> SpeechClip:
        async with self._synth_sem:
            result = await self._tts.synthesize(text)
        return SpeechClip(
            text=text,
            samples=result.samples,
            sample_rate=result.sample_rate,
            timeline=build_timeline(text, result.samples, result.sample_rate),
            mouth=build_mouth_track(result.samples, result.sample_rate, self.settings.mouth),
            pose=self._predict_pose(result.samples, result.sample_rate),
            engine_name=result.engine,
        )

    def discard_prefetches(self) -> None:
        """Cancel synthesis queued for sentences that will no longer be spoken."""
        for task in self._prefetch.values():
            task.cancel()
        self._prefetch.clear()

    # -- speaking ---------------------------------------------------------------------

    async def speak(
        self,
        text: str,
        markers: Sequence[SpeechMarker] = (),
        on_marker: MarkerCallback | None = None,
        mouth_sink: MouthSink | None = None,
        pose_sink: PoseSink | None = None,
    ) -> SpeakResult:
        """Speak one sentence. Raises TTSError/PlaybackError if audio is impossible."""
        self._stop_requested = False
        clip = await self.synthesize(text)
        mouth_cfg = self.settings.mouth

        # Char positions -> playback times, kept in written order for equal times.
        timed = sorted(
            ((clip.timeline.time_for_char(m.char_pos), i, m) for i, m in enumerate(markers)),
            key=lambda item: (item[0], item[1]),
        )

        self._player.play(clip.samples, clip.sample_rate)
        fired: list[asyncio.Task] = []
        stop_applied = False
        next_marker = 0
        tick = max(0.01, min(0.05, 1.0 / max(1.0, mouth_cfg.fps)))

        try:
            while self._player.active:
                t = self._player.position_s

                if self._stop_requested and not stop_applied:
                    boundary = clip.timeline.word_end_after(t) + self.settings.word_stop_pad_s
                    self._player.stop_at(boundary)
                    stop_applied = True

                # Once the cut is in motion, no further gestures  a nod firing
                # during the fade-out would look like the robot ignoring the user.
                while (
                    not stop_applied
                    and next_marker < len(timed)
                    and timed[next_marker][0] <= t
                ):
                    marker = timed[next_marker][2]
                    if on_marker is not None:
                        fired.append(asyncio.create_task(on_marker(marker)))
                    next_marker += 1

                if clip.pose is not None and pose_sink is not None:
                    frame = min(
                        clip.pose.motion.shape[0] - 1,
                        max(0, int(t * clip.pose.control_hz)),
                    )
                    pose = dict(zip(clip.pose.axis_names, clip.pose.motion[frame].tolist()))
                    if self.settings.gesture.scripted_mouth:
                        pose.pop("TOPLIP", None)
                        pose.pop("BOTTOMLIP", None)
                    pose_sink(pose)
                    if self.settings.gesture.scripted_mouth and mouth_sink is not None:
                        openness = clip.mouth.openness_at(t + mouth_cfg.sync_offset_s)
                        mouth_sink(
                            min(openness * mouth_cfg.top_gain, mouth_cfg.top_max_delta),
                            min(openness * mouth_cfg.bottom_gain, mouth_cfg.bottom_max_delta),
                        )
                elif mouth_sink is not None:
                    openness = clip.mouth.openness_at(t + mouth_cfg.sync_offset_s)
                    mouth_sink(
                        min(openness * mouth_cfg.top_gain, mouth_cfg.top_max_delta),
                        min(openness * mouth_cfg.bottom_gain, mouth_cfg.bottom_max_delta),
                    )

                await asyncio.sleep(tick)
        finally:
            if mouth_sink is not None:
                mouth_sink(0.0, 0.0)

        if self._player.error is not None:
            # Playback broke (usually: no output device). Raise before firing the
            # trailing markers  the controller falls back to simulated pacing and
            # fires the full marker list there instead.
            if fired:
                await asyncio.gather(*fired, return_exceptions=True)
            raise self._player.error

        # Completed normally: markers sitting on the final word / trailing
        # punctuation may not have fired inside the loop  fire them now.
        if not stop_applied and on_marker is not None:
            for _, _, marker in timed[next_marker:]:
                fired.append(asyncio.create_task(on_marker(marker)))

        if fired:
            await asyncio.gather(*fired, return_exceptions=True)

        return SpeakResult(
            completed=not stop_applied,
            spoken_duration_s=self._player.position_s,
            total_duration_s=clip.timeline.duration_s,
            engine=clip.engine_name,
        )

    def request_stop(self) -> None:
        """Graceful interrupt: finish the current word, then go quiet."""
        self._stop_requested = True

    def abort(self) -> None:
        """Hard stop (shutdown/kill-switch): silence immediately."""
        self._stop_requested = True
        self._player.abort()

    def close(self) -> None:
        self.abort()
        self.discard_prefetches()
        self._tts.close()
