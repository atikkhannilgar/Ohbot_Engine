"""Text-to-speech engines producing raw PCM for the speech pipeline.

Three engines plus a fallback chain (best voice first):

* :class:`GeminiTTS`  Google's Gemini TTS API. The most natural voices, but
  the free tier allows only ~3 requests/minute, so in practice it covers the
  first sentences of a conversation and the chain drops through afterwards.
* :class:`PiperTTS`  neural TTS running fully offline (Windows and the Pi).
  Close-to-Gemini quality with zero rate limits; the everyday workhorse.
* :class:`LocalTTS`  SAPI on Windows / espeak on the Pi. Robotic, but
  dependency-free and effectively cannot fail; the last resort.

All return :class:`SynthResult` (mono int16 samples + sample rate) so the rest
of the stack  playback, mouth animation, word timeline  is engine-agnostic.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import re
import sys
import tempfile
import threading
import time
import wave
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import (
    EdgeTTSSettings,
    GeminiTTSSettings,
    GTTSSettings,
    KokoroTTSSettings,
    LocalTTSSettings,
    PiperTTSSettings,
    TTSSettings,
)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


class TTSError(RuntimeError):
    """Raised when synthesis fails (network, quota, missing voice, ...)."""


@dataclass(frozen=True)
class SynthResult:
    samples: np.ndarray  # mono int16
    sample_rate: int
    engine: str

    @property
    def duration_s(self) -> float:
        return len(self.samples) / float(self.sample_rate)


class TTSEngine(ABC):
    name: str = "tts"

    @abstractmethod
    async def synthesize(self, text: str) -> SynthResult: ...

    def close(self) -> None:
        """Release engine resources (worker threads, COM objects). Optional."""


class GeminiTTS(TTSEngine):
    """Gemini TTS API: returns 24 kHz PCM via generateContent with AUDIO modality."""

    name = "gemini"

    def __init__(self, api_key: str, settings: GeminiTTSSettings) -> None:
        if not api_key:
            raise TTSError("gemini_api_key is empty; Gemini TTS needs it (config.json).")
        self._api_key = api_key
        self._settings = settings

    async def synthesize(self, text: str) -> SynthResult:
        import httpx  # lazy so machines without httpx can still run local-only

        s = self._settings
        # A style prompt ("Say this like a cheery news anchor:") steers delivery and
        # pace  Gemini TTS takes direction from the text itself, not from parameters.
        # A directive is REQUIRED: with bare conversational text the TTS model
        # sometimes tries to *answer* it and the API rejects the call with a 400.
        style = s.style.strip() or "Say:"
        prompt = f"{style} {text}"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": s.voice}}
                },
            },
        }
        url = f"{GEMINI_BASE}/models/{s.model}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
                r = await client.post(url, params={"key": self._api_key}, json=body)
        except httpx.HTTPError as exc:
            raise TTSError(f"Gemini TTS network error: {exc}") from exc

        if r.status_code != 200:
            # Collapse the JSON error onto one line so a failure is one log line.
            detail = " ".join(r.text.split())[:160]
            raise TTSError(f"Gemini TTS returned {r.status_code}: {detail}")

        try:
            part = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
            mime = part.get("mimeType", "")
            pcm = base64.b64decode(part["data"])
        except (KeyError, IndexError, ValueError) as exc:
            raise TTSError(f"Gemini TTS response had no audio: {r.text[:200]}") from exc

        # mimeType looks like "audio/L16;codec=pcm;rate=24000".
        rate_match = re.search(r"rate=(\d+)", mime)
        sample_rate = int(rate_match.group(1)) if rate_match else 24_000
        samples = np.frombuffer(pcm, dtype=np.int16)
        if samples.size == 0:
            raise TTSError("Gemini TTS returned empty audio.")
        return SynthResult(samples=samples, sample_rate=sample_rate, engine=self.name)


class PiperTTS(TTSEngine):
    """Piper neural TTS: offline, no rate limits, near-Gemini voice quality.

    The voice model (a ~60-100 MB .onnx file) lives in ``ohbotData/piper/`` and
    is downloaded automatically on first use (configurable). Synthesis runs on
    a worker thread; the ONNX session is loaded once and reused  Piper handles
    sentence-after-sentence synthesis without the SAPI-style COM fragility.
    """

    name = "piper"

    # Default location for downloaded voices, relative to the repo root
    # (the app runs from there  the ohbot library itself requires it).
    VOICES_DIR = Path("ohbotData") / "piper"

    def __init__(self, settings: PiperTTSSettings) -> None:
        self._settings = settings
        self._voice = None
        self._syn_config = None
        self._lock = threading.Lock()
        if settings.warm_up:
            threading.Thread(target=self._warm_up, daemon=True, name="piper-warmup").start()

    def _warm_up(self) -> None:
        # Pre-load (and if needed download) the voice so the first spoken sentence
        # starts instantly. Failures are non-fatal: the first real synthesis will
        # retry and raise properly into the fallback chain.
        try:
            with self._lock:
                self._ensure_voice()
        except TTSError as exc:
            print(f"[tts] piper warm-up failed: {exc}")

    async def synthesize(self, text: str) -> SynthResult:
        return await asyncio.to_thread(self._synthesize_blocking, text)

    def _synthesize_blocking(self, text: str) -> SynthResult:
        with self._lock:
            voice = self._ensure_voice()
            try:
                chunks = list(voice.synthesize(text, self._syn_config))
            except Exception as exc:
                raise TTSError(f"piper synthesis failed: {exc}") from exc

        if not chunks:
            raise TTSError("piper produced no audio.")
        samples = np.frombuffer(
            b"".join(c.audio_int16_bytes for c in chunks), dtype=np.int16
        )
        if samples.size == 0:
            raise TTSError("piper produced empty audio.")
        return SynthResult(
            samples=samples, sample_rate=int(chunks[0].sample_rate), engine=self.name
        )

    def _ensure_voice(self):
        if self._voice is not None:
            return self._voice
        try:
            from piper import PiperVoice, SynthesisConfig
        except ImportError as exc:
            raise TTSError("piper-tts is not installed (pip install piper-tts).") from exc

        model = self._resolve_model()
        print(f"[tts] loading piper voice {model.name} ...")
        try:
            self._voice = PiperVoice.load(str(model))
        except Exception as exc:
            raise TTSError(f"could not load piper voice '{model}': {exc}") from exc

        s = self._settings
        try:
            self._syn_config = SynthesisConfig(
                length_scale=float(s.length_scale), volume=float(s.volume)
            )
        except TypeError:
            # Older/newer piper without these knobs: synthesize with defaults.
            self._syn_config = None
        return self._voice

    def _resolve_model(self) -> Path:
        s = self._settings
        if s.model_path:
            model = Path(s.model_path)
            if not model.exists():
                raise TTSError(
                    f"piper model_path '{s.model_path}' does not exist "
                    "(config.json -> speech.tts.piper.model_path)."
                )
            return model

        model = self.VOICES_DIR / f"{s.voice}.onnx"
        if model.exists():
            return model

        if not s.auto_download:
            raise TTSError(
                f"piper voice '{s.voice}' not found at {model}. Download it with:\n"
                f"  python -m piper.download_voices {s.voice} --data-dir {self.VOICES_DIR}"
            )

        print(f"[tts] downloading piper voice '{s.voice}' (one-time, ~60-100 MB)...")
        try:
            from piper.download_voices import download_voice

            self.VOICES_DIR.mkdir(parents=True, exist_ok=True)
            download_voice(s.voice, self.VOICES_DIR)
        except Exception as exc:
            raise TTSError(f"could not download piper voice '{s.voice}': {exc}") from exc
        if not model.exists():
            raise TTSError(f"piper voice download finished but {model} is missing.")
        print(f"[tts] piper voice ready: {model}")
        return model


class LocalTTS(TTSEngine):
    """Offline TTS: Windows SAPI, macOS say, or pyttsx3/espeak on Linux/Pi.

    All synthesis runs on ONE dedicated worker thread, because SAPI's COM
    objects must stay in the apartment (thread) that created them. Windows
    deliberately does not use pyttsx3  its SAPI driver deadlocks on the second
    ``runAndWait`` of a reused engine  and instead drives SAPI the same way
    the ohbot library did (SpVoice writing into a SpFileStream per call), which
    is proven to run sentence after sentence. Synthesis writes a temp WAV that
    is loaded back as PCM.
    """

    name = "local"

    def __init__(self, settings: LocalTTSSettings) -> None:
        from concurrent.futures import ThreadPoolExecutor

        self._settings = settings
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="obot-tts")
        self._backend = None  # created lazily on the worker thread

    async def synthesize(self, text: str) -> SynthResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._synthesize_blocking, text)

    def close(self) -> None:
        # Drop the COM objects on the worker thread (their home apartment) before
        # the executor goes away  releasing them from another thread at
        # interpreter shutdown makes SAPI exit uncleanly.
        def _release() -> None:
            self._backend = None

        try:
            self._executor.submit(_release).result(timeout=2.0)
        except Exception:
            pass
        self._executor.shutdown(wait=False)

    def _synthesize_blocking(self, text: str) -> SynthResult:
        if self._backend is None:
            if sys.platform == "win32":
                self._backend = _SapiBackend(self._settings)
            elif sys.platform == "darwin":
                from .macos import MacSayBackend
                self._backend = MacSayBackend(self._settings)
            else:
                self._backend = _PyttsxBackend(self._settings)

        fd, path = tempfile.mkstemp(suffix=".wav", prefix="obot_tts_")
        os.close(fd)
        try:
            self._backend.synth_to_file(text, path)
            samples, sample_rate = _load_wav_mono16(path)
        except TTSError:
            raise
        except Exception as exc:
            # A wedged backend poisons its COM state; drop it so the next call re-inits.
            self._backend = None
            raise TTSError(f"local TTS failed: {exc}") from exc
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        if samples.size == 0:
            raise TTSError("local TTS produced an empty file.")
        if sys.platform == "darwin":
            volume = max(0.0, min(1.0, self._settings.volume))
            samples = np.rint(samples.astype(np.float64) * volume).astype(np.int16)
        return SynthResult(samples=samples, sample_rate=sample_rate, engine=self.name)


class _SapiBackend:
    """Windows SAPI voice writing WAVs, one Speak per sentence (ohbot-style)."""

    def __init__(self, settings: LocalTTSSettings) -> None:
        try:
            import comtypes
            from comtypes.client import CreateObject
        except ImportError as exc:
            raise TTSError("comtypes is not installed (pip install comtypes).") from exc

        # COM must be initialized on THIS thread (comtypes only auto-inits the
        # thread that first imported it, which may have been the main thread).
        try:
            comtypes.CoInitialize()
        except OSError:
            pass

        self._voice = CreateObject("SAPI.SpVoice")
        self._create_stream = lambda: CreateObject("SAPI.SpFileStream")
        # comtypes generates this module when the first SAPI object is created.
        from comtypes.gen import SpeechLib

        self._speechlib = SpeechLib
        s = settings
        self._voice.Volume = int(max(0.0, min(1.0, s.volume)) * 100)
        # SAPI rate is -10..+10 around ~175 wpm; map the configured wpm onto it.
        self._voice.Rate = int(max(-10, min(10, round((s.rate_wpm - 175) / 15))))
        if s.voice:
            for v in self._voice.GetVoices():
                if s.voice.lower() in v.GetDescription().lower():
                    self._voice.Voice = v
                    break

    def synth_to_file(self, text: str, path: str) -> None:
        stream = self._create_stream()
        stream.Open(path, self._speechlib.SSFMCreateForWrite)
        try:
            self._voice.AudioOutputStream = stream
            self._voice.Speak(text)
        finally:
            stream.Close()


class _PyttsxBackend:
    """pyttsx3 (espeak) for Linux/Pi, where engine reuse is safe."""

    def __init__(self, settings: LocalTTSSettings) -> None:
        try:
            import pyttsx3
        except ImportError as exc:
            raise TTSError("pyttsx3 is not installed (pip install pyttsx3).") from exc

        engine = pyttsx3.init()
        engine.setProperty("rate", int(settings.rate_wpm))
        engine.setProperty("volume", float(settings.volume))
        if settings.voice:
            for v in engine.getProperty("voices"):
                if (
                    settings.voice.lower() in (v.name or "").lower()
                    or settings.voice.lower() in v.id.lower()
                ):
                    engine.setProperty("voice", v.id)
                    break
        self._engine = engine

    def synth_to_file(self, text: str, path: str) -> None:
        self._engine.save_to_file(text, path)
        self._engine.runAndWait()


def _decode_mp3(data: bytes, target_rate: int = 24_000) -> tuple[np.ndarray, int]:
    """Decode MP3 bytes (from the online voices) to mono int16 at ``target_rate``."""
    try:
        import miniaudio
    except ImportError as exc:
        raise TTSError(
            "miniaudio is not installed (pip install miniaudio)  needed to decode the "
            "MP3 audio from the online voices (edge/gtts)."
        ) from exc
    try:
        decoded = miniaudio.decode(
            data, output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=1, sample_rate=target_rate,
        )
    except Exception as exc:
        raise TTSError(f"could not decode MP3 audio: {exc}") from exc
    samples = np.frombuffer(decoded.samples.tobytes(), dtype=np.int16)
    if samples.size == 0:
        raise TTSError("decoded MP3 audio was empty.")
    return samples, int(decoded.sample_rate)


class EdgeTTS(TTSEngine):
    """Microsoft Edge online neural TTS (edge-tts): Azure-quality voices, free, no key."""

    name = "edge"

    def __init__(self, settings: EdgeTTSSettings) -> None:
        self._settings = settings

    async def synthesize(self, text: str) -> SynthResult:
        try:
            import edge_tts
        except ImportError as exc:
            raise TTSError("edge-tts is not installed (pip install edge-tts).") from exc

        s = self._settings
        try:
            comm = edge_tts.Communicate(
                text, voice=s.voice, rate=s.rate, volume=s.volume, pitch=s.pitch
            )
            buf = bytearray()
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    buf += chunk["data"]
        except Exception as exc:
            raise TTSError(f"edge-tts synthesis failed: {exc}") from exc
        if not buf:
            raise TTSError("edge-tts returned no audio (check the voice name / network).")
        samples, rate = _decode_mp3(bytes(buf))
        return SynthResult(samples=samples, sample_rate=rate, engine=self.name)


class GTTSEngine(TTSEngine):
    """Google Translate TTS (gTTS): free, no key, decent quality. Needs internet."""

    name = "gtts"

    def __init__(self, settings: GTTSSettings) -> None:
        self._settings = settings

    async def synthesize(self, text: str) -> SynthResult:
        return await asyncio.to_thread(self._synthesize_blocking, text)

    def _synthesize_blocking(self, text: str) -> SynthResult:
        try:
            from gtts import gTTS
        except ImportError as exc:
            raise TTSError("gTTS is not installed (pip install gTTS).") from exc

        s = self._settings
        buf = io.BytesIO()
        try:
            gTTS(text=text, lang=s.lang, tld=s.tld, slow=s.slow).write_to_fp(buf)
        except Exception as exc:
            raise TTSError(f"gTTS synthesis failed: {exc}") from exc
        data = buf.getvalue()
        if not data:
            raise TTSError("gTTS returned no audio.")
        samples, rate = _decode_mp3(data)
        return SynthResult(samples=samples, sample_rate=rate, engine=self.name)


class KokoroTTS(TTSEngine):
    """Kokoro: a small, high-quality open TTS model running fully offline via ONNX.

    Reads more naturally than Piper and runs faster than real time on the CPU. The model
    (~330 MB) and voice pack download automatically to ``ohbotData/kokoro/`` on first use.
    Synthesis runs on a worker thread; the ONNX session is loaded once and reused.
    """

    name = "kokoro"

    MODELS_DIR = Path("ohbotData") / "kokoro"
    _RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
    _MODEL_FILE = "kokoro-v1.0.onnx"
    _VOICES_FILE = "voices-v1.0.bin"


    def __init__(self, settings: KokoroTTSSettings) -> None:
        self._settings = settings
        self._kokoro = None
        self._lock = threading.Lock()
        if settings.warm_up:
            threading.Thread(target=self._warm_up, daemon=True, name="kokoro-warmup").start()

    def _warm_up(self) -> None:
        try:
            with self._lock:
                self._ensure_loaded()
        except TTSError as exc:
            print(f"[tts] kokoro warm-up failed: {exc}")

    async def synthesize(self, text: str) -> SynthResult:
        return await asyncio.to_thread(self._synthesize_blocking, text)

    def _synthesize_blocking(self, text: str) -> SynthResult:
        with self._lock:
            kokoro = self._ensure_loaded()
            try:
                samples, sample_rate = kokoro.create(
                    text, voice=self._settings.voice,
                    speed=float(self._settings.speed), lang=self._settings.lang,
                )
            except Exception as exc:
                raise TTSError(f"kokoro synthesis failed: {exc}") from exc
        if samples is None or len(samples) == 0:
            raise TTSError("kokoro produced no audio.")
        # Kokoro returns float32 in [-1, 1]; convert to int16 PCM for the pipeline.
        pcm = np.clip(np.asarray(samples, dtype=np.float32) * 32767.0, -32768, 32767).astype(np.int16)
        return SynthResult(samples=pcm, sample_rate=int(sample_rate), engine=self.name)

    def _ensure_loaded(self):
        if self._kokoro is not None:
            return self._kokoro
        try:
            from kokoro_onnx import Kokoro
        except ImportError as exc:
            raise TTSError("kokoro-onnx is not installed (pip install kokoro-onnx).") from exc

        model = self._resolve(self._settings.model_path, self._MODEL_FILE, "model", "~330 MB")
        voices = self._resolve(self._settings.voices_path, self._VOICES_FILE, "voice pack", "~28 MB")
        print(f"[tts] loading kokoro model {model.name} ...")
        try:
            self._kokoro = Kokoro(str(model), str(voices))
        except Exception as exc:
            raise TTSError(f"could not load kokoro model: {exc}") from exc
        return self._kokoro

    def _resolve(self, explicit: str, filename: str, label: str, size: str) -> Path:
        if explicit:
            p = Path(explicit)
            if not p.exists():
                raise TTSError(f"kokoro {label} path '{explicit}' does not exist.")
            return p
        path = self.MODELS_DIR / filename
        if path.exists():
            return path
        if not self._settings.auto_download:
            raise TTSError(
                f"kokoro {label} not found at {path}. Download it from {self._RELEASE} "
                "or set speech.tts.kokoro.auto_download = true."
            )
        print(f"[tts] downloading kokoro {label} ({size}, one-time)...")
        try:
            import urllib.request

            self.MODELS_DIR.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".part")
            urllib.request.urlretrieve(f"{self._RELEASE}/{filename}", tmp)
            os.replace(tmp, path)
        except Exception as exc:
            raise TTSError(f"could not download kokoro {label}: {exc}") from exc
        print(f"[tts] kokoro {label} ready: {path}")
        return path


class FallbackTTS(TTSEngine):
    """Tries engines in order; a failing engine is benched for a cooldown period.

    The bench matters for flow: without it, a dead network would add a full
    timeout to *every* sentence before the local voice kicked in.
    """

    name = "fallback"

    def __init__(self, engines: list[TTSEngine], cooldown_s: float = 90.0) -> None:
        if not engines:
            raise TTSError("no TTS engines configured.")
        self._engines = engines
        self._cooldown_s = cooldown_s
        self._benched_until: dict[str, float] = {}

    async def synthesize(self, text: str) -> SynthResult:
        errors: list[str] = []
        now = time.monotonic()
        for engine in self._engines:
            if self._benched_until.get(engine.name, 0.0) > now:
                continue
            try:
                return await engine.synthesize(text)
            except TTSError as exc:
                errors.append(f"{engine.name}: {exc}")
                self._benched_until[engine.name] = time.monotonic() + self._cooldown_s
                print(f"[tts] {engine.name} failed ({exc}); "
                      f"benched for {int(self._cooldown_s)}s.")
        # Everyone is benched or failed: clear the bench and report, so the next
        # sentence gets a fresh chance instead of failing forever.
        self._benched_until.clear()
        raise TTSError("all TTS engines failed: " + " | ".join(errors))

    def close(self) -> None:
        for engine in self._engines:
            engine.close()


def _module_installed(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None


def build_tts(settings: TTSSettings, gemini_api_key: str = "") -> TTSEngine:
    """Assemble the engine (chain) described by config.

    ``auto`` chains the best available voices, falling through on failure:
    edge -> kokoro -> piper -> local. Explicit modes pin a single engine
    ("edge", "kokoro", "gtts", "gemini", "piper", "local"), with the basic local
    voice as a last resort only if the pinned engine isn't available.
    """
    mode = settings.engine.lower().strip() or "auto"
    if mode not in ("auto", "edge", "kokoro", "gtts", "gemini", "piper", "local"):
        print(f"[tts] unknown engine '{mode}'; using the auto chain.")
        mode = "auto"

    engines: list[TTSEngine] = []

    def add_if_installed(module: str, make: Callable[[], TTSEngine], pip_name: str) -> None:
        if _module_installed(module):
            engines.append(make())
        elif mode != "auto":
            print(f"[tts] engine set to '{mode}' but {pip_name} is not installed "
                  f"(pip install {pip_name}); using the basic local voice.")

    if mode in ("auto", "edge"):
        add_if_installed("edge_tts", lambda: EdgeTTS(settings.edge), "edge-tts")
    if mode in ("auto", "kokoro"):
        add_if_installed("kokoro_onnx", lambda: KokoroTTS(settings.kokoro), "kokoro-onnx")
    if mode == "gtts":
        add_if_installed("gtts", lambda: GTTSEngine(settings.gtts), "gTTS")
    if mode == "gemini":
        if gemini_api_key:
            engines.append(GeminiTTS(gemini_api_key, settings.gemini))
        else:
            print("[tts] engine set to 'gemini' but gemini_api_key is empty; "
                  "using the basic local voice.")
    if mode in ("auto", "piper"):
        add_if_installed("piper", lambda: PiperTTS(settings.piper), "piper-tts")

    # The basic local voice always terminates the auto chain, and stands in
    # whenever a pinned engine turned out to be unavailable.
    if not engines or mode in ("auto", "local"):
        engines.append(LocalTTS(settings.local))

    if len(engines) == 1:
        return engines[0]
    return FallbackTTS(engines, cooldown_s=settings.failure_cooldown_s)


def _load_wav_mono16(path: str) -> tuple[np.ndarray, int]:
    """Read a WAV file as mono int16 samples (mixing channels / widening 8-bit)."""
    with wave.open(path, "rb") as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())

    if width == 2:
        samples = np.frombuffer(raw, dtype=np.int16)
    elif width == 1:
        samples = ((np.frombuffer(raw, dtype=np.uint8).astype(np.int16) - 128) << 8)
    elif width == 4:
        samples = (np.frombuffer(raw, dtype=np.int32) >> 16).astype(np.int16)
    else:
        raise TTSError(f"unsupported WAV sample width: {width} bytes")

    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return samples, sample_rate
