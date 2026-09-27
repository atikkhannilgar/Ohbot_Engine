from __future__ import annotations

import asyncio
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from ..core import events
from ..core.models import SpeechMarker
from ..speech.config import MotionSettings, SpeechSettings
from ..speech.engine import SpeechEngine, estimate_duration_s
from ..speech.player import PlaybackError
from ..speech.tts import TTSError
from . import emotions, joints

# ohbot is imported lazily inside HardwareObotController.__init__ so the COM port scan
# does not block startup. Module-level None until the hardware controller is first created.
ohbot = None  # type: ignore

MarkerCallback = Callable[[SpeechMarker], Awaitable[None]]


def _import_ohbot(preferred_port: str | None = None) -> None:
    """Import the ohbot module, trying preferred_port first to avoid a slow full scan."""
    global ohbot
    import serial.tools.list_ports as _lp

    _orig = None
    if preferred_port:
        _orig = _lp.comports

        def _preferred_first():
            all_ports = _orig()
            preferred = [p for p in all_ports if p[0] == preferred_port]
            rest = [p for p in all_ports if p[0] != preferred_port]
            return preferred + rest

        _lp.comports = _preferred_first

    try:
        from ohbot import ohbot as _mod
        ohbot = _mod
    except ImportError as exc:
        if "ohbot" in str(exc).lower() or "No module named 'ohbot'" in str(exc):
            ohbot = None
        else:
            raise ImportError(
                f"the 'ohbot' package is installed but a dependency is missing: {exc}"
            ) from exc
    finally:
        if _orig is not None:
            _lp.comports = _orig


@dataclass(slots=True)
class MotionOffset:
    """Relative servo movement request consumed by the mixer thread."""
    joint_id: int
    delta: float
    duration_s: float


class ObotController(ABC):
    """Robot-facing commands live here."""

    # Name of the last emotion whose pose was actually recognised (see
    # emotions.resolve); a plain class attribute so every controller  including
    # motor-less ConsoleObotController  has a sensible default without its own
    # __init__. Subclasses set an instance attribute of the same name on change.
    current_emotion: str = "Neutral"

    @abstractmethod
    async def speak_sentence(
        self,
        sentence: str,
        markers: Sequence[SpeechMarker] = (),
        on_marker: MarkerCallback | None = None,
    ) -> bool | None:
        """Return whether playback completed; None supports older controllers."""

    @abstractmethod
    async def nod(self) -> None: ...

    @abstractmethod
    async def look_left(self) -> None: ...

    @abstractmethod
    async def look_right(self) -> None: ...

    @abstractmethod
    async def blink(self, announce: bool = True) -> None: ...

    @abstractmethod
    async def wink(self) -> None: ...

    @abstractmethod
    async def shake_head(self) -> None: ...

    @abstractmethod
    async def set_emotion(self, emotion: str) -> None: ...

    def prepare_sentence(self, sentence: str) -> None:
        """Hint that this sentence will be spoken soon (TTS prefetch). Optional."""

    def turn_finished(self) -> None:
        """A speaking turn ended; drop cached audio for sentences never voiced."""

    def enqueue_offset(self, joint_id: int, delta: float, duration_s: float) -> bool:
        """Request a temporary servo offset. Returns False when there are no servos.

        This is the public hook behavior modules use for small ambient motions
        (sway, eye wander). Controllers without motors simply ignore it.
        """
        del joint_id, delta, duration_s
        return False

    def set_manual_joint(self, joint_id: int, position: float | None) -> bool:
        """Hold (or release, when ``position`` is None) one joint at an absolute
        position for manual GUI control, overriding ambient behaviors/speech for
        that joint until released. Returns False when there are no servos.
        """
        del joint_id, position
        return False

    def release_all_manual_joints(self) -> None:
        """Release every joint held by :meth:`set_manual_joint`. No-op with no motors."""

    def drive_pose(self, positions: Mapping[int, float]) -> bool:
        """Directly set absolute joint targets (0..10), e.g. one frame of an
        AI-predicted pose. Overrides offsets/lips for exactly the joints given,
        until :meth:`release_pose` hands them back. Returns False when there
        are no servos to drive.

        This is the hook an audio-driven gesture model uses to speak straight
        to the motor mixer instead of going through discrete actions/emotions.
        """
        del positions
        return False

    def release_pose(self, joint_ids: Iterable[int] | None = None) -> None:
        """Stop directly driving the given joints (or all, if None); motion
        returns to the offset/lips mixer."""
        del joint_ids

    async def stop_speaking(self) -> None:
        """Stop current speech at the next word boundary. Override to actually halt TTS."""

    def close(self) -> None:
        """Release hardware resources. Override to actually stop threads/hardware."""


