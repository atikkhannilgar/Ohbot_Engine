"""Hardware-free checks against the unmodified review snapshot.

Run from the engine root: python -m unittest discover -s tests -p test_revision_validation.py -v
Use an editable installation or set PYTHONPATH=src.
Synthetic PCM and a fake playback clock test software policy, not acoustic alignment.
"""
import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from obot.core.models import SpeechMarker
from obot.core.processor import StreamProcessor
from obot.robot.controller import AnimatedObotController, MotionOffset
from obot.robot import joints
from obot.speech.config import SpeechSettings
from obot.speech.engine import SpeechEngine, SpeechClip
from obot.speech.timeline import build_timeline, build_mouth_track


class ParserChecks(unittest.TestCase):
    def test_all_two_chunk_splits(self):
        text = '(Happy) Let us try [Nod] the next step.'
        for split in range(len(text) + 1):
            with self.subTest(split=split):
                p = StreamProcessor()
                out = p.feed(text[:split]) + p.feed(text[split:]) + p.flush()
                self.assertEqual(len(out), 1)
                self.assertEqual(out[0].payload, 'Let us try the next step.')
                self.assertEqual(out[0].metadata, {'actions': 'Nod@10', 'emotions': 'Happy@0'})


class OneTick:
    def __init__(self): self.calls = 0
    def wait(self, tick):
        self.calls += 1
        return self.calls > 1


def mixed_target(offsets=(), pose=None, bias=0, manual=None, rate=10000):
    # Invoke the original mixer for one controlled tick; suppress only hardware I/O.
    c = SimpleNamespace()
    c.motion = SimpleNamespace(tick_s=.02, rate_limit=rate, lip_rate_limit=rate,
                               write_epsilon=0, move_speed=5)
    c._offset_requests = [MotionOffset(joints.HEADNOD, d, 1) for d in offsets]
    c._offset_lock = threading.Lock()
    c._pose_lock = threading.Lock()
    c._manual_lock = threading.Lock()
    c._pose_overrides = {} if pose is None else {joints.HEADNOD: pose}
    c._manual_overrides = {} if manual is None else {joints.HEADNOD: manual}
    c._emotion_pose = {joints.HEADNOD: bias}
    c._lips = (0., 0.)
    c._stop_event = OneTick()
    c._rest_targets = lambda: {j: 5. for j in joints.ALL_JOINTS}
    written = {}
    c._write_motor = lambda j, p, speed: written.update({j: p})
    AnimatedObotController._mixer_loop(c)
    return written[joints.HEADNOD]


class MixerChecks(unittest.TestCase):
    def test_overlapping_offsets_are_averaged(self):
        self.assertEqual(mixed_target(offsets=(2, -1)), 5.5)
    def test_predicted_pose_overrides_offsets(self):
        self.assertEqual(mixed_target(offsets=(2,), pose=3), 3)
    def test_expression_bias_follows_predicted_pose(self):
        self.assertEqual(mixed_target(offsets=(2,), pose=3, bias=1), 4)
    def test_manual_override_wins(self):
        self.assertEqual(mixed_target(offsets=(2,), pose=3, bias=1, manual=8), 8)
    def test_targets_are_clamped(self):
        self.assertEqual(mixed_target(pose=14), 10)
        self.assertEqual(mixed_target(pose=-4), 0)
    def test_slew_rate_limits_single_tick(self):
        self.assertAlmostEqual(mixed_target(pose=10, rate=2), 5.04)


class TimelineChecks(unittest.TestCase):
    def test_known_synthetic_speech_interval(self):
        # 0.2 s silence, 1.0 s constant signal, 0.2 s silence at 16 kHz.
        pcm = np.r_[np.zeros(3200), np.ones(16000)*1000, np.zeros(3200)].astype(np.int16)
        t = build_timeline('one three', pcm, 16000)
        self.assertAlmostEqual(t.words[0].start_s, .2)
        self.assertAlmostEqual(t.words[1].start_s, .6)  # weights 4 and 6
        self.assertAlmostEqual(t.words[-1].end_s, 1.2)
        self.assertAlmostEqual(t.time_for_char(3), .6)


class FakePlayer:
    error = None
    def __init__(self, engine, stop=False):
        self.engine, self.should_stop = engine, stop
        self.times = [0., .2, .4, .6, .8, 1.]
        self.i, self.position_s, self.boundary = 0, 0., None
    def play(self, samples, sample_rate): pass
    @property
    def active(self):
        if self.i >= len(self.times): return False
        self.position_s = self.times[self.i]
        self.i += 1
        if self.boundary is not None and self.position_s >= self.boundary:
            self.position_s = self.boundary
            return False
        if self.should_stop and self.position_s >= .2:
            self.engine.request_stop()
        return True
    def stop_at(self, boundary): self.boundary = boundary


class PlaybackChecks(unittest.IsolatedAsyncioTestCase):
    async def run_clip(self, stop=False):
        e = SpeechEngine.__new__(SpeechEngine)
        e.settings = SpeechSettings()
        e.settings.word_stop_pad_s = 0
        e._stop_requested = False
        pcm = np.ones(16000, dtype=np.int16)*1000
        clip = SpeechClip('one two', pcm, 16000, build_timeline('one two', pcm, 16000),
                          build_mouth_track(pcm, 16000, e.settings.mouth), 'synthetic')
        async def synthesize(text): return clip
        e.synthesize = synthesize
        e._player = FakePlayer(e, stop)
        called = []
        async def marker(m): called.append(m.name)
        original_sleep = asyncio.sleep
        async def yield_only(delay): await original_sleep(0)
        with patch('obot.speech.engine.asyncio.sleep', yield_only):
            result = await e.speak('one two', [SpeechMarker('action', 'Nod', 0),
                                              SpeechMarker('action', 'Blink', 4)], marker)
        return result, called, e._player.boundary
    async def test_markers_dispatch_in_order(self):
        result, called, boundary = await self.run_clip()
        self.assertTrue(result.completed)
        self.assertEqual(called, ['Nod', 'Blink'])
        self.assertIsNone(boundary)
    async def test_stop_boundary_suppresses_future_marker(self):
        result, called, boundary = await self.run_clip(stop=True)
        self.assertFalse(result.completed)
        self.assertEqual(called, ['Nod'])
        self.assertAlmostEqual(boundary, .5)


if __name__ == '__main__': unittest.main(verbosity=2)
