"""Speaks an audio clip through the Ohbot using the AI gesture model instead
of the scripted viseme mouth track: predicts a full pose per control-rate
frame, plays the audio, and steps the predicted pose into the controller in
lockstep with real playback position via drive_pose()/release_pose().
"""

from __future__ import annotations

import asyncio

import numpy as np

from ..robot.controller import ObotController
from ..speech.player import AudioPlayer
from .inference import GestureModel


def _to_float32(samples: np.ndarray) -> np.ndarray:
    if samples.dtype == np.int16:
        return samples.astype(np.float32) / 32768.0
    return samples.astype(np.float32)


def _to_int16(samples: np.ndarray) -> np.ndarray:
    if samples.dtype == np.int16:
        return samples
    return np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)


class AIGestureDriver:
    """Runs one clip end to end: predict pose track, play audio, drive servos."""

    def __init__(self, controller: ObotController, model: GestureModel) -> None:
        self.controller = controller
        self.model = model
        self._player = AudioPlayer()

    async def play(
        self,
        samples: np.ndarray,
        sample_rate: int,
        control_hz: float = 20.0,
        intensity: float = 1.0,
    ) -> None:
        if samples.ndim > 1:
            samples = samples.mean(axis=1)

        prediction = self.model.predict(
            _to_float32(samples), sample_rate, control_hz=control_hz, intensity=intensity
        )
        n_frames = prediction.motion.shape[0]

        self._player.play(_to_int16(samples), sample_rate)
        tick = min(0.05, 1.0 / control_hz)
        try:
            while self._player.active:
                t = self._player.position_s
                frame = min(n_frames - 1, max(0, int(t * control_hz)))
                self.controller.drive_pose(prediction.row_to_pose(prediction.motion[frame]))
                await asyncio.sleep(tick)
        finally:
            self.controller.release_pose()
            if self._player.error is not None:
                raise self._player.error

    def stop(self) -> None:
        """Cut playback short. The pose loop follows the player, so it exits with it."""
        self._player.abort()

    async def play_wav(self, wav_path: str, control_hz: float = 20.0, intensity: float = 1.0) -> None:
        import soundfile as sf

        samples, sample_rate = sf.read(wav_path, dtype="int16", always_2d=False)
        await self.play(samples, sample_rate, control_hz=control_hz, intensity=intensity)