class AnimatedObotController(ObotController):
    """Shared base for controllers with actual joints (hardware servos or the sim face).

    Owns two cooperating pieces:

    * the **motor mixer**  a thread that every ``tick_s`` blends all active
      motion offsets plus the live lip position from speech, applies slew-rate
      limiting so joints travel at a bounded speed instead of snapping, and
      writes only joints that actually changed;
    * the **speech engine**  the custom say(): TTS (Gemini/local), playback,
      mouth animation, word-timed markers, and word-boundary interruption.

    Subclasses implement :meth:`_write_motor` (serial servo write / sim canvas).
    """

    def __init__(
        self,
        speech_settings: SpeechSettings | None = None,
        motion_settings: MotionSettings | None = None,
        gemini_api_key: str = "",
    ) -> None:
        super().__init__()
        self.motion = motion_settings or MotionSettings()
        self.speech = SpeechEngine(speech_settings or SpeechSettings(), gemini_api_key)

        self._offset_requests: list[MotionOffset] = []
        self._offset_lock = threading.Lock()
        # (top_delta, bottom_delta) written by the speech engine's mouth sink;
        # read by the mixer thread. Replaced atomically as a tuple.
        self._lips: tuple[float, float] = (0.0, 0.0)
        # Active emotion's persistent per-joint bias (joint_id -> delta from
        # REST_POSITION), set by set_emotion and read every mixer tick. Replaced
        # atomically as a whole dict -- same pattern as self._lips above -- so the
        # mixer thread never sees a half-written pose.
        # Start from NEUTRAL so rest overrides (e.g. LidBlink open at LIDBLINK_OPEN) apply
        # immediately — waiting for set_emotion left lids stuck at REST_POSITION 5.
        self._emotion_pose: emotions.EmotionPose = dict(emotions.NEUTRAL)
        self.current_emotion = "Neutral"        # joint_id -> absolute position (0..10), set by the GUI's manual control
        # panel. Wins over offsets/lips for that joint until explicitly released.
        self._manual_overrides: dict[int, float] = {}
        self._manual_lock = threading.Lock()
        # Absolute joint targets from drive_pose() (e.g. an AI gesture model),
        # keyed by joint id. Present joints skip offset/lip blending entirely
        # in the mixer and use this value as their target instead.
        self._pose_overrides: dict[int, float] = {}
        self._pose_lock = threading.Lock()
        self._speech_stopped = threading.Event()
        self._stop_event = threading.Event()

        self._mixer_thread = threading.Thread(target=self._mixer_loop, daemon=True)
        self._mixer_thread.start()

    # -- motor mixing ------------------------------------------------------------------

    @abstractmethod
    def _write_motor(self, joint_id: int, position: float, speed: int) -> None:
        """Send one joint position (0..10) to the physical/virtual robot."""

    def enqueue_offset(self, joint_id: int, delta: float, duration_s: float) -> bool:
        duration_s = max(0.0, duration_s)
        with self._offset_lock:
            self._offset_requests.append(
                MotionOffset(joint_id=joint_id, delta=delta, duration_s=duration_s)
            )
        return True

    def set_manual_joint(self, joint_id: int, position: float | None) -> bool:
        with self._manual_lock:
            if position is None:
                self._manual_overrides.pop(joint_id, None)
            else:
                self._manual_overrides[joint_id] = min(10.0, max(0.0, position))
        return True

    def release_all_manual_joints(self) -> None:
        with self._manual_lock:
            self._manual_overrides.clear()

    def drive_pose(self, positions: Mapping[int, float]) -> bool:
        with self._pose_lock:
            self._pose_overrides.update(positions)
        return True

    def release_pose(self, joint_ids: Iterable[int] | None = None) -> None:
        with self._pose_lock:
            if joint_ids is None:
                self._pose_overrides.clear()
            else:
                for j in joint_ids:
                    self._pose_overrides.pop(j, None)

    def _rest_targets(self) -> dict[int, float]:
        """REST_POSITION plus the standing NEUTRAL (or active emotion) bias."""
        targets = {j: joints.REST_POSITION for j in joints.ALL_JOINTS}
        for j, delta in self._emotion_pose.items():
            targets[j] = min(10.0, max(0.0, targets[j] + delta))
        return targets

    def _mixer_loop(self) -> None:
        """Blend offsets + speech lips into joint targets and chase them at a bounded rate."""
        tick = max(0.01, self.motion.tick_s)
        # Seed at the NEUTRAL-biased rest (LidBlink open at LIDBLINK_OPEN) so we don't
        # start half-closed and slew open after ohbot.reset().
        current = self._rest_targets()
        written = dict(current)
        # Joint stream for the GUI face preview, throttled to ~15 Hz and only built
        # when something is actually listening (the console/hardware flow pays nothing).
        last_emit = 0.0
        emit_period = 1.0 / 15.0

        while not self._stop_event.wait(tick):
            targets = {j: joints.REST_POSITION for j in joints.ALL_JOINTS}
            sums = {j: 0.0 for j in joints.ALL_JOINTS}
            counts = {j: 0 for j in joints.ALL_JOINTS}

            with self._offset_lock:
                expired: list[MotionOffset] = []
                for req in self._offset_requests:
                    if req.duration_s <= 0:
                        expired.append(req)
                        continue
                    # Offsets are blended by averaging (baseline counts once), so
                    # overlapping actions soften each other instead of stacking
                    # into a slam past the servo limits.
                    sums[req.joint_id] += req.delta
                    counts[req.joint_id] += 1
                    req.duration_s -= tick
                for req in expired:
                    self._offset_requests.remove(req)

            with self._pose_lock:
                pose_overrides = dict(self._pose_overrides) if self._pose_overrides else None

            for j in joints.ALL_JOINTS:
                if pose_overrides is not None and j in pose_overrides:
                    # An AI-predicted pose speaks straight to the servo for this
                    # joint, bypassing offset/lip blending entirely.
                    targets[j] = pose_overrides[j]
                else:
                    if counts[j] == 0:
                        counts[j] = 1

                    targets[j] = joints.REST_POSITION + sums[j] / counts[j]

            # Speech lips ride on top of whatever the offsets decided (an emotion
            # can hold the mouth corners while the visemes open/close it) --
            # unless a pose override already owns that joint.
            lip_top, lip_bottom = self._lips
            if pose_overrides is None or joints.TOPLIP not in pose_overrides:
                targets[joints.TOPLIP] += lip_top
            if pose_overrides is None or joints.BOTTOMLIP not in pose_overrides:
                targets[joints.BOTTOMLIP] += lip_bottom

            # Active emotion nudges the resting pose itself: everything computed
            # above (ambient offsets, lips) targets a plain neutral rest, so adding
            # the bias here carries it along -- the face keeps blinking/talking/
            # wandering normally, just around a shifted baseline instead of dead center.
            if self._emotion_pose:
                for j, delta in self._emotion_pose.items():
                    targets[j] += delta

            # Manual GUI overrides win outright: a held joint ignores behaviors,
            # offsets and speech lips until the GUI releases it.
            with self._manual_lock:
                if self._manual_overrides:
                    targets.update(self._manual_overrides)

            for j in joints.ALL_JOINTS:
                target = min(10.0, max(0.0, targets[j]))
                # Slew-rate limiting: travel toward the target at a bounded
                # positions-per-second speed so motion is smooth, not snappy.
                # Lips and lids use a much higher rate  visemes and blinks
                # have to hit their pose within a frame or two.
                rate = (
                    self.motion.lip_rate_limit
                    if j in joints.FAST_JOINTS
                    else self.motion.rate_limit
                )
                max_step = rate * tick
                step = min(max_step, max(-max_step, target - current[j]))
                current[j] += step

                if abs(current[j] - written[j]) >= self.motion.write_epsilon:
                    self._write_motor(j, current[j], self.motion.move_speed)
                    written[j] = current[j]

            # Stream the smoothed pose so a GUI can mirror the face. Gated so the
            # dict is not even built when unobserved; throttled below the tick rate.
            now = time.monotonic()
            if now - last_emit >= emit_period and events.has_subscribers(events.JOINTS):
                last_emit = now
                events.emit(
                    events.JOINTS,
                    {joints.JOINT_NAMES[j]: round(current[j], 3) for j in joints.ALL_JOINTS},
                )

    # -- speech ------------------------------------------------------------------------

    def _set_lips(self, top_delta: float, bottom_delta: float) -> None:
        self._lips = (top_delta, bottom_delta)

    def _set_pose(self, positions: Mapping[str, float]) -> None:
        """pose_sink for the speech engine's AI gesture model: axis names -> joint ids."""
        from ..ml.inference import AXIS_TO_JOINT  # torch already loaded once gesture mode is on

        joint_positions = {
            AXIS_TO_JOINT[name]: value for name, value in positions.items() if name in AXIS_TO_JOINT
        }
        if joint_positions:
            self.drive_pose(joint_positions)

    def prepare_sentence(self, sentence: str) -> None:
        if any(ch.isalnum() for ch in sentence):
            self.speech.prepare(sentence)

    def turn_finished(self) -> None:
        self.speech.discard_prefetches()

    async def speak_sentence(
        self,
        sentence: str,
        markers: Sequence[SpeechMarker] = (),
        on_marker: MarkerCallback | None = None,
    ) -> bool:
        print(f"[speech] {sentence}")
        # Announce the sentence up front so a GUI shows the bot bubble with no latency;
        # the active engine is only known once synthesis returns (emitted below).
        events.emit(events.SPEECH, {"text": sentence, "event": "spoken", "engine": None})
        # Cleared per sentence so a stop from the previous sentence doesn't suppress this one.
        self._speech_stopped.clear()

        if not any(ch.isalnum() for ch in sentence):
            await asyncio.sleep(0.3)
            return not self._speech_stopped.is_set()

        try:
            result = await self.speech.speak(
                sentence, markers=markers, on_marker=on_marker,
                mouth_sink=self._set_lips, pose_sink=self._set_pose,
            )
            if not result.completed:
                print("[speech] (cut off at word boundary)")
            events.emit(events.SPEECH, {
                "text": sentence,
                "event": "cutoff" if not result.completed else "done",
                "engine": result.engine,
            })
            return result.completed
        except (TTSError, PlaybackError) as exc:
            # No audio possible: keep the conversation alive with simulated pacing
            # so sentences, interrupts and turn-taking still behave sensibly.
            print(f"[speech] audio unavailable ({exc}); simulating timing.")
            events.emit(events.LOG, {"level": "warn", "message": f"audio unavailable ({exc}); simulating timing."})
            await self._simulate_sentence(sentence, markers, on_marker)
            completed = not self._speech_stopped.is_set()
            events.emit(events.SPEECH, {"text": sentence, "event": "done" if completed else "cutoff", "engine": "simulated-pacing"})
            return completed
        finally:
            # Hand any AI-driven joints back to the offset/lips mixer; harmless
            # no-op if this sentence never used drive_pose().
            self.release_pose()

    async def _simulate_sentence(
        self,
        sentence: str,
        markers: Sequence[SpeechMarker],
        on_marker: MarkerCallback | None,
    ) -> None:
        duration = estimate_duration_s(sentence, self.speech.settings.estimate_wpm)
        pending = sorted(markers, key=lambda m: m.char_pos)
        fired: list[asyncio.Task] = []
        elapsed = 0.0
        step = 0.05
        length = max(1, len(sentence))
        while elapsed < duration:
            if self._speech_stopped.is_set():
                break
            while pending and (pending[0].char_pos / length) * duration <= elapsed:
                marker = pending.pop(0)
                if on_marker is not None:
                    fired.append(asyncio.create_task(on_marker(marker)))
            await asyncio.sleep(step)
            elapsed += step
        if fired:
            await asyncio.gather(*fired, return_exceptions=True)

    async def stop_speaking(self) -> None:
        self._speech_stopped.set()
        self.speech.request_stop()

    def close(self) -> None:
        # Defensive: if __init__ bailed early these attributes may not exist,
        # and __del__ must not raise during garbage collection.
        speech = getattr(self, "speech", None)
        if speech is not None:
            speech.close()
        stop_event = getattr(self, "_stop_event", None)
        if stop_event is not None:
            stop_event.set()
        mixer = getattr(self, "_mixer_thread", None)
        if mixer is not None and mixer.is_alive():
            mixer.join(timeout=1.0)

    def __del__(self) -> None:
        self.close()

    # -- movement actions ---------------------------------------------------------------
    # Each action feeds offset requests into the mixer: joint id, delta, duration.

    async def nod(self) -> None:
        print("[action] nod")
        events.emit(events.ACTION, {"name": "nod"})

        self.enqueue_offset(joints.HEADNOD, +3, 0.5)
        await asyncio.sleep(0.5)
        self.enqueue_offset(joints.HEADNOD, -3, 0.75)
        await asyncio.sleep(0.75)

    async def look_left(self) -> None:
        print("[action] look_left")
        events.emit(events.ACTION, {"name": "look_left"})
        self.enqueue_offset(joints.EYETURN, +5.0, 1.5)
        await asyncio.sleep(1.5)

    async def look_right(self) -> None:
        print("[action] look_right")
        events.emit(events.ACTION, {"name": "look_right"})
        self.enqueue_offset(joints.EYETURN, -5.0, 1.5)
        await asyncio.sleep(1.5)

    async def blink(self, announce: bool = True) -> None:
        if announce:
            print("[action] blink")
            # Only script/marker-driven blinks are announced; ambient auto_blink
            # passes announce=False so it stays off both the console and the event feed.
            events.emit(events.ACTION, {"name": "blink"})
        self.enqueue_offset(joints.LIDBLINK, -15.0, 0.5)
        await asyncio.sleep(0.5)

    async def wink(self) -> None:
        # Obot has a single shared lid servo, so a wink is rendered as a quick,
        # snappier blink  the closest the hardware can manage.
        print("[action] wink")
        events.emit(events.ACTION, {"name": "wink"})
        self.enqueue_offset(joints.LIDBLINK, -10.0, 0.2)
        await asyncio.sleep(0.3)

    async def shake_head(self) -> None:
        print("[action] shake_head")
        events.emit(events.ACTION, {"name": "shake_head"})
        self.enqueue_offset(joints.HEADTURN, -2.0, 0.5)
        self.enqueue_offset(joints.EYETURN, +2.0, 0.5)
        await asyncio.sleep(0.5)
        self.enqueue_offset(joints.HEADTURN, +2.0, 1.0)
        self.enqueue_offset(joints.EYETURN, -2.0, 1.0)
        await asyncio.sleep(1)
        self.enqueue_offset(joints.HEADTURN, -2.0, 0.5)
        self.enqueue_offset(joints.EYETURN, +2.0, 0.5)
        await asyncio.sleep(0.5)

    async def set_emotion(self, emotion: str) -> None:
        print(f"[emotion] {emotion}")
        # Always announce the raw name -- the transcript chip shows whatever the
        # LLM wrote even if it doesn't map to a recognised pose below.
        events.emit(events.EMOTION, {"name": emotion})
        # combined_pose layers NEUTRAL's rest-position override underneath the
        # named emotion's own deltas, so recalibrating NEUTRAL shifts every
        # emotion's baseline (see emotions.py), not just the plain Neutral state.
        pose = emotions.combined_pose(emotion)
        if pose is None:
            return
        # Persistent until the next set_emotion call: unlike enqueue_offset, this
        # does not decay, so the face holds the pose for as long as the emotion
        # is active (see the mixer's self._emotion_pose blend in _mixer_loop).
        self.current_emotion = emotion
        self._emotion_pose = pose


