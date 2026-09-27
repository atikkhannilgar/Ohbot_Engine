"""Voice enumeration and a one-off "speak this test sentence" helper for the GUI.

The Setup page needs to show the voices available per TTS engine and let the user
audition one before committing. Both operations are synchronous/blocking (COM
enumeration, synthesis, audio playback), so the server calls them via
``asyncio.to_thread`` and never on the event loop.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..speech.config import (
    EdgeTTSSettings,
    GeminiTTSSettings,
    GTTSSettings,
    KokoroTTSSettings,
    LocalTTSSettings,
    PiperTTSSettings,
)
from ..speech.tts import (
    EdgeTTS,
    GeminiTTS,
    GTTSEngine,
    KokoroTTS,
    LocalTTS,
    PiperTTS,
    TTSError,
)

# Gemini's prebuilt voice names are a fixed catalogue (not fetched per key), so a
# static list is correct and keeps the Setup page working offline.
GEMINI_PREBUILT_VOICES = [
    "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede",
    "Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba",
    "Despina", "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar",
    "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
    "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
]

# A curated set of Microsoft Edge neural voices (British first, for Ms. Mimic). The full
# edge-tts catalogue is ~300 voices across all languages; these are the useful English ones.
EDGE_VOICES = [
    "en-GB-SoniaNeural", "en-GB-LibbyNeural", "en-GB-MaisieNeural",
    "en-GB-RyanNeural", "en-GB-ThomasNeural",
    "en-US-AriaNeural", "en-US-JennyNeural", "en-US-MichelleNeural",
    "en-US-GuyNeural", "en-US-AnaNeural",
    "en-AU-NatashaNeural", "en-AU-WilliamNeural",
    "en-IE-EmilyNeural", "en-CA-ClaraNeural",
]

# Kokoro v1.0 voice ids (British female first). b* = British, a* = American; f/m = female/male.
KOKORO_VOICES = [
    "bf_emma", "bf_isabella", "bf_alice", "bf_lily",
    "bm_george", "bm_lewis", "bm_daniel", "bm_fable",
    "af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky",
    "am_adam", "am_michael", "am_liam", "am_onyx",
]

# gTTS has no named voices  the "voice" is the Google endpoint TLD, which sets the accent.
GTTS_ACCENTS = ["co.uk", "com", "com.au", "ca", "co.in", "ie", "co.za"]


def _piper_cached_voices(configured: str) -> list[str]:
    """Piper voices already downloaded to ohbotData/piper (offline-usable), plus the
    configured one so it always appears even before its first download."""
    voices: list[str] = []
    voices_dir = PiperTTS.VOICES_DIR
    try:
        if voices_dir.is_dir():
            voices = sorted(p.stem for p in voices_dir.glob("*.onnx"))
    except OSError:
        voices = []
    if configured and configured not in voices:
        voices.insert(0, configured)
    return voices


def _sapi_voices() -> list[str]:
    """Installed Windows SAPI voice names (short forms), enumerated on a COM thread."""
    try:
        import comtypes
        from comtypes.client import CreateObject
    except ImportError:
        return []
    try:
        comtypes.CoInitialize()
    except OSError:
        pass
    try:
        voice = CreateObject("SAPI.SpVoice")
        names = []
        for v in voice.GetVoices():
            desc = v.GetDescription()
            # SAPI descriptions look like "Microsoft Zira Desktop - English (United States)";
            # keep the leading name so it matches the config substring style ("zira").
            names.append(desc)
        return names
    except Exception:
        return []


def _pyttsx_voices() -> list[str]:
    try:
        import pyttsx3
    except ImportError:
        return []
    try:
        engine = pyttsx3.init()
        return [v.name or v.id for v in engine.getProperty("voices")]
    except Exception:
        return []


def list_tts_voices(cfg) -> dict:
    """Return the available voices per engine for the Setup page.

    One list per engine. Piper lists what is downloaded locally; ``edge``/``kokoro``
    are curated catalogues; ``gtts`` lists accent TLDs; ``local`` is SAPI / espeak.
    """
    if sys.platform == "darwin":
        from ..speech.macos import voice_names
        local = voice_names()
    else:
        local = _sapi_voices() if sys.platform == "win32" else _pyttsx_voices()
    return {
        "gemini": list(GEMINI_PREBUILT_VOICES),
        "piper": _piper_cached_voices(cfg.speech.tts.piper.voice),
        "local": local,
        "edge": list(EDGE_VOICES),
        "kokoro": list(KOKORO_VOICES),
        "gtts": list(GTTS_ACCENTS),
    }


def _play(samples, sample_rate: int) -> None:
    import sounddevice as sd

    sd.play(samples, samplerate=sample_rate)
    sd.wait()


def speak_test_blocking(cfg, engine: str, voice: str, text: str) -> str:
    """Synthesize ``text`` with one engine/voice and play it on the host. Blocking.

    Returns the engine name that actually produced audio. Raises :class:`TTSError`
    on synthesis failure so the server reports it as a failed RPC. Meant to run in a
    worker thread.
    """
    import asyncio

    text = (text or "").strip() or "Hello, I am Ms. Mimic. This is a voice test."
    engine = (engine or "").lower().strip()

    if engine == "gemini":
        settings = GeminiTTSSettings.from_dict(
            {**cfg.speech.tts.gemini.__dict__, "voice": voice or cfg.speech.tts.gemini.voice}
        )
        tts = GeminiTTS(cfg.gemini_api_key, settings)
    elif engine == "piper":
        settings = PiperTTSSettings.from_dict(
            {**cfg.speech.tts.piper.__dict__, "voice": voice or cfg.speech.tts.piper.voice,
             "warm_up": False}
        )
        tts = PiperTTS(settings)
    elif engine == "edge":
        settings = EdgeTTSSettings.from_dict(
            {**cfg.speech.tts.edge.__dict__, "voice": voice or cfg.speech.tts.edge.voice}
        )
        tts = EdgeTTS(settings)
    elif engine == "kokoro":
        settings = KokoroTTSSettings.from_dict(
            {**cfg.speech.tts.kokoro.__dict__, "voice": voice or cfg.speech.tts.kokoro.voice,
             "warm_up": False}
        )
        tts = KokoroTTS(settings)
    elif engine == "gtts":
        # gTTS "voice" from the GUI is the accent TLD.
        settings = GTTSSettings.from_dict(
            {**cfg.speech.tts.gtts.__dict__, "tld": voice or cfg.speech.tts.gtts.tld}
        )
        tts = GTTSEngine(settings)
    else:  # "local" / anything else
        settings = LocalTTSSettings.from_dict(
            {**cfg.speech.tts.local.__dict__, "voice": voice or cfg.speech.tts.local.voice}
        )
        tts = LocalTTS(settings)

    try:
        result = asyncio.run(tts.synthesize(text))
        _play(result.samples, result.sample_rate)
        return result.engine
    finally:
        tts.close()
