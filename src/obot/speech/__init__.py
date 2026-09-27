"""Custom speech stack replacing ohbot.say().

Synthesis (Gemini TTS or local pyttsx3), interruptible playback, viseme-based
mouth animation, and a word timeline for precisely timed mid-sentence actions.
"""

from .config import MotionSettings, MouthSettings, SpeechSettings, TTSSettings
from .engine import SpeechEngine, SpeakResult
from .tts import TTSError

__all__ = [
    "MotionSettings",
    "MouthSettings",
    "SpeechSettings",
    "TTSSettings",
    "SpeechEngine",
    "SpeakResult",
    "TTSError",
]