class HardwareObotController(AnimatedObotController):
    """Drives the physical Obot via the ohbot library's servo commands.

    Speech no longer goes through ohbot.say(): audio comes from the
    SpeechEngine (Gemini TTS or the local voice) played on the host's audio
    output, and the lips are driven by the mixer like every other joint.
    """

    def __init__(
        self,
        port: str | None = None,
        speech_settings: SpeechSettings | None = None,
        motion_settings: MotionSettings | None = None,
        gemini_api_key: str = "",
    ):
        global ohbot
        if ohbot is None:
            _import_ohbot(port)
        if ohbot is None:
            raise RuntimeError(
                "the 'ohbot' library is not installed, so the hardware controller "
                "cannot start. Install it on the robot/Pi, use --sim for the digital "
                "face, or ConsoleObotController (the demo falls back to it automatically)."
            )

        # Serialise access to the ohbot library, which is not thread-safe.
        self._ohbot_lock = threading.Lock()
        with self._ohbot_lock:
            ohbot.reset()
            # reset() may park LidBlink at the OMD RestPosition (often 10). The mixer
            # then drives to NEUTRAL open lids (LIDBLINK_OPEN = 7 on this build).

        super().__init__(
            speech_settings=speech_settings,
            motion_settings=motion_settings,
            gemini_api_key=gemini_api_key,
        )

    def _write_motor(self, joint_id: int, position: float, speed: int) -> None:
        try:
            with self._ohbot_lock:
                ohbot.move(joint_id, position, speed)
        except (OSError, Exception) as exc:
            if "serial" in type(exc).__module__.lower() or isinstance(exc, OSError):
                if not getattr(self, "_serial_error_logged", False):
                    self._serial_error_logged = True
                    print(f"[hardware] serial write failed: {exc}")
                    events.emit(events.LOG, {
                        "level": "error",
                        "message": f"serial connection lost: {exc}",
                    })
            else:
                raise


