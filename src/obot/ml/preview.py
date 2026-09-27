"""Plays a checkpoint -- or a recorded training clip -- through a live controller.

The GUI's ML Control page needs to watch a model move the face before committing it to
a conversation, and to compare that against the ground truth beat2_to_ohbot.py extracted
for the same kind of clip. Both paths write absolute joint targets through
``drive_pose()``/``release_pose()``, exactly the way speech drives the AI gesture model,
so what you see here is what a conversation will look like.

One playback at a time per session; :meth:`MLPreview.stop` cuts it at the next frame by
aborting the audio (the pose loop follows playback position, so it ends with it) rather
than cancelling the task, which keeps the release-the-joints path unconditional.

Console sessions have no servos: ``drive_pose`` is a no-op there and only the audio is
heard. The caller (server/session.py) says so in the result rather than refusing.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from . import registry

# Pose frames are stepped no slower than this even at very low control rates, so a
# stop() request is honoured promptly instead of waiting out a long frame.
_MAX_TICK_S = 0.05


class MLPreview:
    """One session's preview slot: at most one model/clip playing at any time."""

    def __init__(self) -> None:
        self._playing: str = ""
        self._driver = None
        self._player = None
        self._stopping = False

    @property
    def active(self) -> bool:
        return bool(self._playing)

    def status(self) -> dict[str, Any]:
        return {"preview_active": self.active, "preview_playing": self._playing}

    def stop(self) -> bool:
        """Cut the current playback short. Returns False when nothing was playing."""
        if not self.active:
            return False
        self._stopping = True
        if self._driver is not None:
            self._driver.stop()
        if self._player is not None:
            self._player.abort()
        return True

    def _begin(self, what: str) -> None:
        if self.active:
            raise RuntimeError(f"a preview is already playing ({self._playing}); stop it first.")
        self._playing = what
        self._stopping = False

    def _end(self) -> None:
        self._playing = ""
        self._stopping = False
        self._driver = None
        self._player = None

    async def play_model(
        self,
        controller,
        *,
        checkpoint: str,
        wav: str,
        control_hz: float = 20.0,
        intensity: float = 1.0,
        device: str = "cpu",
    ) -> dict[str, Any]:
        """Predict a pose track for ``wav`` with ``checkpoint`` and play it out."""
        checkpoint_path = registry.resolve_path(checkpoint)
        wav_path = registry.resolve_path(wav)
        if not checkpoint_path.is_file():
            raise FileNotFoundError(f"no checkpoint at {checkpoint_path}")
        if not wav_path.is_file():
            raise FileNotFoundError(f"no audio file at {wav_path}")

        self._begin(f"model {registry.display_path(checkpoint_path)}")
        started = time.monotonic()
        try:
            from .driver import AIGestureDriver
            from .inference import GestureModel

            # Loading a checkpoint means importing torch (seconds, the first time) and
            # reading the file: both belong off the event loop, or the whole control
            # server -- joint stream included -- stalls while the GUI waits.
            model = await asyncio.to_thread(GestureModel, checkpoint_path, device)
            if self._stopping:
                return self._result(checkpoint_path, wav_path, started, frames=0)

            driver = AIGestureDriver(controller, model)
            self._driver = driver
            await driver.play_wav(
                str(wav_path), control_hz=control_hz, intensity=intensity
            )
            return self._result(checkpoint_path, wav_path, started)
        finally:
            self._end()

    def _result(
        self, checkpoint: Path, wav: Path, started: float, frames: int | None = None
    ) -> dict[str, Any]:
        result = {
            "checkpoint": registry.display_path(checkpoint),
            "wav": registry.display_path(wav),
            "elapsed_s": round(time.monotonic() - started, 2),
            "stopped": self._stopping,
        }
        if frames is not None:
            result["frames"] = frames
        return result

    async def play_clip(
        self,
        controller,
        *,
        clip_path: str,
        speed: float = 1.0,
        play_audio: bool = True,
    ) -> dict[str, Any]:
        """Replay one recorded dataset clip (an .npz from beat2_to_ohbot.py).

        This is ground truth, not a prediction: it shows exactly what the conversion
        script pulled out of a BEAT2 take, which is the reference a model preview is
        judged against.
        """
        import numpy as np

        from ..speech.player import AudioPlayer
        from .replay_dataset import load_clip

        path = registry.resolve_path(clip_path)
        if not path.is_file():
            raise FileNotFoundError(f"no clip at {path}")

        self._begin(f"clip {registry.display_path(path)}")
        started = time.monotonic()
        try:
            clip = await asyncio.to_thread(load_clip, path)
            motion = clip["motion"]
            joint_ids = [registry.AXIS_TO_JOINT.get(name) for name in clip["axis_names"]]
            control_hz = max(1.0, float(clip["control_hz"]) * max(0.05, speed))
            n_frames = int(motion.shape[0])

            if play_audio and clip["audio"] is not None and not self._stopping:
                samples = np.clip(clip["audio"] * 32767.0, -32768, 32767).astype(np.int16)
                self._player = AudioPlayer()
                self._player.play(samples, clip["audio_sr"])

            # Frame index comes from elapsed wall time rather than a frame counter, so
            # a control rate slower than the tick (or a late wake-up) neither speeds the
            # clip up nor drifts away from the audio -- the same approach driver.py uses
            # to follow real playback position.
            tick = min(_MAX_TICK_S, 1.0 / control_hz)
            clip_started = time.monotonic()
            while not self._stopping:
                index = int((time.monotonic() - clip_started) * control_hz)
                if index >= n_frames:
                    break
                pose = {
                    joint_id: float(value)
                    for joint_id, value in zip(joint_ids, motion[index])
                    if joint_id is not None
                }
                if pose:
                    controller.drive_pose(pose)
                await asyncio.sleep(tick)

            return {
                "clip": registry.display_path(path),
                "frames": n_frames,
                "control_hz": round(control_hz, 2),
                "elapsed_s": round(time.monotonic() - started, 2),
                "stopped": self._stopping,
            }
        finally:
            controller.release_pose()
            if self._player is not None:
                self._player.abort()
            self._end()
