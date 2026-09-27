"""Word timing and mouth animation tracks derived from synthesized audio.

Neither TTS engine reports word timestamps, so timing is estimated from the
audio itself: an RMS envelope estimates the speech interval, and words are
distributed over that span by character count. These are estimated timings,
not measured word alignment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from .config import MouthSettings

_WORD_RE = re.compile(r"\S+")


@dataclass(frozen=True)
class WordSpan:
    text: str
    char_start: int  # index into the sentence string
    char_end: int
    start_s: float   # when this word is voiced within the clip
    end_s: float


@dataclass(frozen=True)
class SpeechTimeline:
    words: list[WordSpan]
    duration_s: float

    def time_for_char(self, char_pos: int) -> float:
        """Playback time when the word containing/following char_pos starts."""
        for w in self.words:
            if char_pos < w.char_end:
                return w.start_s
        return self.words[-1].end_s if self.words else 0.0

    def word_end_after(self, t: float) -> float:
        """End time of the word being voiced at time ``t``  the stop boundary.

        In a gap between words, the next word has not started, so ``t`` itself
        is a valid boundary and playback can stop right away.
        """
        for w in self.words:
            if w.start_s <= t < w.end_s:
                return w.end_s
            if t < w.start_s:
                return t
        return t


def envelope(samples: np.ndarray, sample_rate: int, fps: float) -> np.ndarray:
    """Normalised RMS loudness (0..1) at ``fps`` frames per second."""
    if len(samples) == 0:
        return np.zeros(0, dtype=np.float32)
    hop = max(1, int(sample_rate / max(1.0, fps)))
    n_frames = (len(samples) + hop - 1) // hop
    trimmed = np.pad(samples.astype(np.float32), (0, n_frames * hop - len(samples)))
    frames = trimmed.reshape(n_frames, hop)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    peak = float(rms.max())
    if peak <= 0.0:
        return np.zeros(n_frames, dtype=np.float32)
    return (rms / peak).astype(np.float32)


def build_timeline(text: str, samples: np.ndarray, sample_rate: int) -> SpeechTimeline:
    duration = len(samples) / float(sample_rate)
    matches = list(_WORD_RE.finditer(text))
    if not matches or duration <= 0.0:
        return SpeechTimeline(words=[], duration_s=duration)

    # Trim lead-in/tail silence with a coarse envelope so word times line up with
    # the voiced part of the clip, not the file boundaries.
    env = envelope(samples, sample_rate, fps=50.0)
    voiced = np.nonzero(env > 0.08)[0]
    if voiced.size:
        speech_start = voiced[0] / 50.0
        speech_end = min(duration, (voiced[-1] + 1) / 50.0)
    else:
        speech_start, speech_end = 0.0, duration
    span = max(0.0, speech_end - speech_start)

    # Weight each word by its length (+1 for the pause that follows it); short
    # words get proportionally less of the clip than long ones.
    weights = [len(m.group(0)) + 1 for m in matches]
    total = float(sum(weights))

    words: list[WordSpan] = []
    t = speech_start
    for m, w in zip(matches, weights):
        dt = span * (w / total)
        words.append(
            WordSpan(
                text=m.group(0),
                char_start=m.start(),
                char_end=m.end(),
                start_s=t,
                end_s=min(t + dt, duration),
            )
        )
        t += dt
    return SpeechTimeline(words=words, duration_s=duration)


@dataclass(frozen=True)
class MouthTrack:
    """Per-frame mouth openness (0..1) ready to be scaled into lip positions."""

    values: np.ndarray
    fps: float

    def openness_at(self, t: float) -> float:
        if self.values.size == 0:
            return 0.0
        idx = int(t * self.fps)
        if idx < 0 or idx >= self.values.size:
            return 0.0
        return float(self.values[idx])


def build_mouth_track(
    samples: np.ndarray, sample_rate: int, mouth: MouthSettings
) -> MouthTrack:
    """Envelope -> gate -> gamma curve -> attack/release smoothing."""
    env = envelope(samples, sample_rate, mouth.fps)
    if env.size == 0:
        return MouthTrack(values=env, fps=mouth.fps)

    gate = max(0.0, min(0.95, mouth.gate))
    gated = np.where(env <= gate, 0.0, (env - gate) / (1.0 - gate))
    shaped = np.power(gated, max(0.1, mouth.gamma))

    # One-pole smoothing with separate opening (attack) and closing (release)
    # speeds: 1.0 follows instantly, small values glide. Keeps consonant flutter
    # out of the servos while still snapping open on syllable onsets.
    attack = float(np.clip(mouth.attack, 0.05, 1.0))
    release = float(np.clip(mouth.release, 0.05, 1.0))
    out = np.empty_like(shaped)
    level = 0.0
    for i, target in enumerate(shaped):
        coeff = attack if target > level else release
        level += (float(target) - level) * coeff
        out[i] = level
    return MouthTrack(values=out, fps=mouth.fps)