class SimulatedObotController(AnimatedObotController):
    """Digital twin: identical motion/speech pipeline, rendered in the sim window.

    Everything (mixer, speech, lips, behaviors) behaves exactly like the
    hardware controller  only :meth:`_write_motor` differs, painting a tkinter
    face instead of writing servo serial commands. Audio still plays on the
    host speakers, so lip-sync and interruption can be tested without a robot.
    """

    def __init__(
        self,
        face,
        speech_settings: SpeechSettings | None = None,
        motion_settings: MotionSettings | None = None,
        gemini_api_key: str = "",
    ) -> None:
        # Duck-typed face: anything with set_motor(joint_id, position). Normally a
        # :class:`obot.sim.face.FaceWindow`.
        self._face = face
        super().__init__(
            speech_settings=speech_settings,
            motion_settings=motion_settings,
            gemini_api_key=gemini_api_key,
        )

    def _write_motor(self, joint_id: int, position: float, speed: int) -> None:
        del speed
        self._face.set_motor(joint_id, position)

    def close(self) -> None:
        super().close()
        face = getattr(self, "_face", None)
        if face is not None and hasattr(face, "close"):
            face.close()


class VirtualObotController(AnimatedObotController):
    """Headless twin: the full motor mixer + speech pipeline with no on-host window.

    Identical to :class:`SimulatedObotController` in every way that matters  mixer,
    slew limiting, real TTS audio on the host speakers, lip-sync, behaviors  but it
    renders nowhere. The joint positions are streamed on the ``joints`` event topic
    instead, so a remote GUI can draw the face itself (``--serve`` + face preview).
    This is the sensible controller for the control server on a machine without the
    robot and without wanting the tkinter sim window to pop up.
    """

    def _write_motor(self, joint_id: int, position: float, speed: int) -> None:
        # No physical or on-screen output: the mixer still computes and emits every
        # joint's position (see _mixer_loop), which is all a GUI face preview needs.
        del joint_id, position, speed


