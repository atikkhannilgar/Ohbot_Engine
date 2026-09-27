"""Tunable settings for the custom speech stack and robot motion.

Every value that affects how the mouth moves, which voice speaks, and how the
head motion blends lives here, loaded from the "speech" / "motion" sections of
config.json. Missing keys fall back to the dataclass defaults, so an old
config.json keeps working untouched.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class MouthSettings:
    """How loudness maps onto lip servo positions during speech.

    The pipeline is: audio -> RMS envelope (at ``fps`` frames/sec) -> normalise
    to 0..1 -> noise ``gate`` -> ``gamma`` curve -> attack/release smoothing ->
    scale by ``top_gain``/``bottom_gain`` into lip deltas above the rest
    position (5 = mouth closed, 10 = fully open on both lips).
    """

    fps: float = 25.0            # lip updates per second
    gate: float = 0.06           # envelope below this fraction of peak counts as silence
    gamma: float = 0.65          # < 1 opens the mouth more on quiet syllables
    attack: float = 0.65         # 0..1, how fast the mouth opens (1 = instant)
    release: float = 0.4         # 0..1, how fast the mouth closes
    top_gain: float = 3.5        # top lip delta above rest at full loudness (0..5)
    bottom_gain: float = 4.5     # bottom lip delta above rest at full loudness (0..5)
    top_max_delta: float = 5.0   # hard cap for the top lip delta
    bottom_max_delta: float = 5.0
    sync_offset_s: float = 0.0   # + if lips lag the audio, - if lips run ahead

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "MouthSettings":
        return _from_dict(cls, data)


@dataclass
class GeminiTTSSettings:
    model: str = "gemini-2.5-flash-preview-tts"
    voice: str = "Kore"          # prebuilt voice name (Kore, Puck, Leda, Charon, ...)
    # Optional style instruction prepended to the text, e.g.
    # "Say this like an upbeat British news presenter:". Empty = plain reading.
    style: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "GeminiTTSSettings":
        return _from_dict(cls, data)


@dataclass
class PiperTTSSettings:
    """Piper: neural TTS running fully offline (Windows PC and the Pi).

    Quality sits between Gemini and the old SAPI voice, with no rate limits.
    Voices come from the rhasspy/piper-voices collection; ``en_GB-*`` fits the
    Ms. Mimic persona. ``length_scale`` controls pace (1.0 normal, 0.9 faster).
    """

    voice: str = "en_GB-cori-high"
    # Explicit path to a .onnx voice model. Empty = ohbotData/piper/<voice>.onnx.
    model_path: str = ""
    # Download the voice model automatically on first use (one-time, ~60-100 MB).
    auto_download: bool = True
    # Load the model in the background at startup so the first sentence doesn't
    # pay the ~3s model-load cost.
    warm_up: bool = True
    length_scale: float = 1.0
    volume: float = 1.0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PiperTTSSettings":
        return _from_dict(cls, data)


@dataclass
class LocalTTSSettings:
    voice: str = "zira"          # substring match against installed voice names (SAPI/espeak)
    rate_wpm: int = 175
    volume: float = 1.0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "LocalTTSSettings":
        return _from_dict(cls, data)


@dataclass
class EdgeTTSSettings:
    """Microsoft Edge online neural TTS (edge-tts): Azure-quality voices, free, no key.

    ``voice`` is a Microsoft neural voice short name (``en-GB-SoniaNeural``,
    ``en-US-AriaNeural``, ...). ``rate``/``volume``/``pitch`` are edge-tts prosody
    strings (``"+0%"``, ``"-10%"``, ``"+5Hz"``). Needs internet; unofficial endpoint.
    """

    voice: str = "en-GB-SoniaNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "EdgeTTSSettings":
        return _from_dict(cls, data)


@dataclass
class KokoroTTSSettings:
    """Kokoro: a small, high-quality open TTS model running fully offline via ONNX.

    Reads more naturally than Piper and runs faster than real time on the CPU.
    ``voice`` is a Kokoro voice id (``bf_emma``/``bf_alice`` British female,
    ``af_sarah`` American female, ``bm_george`` British male, ...). The model
    (~330 MB) and voice pack download automatically to ``ohbotData/kokoro/``.
    """

    voice: str = "bf_emma"
    speed: float = 1.0
    lang: str = "en-us"
    # Explicit paths override the auto-downloaded ohbotData/kokoro/ files.
    model_path: str = ""
    voices_path: str = ""
    auto_download: bool = True
    warm_up: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "KokoroTTSSettings":
        return _from_dict(cls, data)


@dataclass
class GTTSSettings:
    """Google Translate TTS (gTTS): free, no key, decent quality. Needs internet.

    ``tld`` picks the accent of the Google endpoint (``co.uk`` British, ``com``
    US, ``com.au`` Australian, ``ie`` Irish, ...). ``slow`` reads more slowly.
    """

    lang: str = "en"
    tld: str = "co.uk"
    slow: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "GTTSSettings":
        return _from_dict(cls, data)


@dataclass
class TTSSettings:
    # "auto" chains the best available voices, falling through on any failure:
    # edge -> kokoro -> piper -> local. Explicit modes pin one engine:
    # "edge", "kokoro", "gtts", "gemini", "piper", or "local".
    engine: str = "auto"
    gemini: GeminiTTSSettings = field(default_factory=GeminiTTSSettings)
    piper: PiperTTSSettings = field(default_factory=PiperTTSSettings)
    local: LocalTTSSettings = field(default_factory=LocalTTSSettings)
    edge: EdgeTTSSettings = field(default_factory=EdgeTTSSettings)
    kokoro: KokoroTTSSettings = field(default_factory=KokoroTTSSettings)
    gtts: GTTSSettings = field(default_factory=GTTSSettings)
    # After an engine failure, don't retry it for this long (keeps sentences
    # flowing on the next voice instead of paying a timeout per sentence).
    # Gemini's free tier is ~3 requests/min, so quota errors land here often.
    failure_cooldown_s: float = 90.0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TTSSettings":
        data = data or {}
        return cls(
            engine=str(data.get("engine", cls.engine)),
            gemini=GeminiTTSSettings.from_dict(data.get("gemini")),
            piper=PiperTTSSettings.from_dict(data.get("piper")),
            local=LocalTTSSettings.from_dict(data.get("local")),
            edge=EdgeTTSSettings.from_dict(data.get("edge")),
            kokoro=KokoroTTSSettings.from_dict(data.get("kokoro")),
            gtts=GTTSSettings.from_dict(data.get("gtts")),
            failure_cooldown_s=float(data.get("failure_cooldown_s", cls.failure_cooldown_s)),
        )


@dataclass
class AIGestureSettings:
    """Optional: drive head/eyes/lids/lips from the BEAT2-trained audio model
    instead of the scripted RMS-envelope mouth track. Disabled by default --
    the checkpoint is a small, still-training model, and torch is only
    imported (see speech/engine.py) when this is turned on.
    """

    enabled: bool = False
    # Path to a train.py checkpoint.
    checkpoint_path: str = ""
    # Must match the --control-hz the checkpoint was trained with (beat2_to_ohbot.py).
    control_hz: float = 20.0
    device: str = "cpu"  # torch device for inference: "cpu" or "cuda"
    # Scales predicted movement around rest position: 1.0 = model output
    # unchanged, >1 exaggerates the gestures, <1 dampens them.
    intensity: float = 1.0
    # When True, the ML model drives head/eyes/lids but TOPLIP and BOTTOMLIP
    # are still driven by the scripted RMS-envelope mouth track.
    scripted_mouth: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AIGestureSettings":
        return _from_dict(cls, data)


@dataclass
class SpeechSettings:
    tts: TTSSettings = field(default_factory=TTSSettings)
    mouth: MouthSettings = field(default_factory=MouthSettings)
    gesture: AIGestureSettings = field(default_factory=AIGestureSettings)
    # sounddevice output device index; None = system default speakers.
    output_device_index: int | None = None
    # When interrupted, playback runs to the end of the current word plus this pad.
    word_stop_pad_s: float = 0.06
    # Pacing estimate used when no real audio exists (console controller, TTS failure).
    estimate_wpm: float = 160.0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SpeechSettings":
        data = data or {}
        device = data.get("output_device_index")
        return cls(
            tts=TTSSettings.from_dict(data.get("tts")),
            mouth=MouthSettings.from_dict(data.get("mouth")),
            gesture=AIGestureSettings.from_dict(data.get("gesture")),
            output_device_index=int(device) if device is not None else None,
            word_stop_pad_s=float(data.get("word_stop_pad_s", cls.word_stop_pad_s)),
            estimate_wpm=float(data.get("estimate_wpm", cls.estimate_wpm)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MotionSettings:
    """Servo mixing/blending tunables shared by the hardware and sim controllers."""

    tick_s: float = 0.05         # mixer loop period; 0.05 = 20 updates/sec
    rate_limit: float = 30.0     # max servo travel in positions/sec (head, eyes)
    lip_rate_limit: float = 200.0  # lips need to snap much faster than the head
    write_epsilon: float = 0.05  # skip serial writes smaller than this position change
    move_speed: int = 3         # ohbot speed argument used for mixer writes

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "MotionSettings":
        return _from_dict(cls, data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _from_dict(cls, data: dict[str, Any] | None):
    """Build a flat dataclass from a dict, keeping defaults for missing/bad keys."""
    data = data or {}
    kwargs: dict[str, Any] = {}
    for name, f in cls.__dataclass_fields__.items():
        if name not in data:
            continue
        try:
            kwargs[name] = type(f.default)(data[name]) if f.default is not None else data[name]
        except (TypeError, ValueError):
            pass
    return cls(**kwargs)
