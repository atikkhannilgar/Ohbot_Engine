"""Opt-in voice check: run with the venv Python in a logged-in macOS desktop session.

This invokes the native speech service. Headless/restricted sessions can return
empty audio even when the native desktop application produces audio successfully.
"""
import sys
import unittest

import numpy as np

from obot.speech.config import LocalTTSSettings
from obot.speech.tts import LocalTTS


@unittest.skipUnless(sys.platform == "darwin", "requires the built-in macOS voice service")
class MacVoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_sentences_produce_decodable_audio(self):
        engine = LocalTTS(LocalTTSSettings(voice=""))
        try:
            for sentence in ("Hello from OhBot.", "This is a second voice check."):
                audio = await engine.synthesize(sentence)
                self.assertEqual(audio.engine, "local")
                self.assertEqual(audio.samples.dtype, np.int16)
                self.assertEqual(audio.sample_rate, 22050)
                self.assertGreater(audio.samples.size, 1000)
                self.assertGreater(np.abs(audio.samples.astype(np.int32)).max(), 0)
        finally:
            engine.close()

    async def test_zero_volume_produces_silent_samples(self):
        engine = LocalTTS(LocalTTSSettings(voice="", volume=0))
        try:
            audio = await engine.synthesize("Check the volume setting.")
            self.assertGreater(audio.samples.size, 1000)
            self.assertTrue(np.all(audio.samples == 0))
        finally:
            engine.close()


if __name__ == "__main__":
    unittest.main()