class ConsoleObotController(ObotController):
    """Hardware-free controller: prints what the robot *would* do and simulates timing.

    This is the reusable "run the whole program without an Obot" path  it needs no
    ohbot library, no servos, and no audio output, so the full pipeline (LLM
    streaming, the processor, interruption, and microphone input) can be exercised
    on a plain dev machine. Speech "playback" is modelled as a short sleep, and
    :meth:`stop_speaking` lets an interrupt cut that simulated playback short,
    mirroring the hardware contract.
    """

    def __init__(self) -> None:
        super().__init__()
        # Tripped by stop_speaking so an in-flight simulated utterance ends early and a
        # still-queued one is skipped  the same semantics as the hardware controller.
        self._speech_stopped = threading.Event()

    async def speak_sentence(
        self,
        sentence: str,
        markers: Sequence[SpeechMarker] = (),
        on_marker: MarkerCallback | None = None,
    ) -> bool:
        print(f"[speech] {sentence}")
        events.emit(events.SPEECH, {"text": sentence, "event": "spoken", "engine": "console"})
        self._speech_stopped.clear()
        # Roughly track real TTS pacing so barge-in timing feels realistic, but poll the
        # stop flag so an interrupt can cut the "playback" mid-sentence.
        estimated_duration = min(0.2 + len(sentence) / 80, 1.5)
        pending = sorted(markers, key=lambda m: m.char_pos)
        fired: list[asyncio.Task] = []
        length = max(1, len(sentence))
        elapsed = 0.0
        step = 0.05
        cut_off = False
        while elapsed < estimated_duration:
            if self._speech_stopped.is_set():
                print("[speech] (cut off)")
                cut_off = True
                break
            while pending and (pending[0].char_pos / length) * estimated_duration <= elapsed:
                marker = pending.pop(0)
                if on_marker is not None:
                    fired.append(asyncio.create_task(on_marker(marker)))
            await asyncio.sleep(step)
            elapsed += step
        else:
            # Finished naturally: fire whatever was anchored to the sentence end.
            for marker in pending:
                if on_marker is not None:
                    fired.append(asyncio.create_task(on_marker(marker)))
        events.emit(events.SPEECH, {
            "text": sentence,
            "event": "cutoff" if cut_off else "done",
            "engine": "console",
        })
        if fired:
            await asyncio.gather(*fired, return_exceptions=True)
        return not cut_off

    async def stop_speaking(self) -> None:
        self._speech_stopped.set()

    async def nod(self) -> None:
        print("[action][sim] nod")
        events.emit(events.ACTION, {"name": "nod"})
        await asyncio.sleep(0.3)

    async def look_left(self) -> None:
        print("[action][sim] look_left")
        events.emit(events.ACTION, {"name": "look_left"})
        await asyncio.sleep(0.3)

    async def look_right(self) -> None:
        print("[action][sim] look_right")
        events.emit(events.ACTION, {"name": "look_right"})
        await asyncio.sleep(0.3)

    async def blink(self, announce: bool = True) -> None:
        if announce:
            print("[action][sim] blink")
            events.emit(events.ACTION, {"name": "blink"})
        await asyncio.sleep(0.2)

    async def wink(self) -> None:
        print("[action][sim] wink")
        events.emit(events.ACTION, {"name": "wink"})
        await asyncio.sleep(0.2)

    async def shake_head(self) -> None:
        print("[action][sim] shake_head")
        events.emit(events.ACTION, {"name": "shake_head"})
        await asyncio.sleep(0.4)

    async def set_emotion(self, emotion: str) -> None:
        print(f"[emotion][sim] {emotion}")
        events.emit(events.EMOTION, {"name": emotion})
        if emotions.resolve(emotion) is not None:
            self.current_emotion = emotion
