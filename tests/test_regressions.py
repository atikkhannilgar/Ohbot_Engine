"""Hardware-free regression checks for streamed labels and speech bookkeeping."""
import asyncio
import unittest

import numpy as np

from obot.core.interrupt import InterruptController
from obot.core.orchestrator import RobotPipeline
from obot.core.processor import StreamProcessor
from obot.llm.client import format_interruption_note
from obot.robot.controller import ConsoleObotController
from obot.speech.timeline import build_timeline, envelope


def parse(chunks):
    processor = StreamProcessor()
    events = []
    for chunk in chunks:
        events.extend(processor.feed(chunk))
    events.extend(processor.flush())
    return [event.to_dict() for event in events]


class StreamTests(unittest.TestCase):
    def test_delay_survives_every_two_chunk_split(self):
        text = 'Hello !Delay500 world.'
        expected = [{'kind': 'sentence', 'payload': 'Hello world.',
                     'metadata': {'delays': '500@5'}}]
        for split in range(len(text) + 1):
            with self.subTest(split=split):
                self.assertEqual(parse([text[:split], text[split:]]), expected)

    def test_labels_survive_character_stream(self):
        text = '(Happy) Let us try [Nod] the next step. !Delay500 Finish [Blink].'
        self.assertEqual(parse(list(text)), parse([text]))
        self.assertNotIn('Delay', ' '.join(e['payload'] for e in parse(list(text))))

    def test_final_delay_is_preserved(self):
        event = parse(['Hello !', 'Delay5', '00'])[0]
        self.assertEqual(event['payload'], 'Hello')
        self.assertEqual(event['metadata'], {'delays': '500@5'})

    def test_final_exclamation_is_punctuation(self):
        self.assertEqual([e['payload'] for e in parse(['Hello', '!'])], ['Hello!'])

    def test_longer_delay_digits_are_not_split(self):
        event = parse(['Hello !Delay5', '000 world.'])[0]
        self.assertEqual(event['metadata']['delays'], '5000@5')


