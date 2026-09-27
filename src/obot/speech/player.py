"""Chunked, interruptible audio playback on sounddevice.

The old stack played whole WAVs through winsound with no way to stop them.
Here a worker thread streams the clip in ~20 ms chunks, so:

* :attr:`position_s` exposes a live playback clock (drives lips + timed actions),
* :meth:`stop_at` ends playback at an exact time  the word-boundary stop,
* :meth:`abort` kills it immediately (shutdown / kill-switch).

A short fade is applied to the final chunk so a stop never clicks.
"""

from __future__ import annotations

import threading

import numpy as np

_CHUNK_S = 0.02
_FADE_S = 0.012


class PlaybackError(RuntimeError):
    """Playback device failures (no output device, stream error, ...)."""


class AudioPlayer:
    def __init__(self, device_index: int | None = None) -> None:
        self._device_index = device_index
        self._thread: threading.Thread | None = None
        self._done = threading.Event()
        self._done.set()
        self._abort = threading.Event()
        self._lock = threading.Lock()
        self._stop_at_s: float | None = None
        self._position_s: float = 0.0
        self._latency_s: float = 0.0
        self._error: Exception | None = None

    # -- control ----------------------------------------------------------------------

    def play(self, samples: np.ndarray, sample_rate: int) -> None:
        """Start playing a mono int16 clip. Raises if a clip is already playing."""
        if not self._done.is_set():
            raise PlaybackError("player is busy; wait for the current clip first.")
        self._done.clear()
        self._abort.clear()
        self._error = None
        with self._lock:
            self._stop_at_s = None
            self._position_s = 0.0
        self._thread = threading.Thread(
            target=self._run, args=(samples, sample_rate), daemon=True
        )
        self._thread.start()

    def stop_at(self, t_s: float) -> None:
        """Let playback continue until ``t_s`` (clip time), then stop with a fade."""
        with self._lock:
            # Never extend an earlier stop request.
            if self._stop_at_s is None or t_s < self._stop_at_s:
                self._stop_at_s = max(0.0, t_s)

    def abort(self) -> None:
        self._abort.set()

    # -- state ------------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return not self._done.is_set()

    @property
    def position_s(self) -> float:
        """Estimated position of what is *audible* right now (latency-compensated)."""
        with self._lock:
            return max(0.0, self._position_s - self._latency_s)

    @property
    def error(self) -> Exception | None:
        return self._error

    # -- worker -----------------------------------------------------------------------

    def _run(self, samples: np.ndarray, sample_rate: int) -> None:
        try:
            import sounddevice as sd

            chunk = max(64, int(sample_rate * _CHUNK_S))
            fade = max(16, int(sample_rate * _FADE_S))
            with sd.OutputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                device=self._device_index,
                blocksize=chunk,
            ) as stream:
                with self._lock:
                    # stream.latency = seconds between write() and the speaker cone
                    # moving; folding it in keeps the lips from running ahead of audio.
                    self._latency_s = float(stream.latency or 0.0)

                pos = 0
                total = len(samples)
                while pos < total and not self._abort.is_set():
                    with self._lock:
                        stop_at = self._stop_at_s
                    end = min(pos + chunk, total)
                    if stop_at is not None:
                        stop_frame = int(stop_at * sample_rate)
                        if pos >= stop_frame:
                            break
                        if end >= stop_frame:
                            # Last chunk before the boundary: trim and fade it out.
                            end = min(max(stop_frame, pos + 1), total)
                            block = samples[pos:end].astype(np.float32)
                            ramp = np.ones(len(block), dtype=np.float32)
                            f = min(fade, len(block))
                            ramp[-f:] = np.linspace(1.0, 0.0, f, dtype=np.float32)
                            stream.write(np.ascontiguousarray(block * ramp, dtype=np.float32).astype(np.int16))
                            pos = end
                            with self._lock:
                                self._position_s = pos / sample_rate
                            break
                    stream.write(np.ascontiguousarray(samples[pos:end]))
                    pos = end
                    with self._lock:
                        self._position_s = pos / sample_rate
        except Exception as exc:  # pragma: no cover - host audio dependent
            self._error = PlaybackError(f"audio playback failed: {exc}")
        finally:
            self._done.set()