class AudioTests(unittest.TestCase):
    def test_empty_audio_is_empty(self):
        self.assertEqual(envelope(np.zeros(0, dtype=np.int16), 16000, 50).size, 0)

    def test_short_audio_and_partial_frame(self):
        for size in [1, 100, 319, 320, 321]:
            with self.subTest(size=size):
                result = envelope(np.ones(size, dtype=np.int16), 16000, 50)
                self.assertTrue(np.isfinite(result).all())
                self.assertEqual(len(result), (size + 319) // 320)

    def test_silence_has_no_mouth_opening(self):
        self.assertTrue(np.all(envelope(np.zeros(100, dtype=np.int16), 16000, 50) == 0))

    def test_marker_at_word_end_uses_next_word(self):
        timeline = build_timeline('hello world', np.ones(16000, dtype=np.int16), 16000)
        self.assertEqual(timeline.time_for_char(5), timeline.words[1].start_s)
        self.assertEqual(timeline.time_for_char(11), timeline.words[-1].end_s)
        self.assertEqual(timeline.time_for_char(0), 0)

    def test_short_clip_word_spans_stay_within_audio(self):
        timeline = build_timeline('one two three', np.ones(100, dtype=np.int16), 16000)
        for word in timeline.words:
            self.assertTrue(0 <= word.start_s <= word.end_s <= timeline.duration_s)


class Source:
    def __init__(self):
        self.registered = None

    async def stream_response(self, prompt):
        yield 'First sentence has several words. Second sentence.'

    def register_interruption(self, spoken, unspoken):
        self.registered = (spoken, unspoken)


class ResolveInputDeviceTests(unittest.TestCase):
    """``None`` must resolve to PortAudio's default, not the first picker-list mic."""

    def test_none_uses_hostapi_default_not_first_listed(self):
        from unittest import mock

        import obot.audio.input as inp

        devices = [
            {'name': 'Listed First', 'hostapi': 0, 'max_input_channels': 2,
             'default_samplerate': 44100},
            {'name': 'Other Out', 'hostapi': 0, 'max_input_channels': 0,
             'default_samplerate': 44100},
            {'name': 'True Default', 'hostapi': 0, 'max_input_channels': 1,
             'default_samplerate': 48000},
        ]

        def query_devices(device=None, kind=None):
            if kind == 'input':
                return dict(devices[2], index=2)
            if device is None:
                return devices
            return devices[int(device)]

        fake_sd = mock.MagicMock()
        fake_sd.default.device = (None, 1)  # missing input half → use host API
        fake_sd.default.hostapi = 0
        fake_sd.query_hostapis.return_value = {
            'name': 'Core Audio',
            'default_input_device': 2,
        }
        fake_sd.query_devices.side_effect = query_devices

        with mock.patch.object(inp, 'sd', fake_sd), mock.patch.object(inp, '_HAVE_SD', True), \
             mock.patch.object(inp, '_HAVE_SR', True):
            self.assertEqual(inp.resolve_input_device(None), 2)
            self.assertEqual(inp.resolve_input_device(0), 0)

    def test_explicit_index_is_unchanged(self):
        from unittest import mock

        import obot.audio.input as inp

        with mock.patch.object(inp, '_HAVE_SD', True), mock.patch.object(inp, '_HAVE_SR', True):
            self.assertEqual(inp.resolve_input_device(5), 5)


class MicLifecycleTests(unittest.TestCase):
    """Mute must not abandon a live capture thread; unmute must not start a second one."""

    def test_stop_keeps_handle_when_join_times_out(self):
        import threading
        import time

        import obot.audio.input as inp

        audio = inp.AudioInput.__new__(inp.AudioInput)
        audio._stop = threading.Event()
        audio._thread = None

        def stuck_loop():
            # Ignore stop briefly (simulates a blocking PortAudio/STT call).
            deadline = time.time() + 0.35
            while time.time() < deadline:
                time.sleep(0.02)
            audio._stop.wait(5)

        thread = threading.Thread(target=stuck_loop, daemon=True)
        audio._thread = thread
        thread.start()
        try:
            self.assertFalse(audio.stop(timeout=0.05))
            self.assertTrue(audio.is_running)
            self.assertIs(audio._thread, thread)
        finally:
            audio._stop.set()
            thread.join(timeout=2.0)

    def test_start_waits_out_stopping_thread(self):
        from unittest import mock
        import threading
        import time

        import obot.audio.input as inp

        started = []

        def fake_loop(self):
            started.append(threading.current_thread())
            while not self._stop.is_set():
                time.sleep(0.02)
            time.sleep(0.12)  # linger after stop so a short join times out

        audio = inp.AudioInput.__new__(inp.AudioInput)
        audio._stop = threading.Event()
        audio._thread = None
        with mock.patch.object(inp.AudioInput, '_capture_loop', fake_loop):
            audio.start()
            first = audio._thread
            self.assertFalse(audio.stop(timeout=0.05))
            self.assertTrue(first.is_alive())
            audio.start()  # must wait, then start exactly one replacement
            self.assertFalse(first.is_alive())
            self.assertEqual(len(started), 2)
            self.assertTrue(audio.is_running)
            self.assertTrue(audio.stop(timeout=2.0))


class MicConsumerRaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_mute_awaits_consumer_before_unmute_recreates(self):
        """Controlled check: cancel without await left two consumers; lock + await fixes it."""
        import asyncio
        import contextlib
        import sys
        from unittest import mock

        sys.modules.setdefault('websockets', mock.MagicMock())
        from obot.server import session as sess

        session = sess.ServerSession.__new__(sess.ServerSession)
        session._mic_mode = 'muted'
        session._mic_started = True
        session._mic_mode_lock = asyncio.Lock()
        session._mic_consumer = None
        session._audio = mock.MagicMock()
        session._audio.is_running = False
        session._audio.stop.return_value = True

        active = 0
        max_active = 0

        async def tracking_consumer():
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1

        session._mic_consumer_loop = tracking_consumer
        session._mic_consumer = asyncio.create_task(tracking_consumer())
        await asyncio.sleep(0)
        self.assertEqual(active, 1)

        # Overlapping mute + unmute: without the lock/await, max_active reached 2.
        mute_task = asyncio.create_task(session.set_mic_mode('muted'))
        await asyncio.sleep(0)
        unmute_task = asyncio.create_task(session.set_mic_mode('vad'))
        await mute_task
        await unmute_task
        self.assertLessEqual(max_active, 1)
        if session._mic_consumer is not None:
            session._mic_consumer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session._mic_consumer


class InterruptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_sentence_is_not_completed(self):
        interrupt = InterruptController()

        class Speaker:
            def prepare_sentence(self, sentence): pass
            def turn_finished(self): pass
            async def stop_speaking(self): pass
            async def set_emotion(self, emotion): pass
            async def speak_sentence(self, sentence, markers, on_marker):
                interrupt.trigger('keyboard')
                await interrupt.wait()
                return False

        result = await RobotPipeline(Source(), Speaker()).run('', interrupt)
        self.assertEqual(result.spoken, [])
        self.assertEqual(result.partial, ['First sentence has several words.'])
        self.assertEqual(result.unspoken, ['First sentence has several words.', 'Second sentence.'])

    async def test_legacy_controller_unknown_completion(self):
        interrupt = InterruptController()

        class Speaker:
            def prepare_sentence(self, sentence): pass
            def turn_finished(self): pass
            async def stop_speaking(self): pass
            async def set_emotion(self, emotion): pass
            async def speak_sentence(self, sentence, markers, on_marker):
                interrupt.trigger('keyboard')

        result = await RobotPipeline(Source(), Speaker()).run('', interrupt)
        self.assertFalse(result.spoken)
        self.assertEqual(len(result.partial), 1)

    async def test_console_completion_and_interruption(self):
        controller = ConsoleObotController()
        self.assertTrue(await controller.speak_sentence('Done.'))
        task = asyncio.create_task(controller.speak_sentence('This sentence is long enough to interrupt.'))
        await asyncio.sleep(0.06)
        await controller.stop_speaking()
        self.assertFalse(await task)

    async def test_uninterrupted_turn_keeps_all_sentences(self):
        result = await RobotPipeline(Source(), ConsoleObotController()).run('')
        self.assertEqual(len(result.spoken), 2)
        self.assertEqual(result.partial, [])
        self.assertEqual(result.unspoken, [])

    def test_note_does_not_claim_exact_audible_cutoff(self):
        note = format_interruption_note([], ['First sentence.'])
        self.assertIn('may have been heard', note)
        self.assertNotIn('before you could say', note)


if __name__ == '__main__':
    unittest.main(verbosity=2)
