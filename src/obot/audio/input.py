from __future__ import annotations

import asyncio
import json
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from typing import Callable, Literal

from ..core import events

# speech_recognition (for transcription), sounddevice (for capture), and vosk are
# optional at import time so this module loads on machines without the audio stack.
# The friendly error is raised only when something actually tries to use the mic.
try:
    import speech_recognition as sr

    _HAVE_SR = True
except ImportError:
    sr = None  # type: ignore
    _HAVE_SR = False

try:
    import sounddevice as sd

    _HAVE_SD = True
except ImportError:
    sd = None  # type: ignore
    _HAVE_SD = False

try:
    import numpy as np

    _HAVE_NUMPY = True
except ImportError:
    np = None  # type: ignore
    _HAVE_NUMPY = False


ListenMode = Literal["vad", "ptt", "muted"]


class AudioInputError(RuntimeError):
    """Any microphone / speech-to-text failure surfaced to the caller."""


def _require_audio() -> None:
    if not _HAVE_SD or not _HAVE_SR:
        missing = []
        if not _HAVE_SD:
            missing.append("sounddevice")
        if not _HAVE_SR:
            missing.append("SpeechRecognition")
        raise AudioInputError(
            f"{', '.join(missing)} not installed. "
            "Run: pip install -r requirements/windows.txt (or requirements/linux.txt / pi.txt)."
        )


# --------------------------------------------------------------------------------------
# Device selection
# --------------------------------------------------------------------------------------

# Windows exposes every physical mic once *per host API* (MME, DirectSound, WASAPI,
# WDM-KS), with MME additionally truncating names to 31 chars  that is why one JBL mic
# showed up four times. Restricting enumeration to a single, modern host API collapses
# those aliases to one clean entry each. Order = most-preferred first.
# TODO: verify device enumeration on Linux.
_PREFERRED_HOST_APIS = ("Windows WASAPI", "Windows DirectSound", "MME")
_VIRTUAL_KEYWORDS = ("Sound Mapper", "Primary Sound Capture Driver")


def _choose_host_api() -> int | None:
    """Pick one host API to enumerate, so each physical mic appears exactly once."""
    try:
        hostapis = sd.query_hostapis()
    except Exception:  # pragma: no cover - host audio dependent
        return None
    names = [h["name"] for h in hostapis]
    for preferred in _PREFERRED_HOST_APIS:
        if preferred in names:
            return names.index(preferred)
    # Non-Windows (ALSA, CoreAudio, ...) usually has a single sensible API: use default.
    try:
        return sd.default.hostapi
    except Exception:  # pragma: no cover
        return 0 if hostapis else None


def _enumerate_input_devices() -> list[tuple[int, str]]:
    """Return ``(sounddevice_index, name)`` for real mics on the chosen host API."""
    _require_audio()
    devices = sd.query_devices()
    host_api = _choose_host_api()

    result: list[tuple[int, str]] = []
    seen: set[str] = set()
    for idx, d in enumerate(devices):
        if d["max_input_channels"] <= 0:
            continue
        if host_api is not None and d["hostapi"] != host_api:
            continue
        name = d["name"]
        if any(kw in name for kw in _VIRTUAL_KEYWORDS):
            continue
        key = name.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        result.append((idx, name))
    return result


def list_input_devices() -> list[str]:
    """Return the de-duplicated microphone names for the chosen host API."""
    return [name for _, name in _enumerate_input_devices()]


def list_input_devices_detailed() -> list[dict]:
    """Return ``[{"index": sounddevice_index, "name": str}, ...]`` for the server.

    The console picker works with 1-based display numbers; the GUI needs the real
    sounddevice index (what ends up in ``config.audio.input_device_index``), so it
    gets the index/name pairs directly.
    """
    return [{"index": idx, "name": name} for idx, name in _enumerate_input_devices()]


def stream_input_level(
    device_index: int | None,
    on_level: Callable[[float, float], None],
    *,
    duration_s: float = 3.0,
    should_stop: Callable[[], bool] | None = None,
) -> float:
    """Record ``duration_s`` from a device, reporting live RMS to ``on_level``.

    This is the headless, GUI-facing counterpart to :func:`test_input_device`
    (which prints an ASCII bar and plays the take back). For every captured block
    ``on_level(rms, running_peak)`` is invoked so the caller can drive a live level
    meter, then the overall peak is returned. Raises :class:`AudioInputError` on a
    capture failure so the server can report it as a failed RPC.

    Runs synchronously and is meant to be called from a worker thread
    (``asyncio.to_thread``) so it never blocks the engine's event loop.
    """
    _require_audio()
    if not _HAVE_NUMPY:
        raise AudioInputError("numpy is not installed; the mic level test needs it.")
    device_index = resolve_input_device(device_index)
    try:
        sample_rate = int(sd.query_devices(device_index)["default_samplerate"])
    except Exception as exc:  # pragma: no cover - host audio dependent
        raise AudioInputError(f"could not query microphone: {exc}") from exc

    chunk = 2048
    channels = _input_channels(device_index)
    peak = 0.0
    try:
        with sd.InputStream(
            device=device_index, samplerate=sample_rate,
            channels=channels, dtype="int16", blocksize=chunk,
        ) as stream:
            blocks = max(1, int(sample_rate * duration_s / chunk))
            for _ in range(blocks):
                if should_stop is not None and should_stop():
                    break
                frame, _ = stream.read(chunk)
                rms = _rms_int16(_mono_bytes(frame))
                peak = max(peak, rms)
                on_level(rms, peak)
    except AudioInputError:
        raise
    except Exception as exc:
        raise AudioInputError(f"microphone capture failed: {exc}") from exc
    return peak


def test_input_device(device_index: int) -> None:
    """Record ~3s from the device with a live level meter, then play it back.

    Lets the user confirm the right mic is selected and that capture actually works 
    the level bar moves when you talk, and you hear yourself on playback.
    """
    if not _HAVE_NUMPY:
        print("[mic test] numpy not available! skipping mic test.")
        return
    try:
        sample_rate = int(sd.query_devices(device_index)["default_samplerate"])
    except Exception as exc:  # pragma: no cover - host audio dependent
        print(f"[mic test] could not query device: {exc}")
        return

    chunk = 2048
    duration = 3.0
    channels = _input_channels(device_index)
    frames: list[bytes] = []
    print("\n[mic test] Recording 3 seconds. Say something now. Watch the level:")
    try:
        with sd.InputStream(
            device=device_index, samplerate=sample_rate,
            channels=channels, dtype="int16", blocksize=chunk,
        ) as stream:
            for _ in range(int(sample_rate * duration / chunk)):
                frame, _ = stream.read(chunk)
                data = _mono_bytes(frame)
                frames.append(data)
                rms = _rms_int16(data)
                bar = "#" * min(40, int(rms / 150))
                print(f"\r  level |{bar:<40}| {int(rms):5d}", end="", flush=True)
        print()
    except Exception as exc:
        print(f"\n[mic test] recording failed: {exc}")
        return

    peak = max((_rms_int16(f) for f in frames), default=0.0)
    if peak < 100:
        print("[mic test] WARNING: almost no signal detected. Maybe wrong device, muted, or "
              "the OS isn't routing this mic. Pick another one.")

    print("[mic test] Playing it back...")
    try:
        audio = np.frombuffer(b"".join(frames), dtype=np.int16)
        sd.play(audio, samplerate=sample_rate)
        sd.wait()
    except Exception as exc:
        print(f"[mic test] playback failed (capture may still be fine): {exc}")


def pick_input_device(preferred_index: int | None = None) -> int | None:
    """Console picker for the input device. Returns a sounddevice device index (or None).

    Mirrors :func:`model_picker._prompt_pick` (1-based). After a pick, the mic is tested
    (record + playback) and confirmed before returning. ``preferred_index`` (from config)
    is the sounddevice index offered as the default.
    """
    device_map = _enumerate_input_devices()
    if not device_map:
        raise AudioInputError("no input devices found. Is a microphone connected?")

    if len(device_map) == 1:
        sd_idx, name = device_map[0]
        print(f"[mic] using the only input device: {name}")
        test_input_device(sd_idx)
        return sd_idx

    while True:
        print("\nAvailable microphones:")
        default_choice = ""
        for display_no, (sd_idx, name) in enumerate(device_map, start=1):
            saved = sd_idx == preferred_index
            if saved:
                default_choice = str(display_no)
            tag = "  (saved)" if saved else ""
            print(f"  [{display_no}] {name}{tag}")

        hint = f" [{default_choice}]" if default_choice else ""
        raw = input(f"Pick a microphone (1-{len(device_map)}){hint}: ").strip()
        if not raw and default_choice:
            raw = default_choice
        if not raw.isdigit() or not (1 <= int(raw) <= len(device_map)):
            print(f"Enter a number 1-{len(device_map)}.")
            continue

        sd_idx, name = device_map[int(raw) - 1]
        test_input_device(sd_idx)
        confirm = input(f"Use '{name}'? [Y/n]: ").strip().lower()
        if confirm in ("", "y", "yes"):
            return sd_idx
        # Anything else: loop back to the list and let them re-pick.


# --------------------------------------------------------------------------------------
# Speech-to-text backends
# --------------------------------------------------------------------------------------

class SttBackend(ABC):
    """Turns a captured :class:`sr.AudioData` phrase into text."""

    name: str
    # True if the backend can transcribe incrementally (interim "partial" hypotheses as
    # the user speaks), via new_stream/accept_stream/final_stream. Vosk can; Google can't.
    supports_streaming: bool = False

    @abstractmethod
    def transcribe(self, recognizer: "sr.Recognizer", audio: "sr.AudioData") -> str:
        ...

    # Streaming API  only meaningful when ``supports_streaming`` is True.
    def new_stream(self, sample_rate: int):
        """Create a per-phrase streaming recognizer. Override in streaming backends."""
        raise NotImplementedError

    def accept_stream(self, rec, frame_bytes: bytes) -> str:
        """Feed one mono int16 frame; return the interim partial text so far."""
        raise NotImplementedError

    def final_stream(self, rec) -> str:
        """Finalize the phrase and return the recognized text."""
        raise NotImplementedError


class GoogleBackend(SttBackend):
    """Online STT via SpeechRecognition's free Google Web Speech endpoint."""

    name = "google"

    def transcribe(self, recognizer, audio) -> str:
        try:
            return recognizer.recognize_google(audio)
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as exc:
            raise AudioInputError(f"Google STT request failed: {exc}") from exc


class VoskBackend(SttBackend):
    """Offline STT via Vosk.

    Model resolution order:
    1. ``model_path`` from config (manual download + unzip, any model size).
    2. The path where ``sprc download vosk`` puts the model automatically
       (``<SpeechRecognition package>/models/vosk``).

    If neither exists, a clear error is printed at startup.
    Vosk models are trained at 16 kHz; audio is resampled before recognition.
    """

    name = "vosk"
    supports_streaming = True
    _VOSK_SAMPLE_RATE = 16_000

    def __init__(self, model_path: str) -> None:
        try:
            from vosk import Model, KaldiRecognizer  # noqa: F401 – import check
            self._Model = Model
            self._KaldiRecognizer = KaldiRecognizer
        except ImportError as exc:
            raise AudioInputError("vosk is not installed (pip install vosk).") from exc

        resolved = self._resolve_model_path(model_path)
        try:
            self._model = self._Model(resolved)
        except Exception as exc:
            raise AudioInputError(
                f"could not load Vosk model at '{resolved}': {exc}"
            ) from exc

    @staticmethod
    def _resolve_model_path(model_path: str) -> str:
        from pathlib import Path

        # Explicit path from config. use it if it exists.
        if model_path:
            p = Path(model_path)
            if p.exists():
                return str(p)
            raise AudioInputError(
                f"vosk_model_path '{model_path}' does not exist. "
                "Check the path in config.json (point at the unzipped folder "
                "containing am/, conf/, graph/)."
            )

        # Fall back to the path used by `sprc download vosk` (SpeechRecognition >= 3.10).
        try:
            import speech_recognition as _sr
            sprc_path = Path(_sr.__file__).parent / "models" / "vosk"
            if sprc_path.exists():
                return str(sprc_path)
        except Exception:
            pass

        raise AudioInputError(
            "No Vosk model found. Either:\n"
            "  a) Run 'sprc download vosk' to download the default model, or\n"
            "  b) Download a model from https://alphacephei.com/vosk/models, unzip it,\n"
            "     and set 'audio.vosk_model_path' in config.json to the folder path."
        )

    def transcribe(self, _recognizer, audio) -> str:
        # Resample to 16 kHz / mono 16-bit  the sample rate Vosk models are trained on.
        # Passing the raw device rate (44100, 48000…) gives garbled / empty results.
        raw = audio.get_raw_data(
            convert_rate=self._VOSK_SAMPLE_RATE, convert_width=2
        )
        rec = self._KaldiRecognizer(self._model, self._VOSK_SAMPLE_RATE)
        rec.AcceptWaveform(raw)
        try:
            result = json.loads(rec.FinalResult())
            return result.get("text", "").strip()
        except (json.JSONDecodeError, AttributeError):
            return ""

    # Streaming: Vosk accepts audio at the recognizer's declared sample rate and resamples
    # to the model's 16 kHz internally, so we hand it native device-rate mono frames as they
    # arrive and read PartialResult() for the words recognized so far.
    def new_stream(self, sample_rate: int):
        return self._KaldiRecognizer(self._model, sample_rate)

    def accept_stream(self, rec, frame_bytes: bytes) -> str:
        try:
            rec.AcceptWaveform(frame_bytes)
            return json.loads(rec.PartialResult()).get("partial", "").strip()
        except (json.JSONDecodeError, AttributeError):
            return ""

    def final_stream(self, rec) -> str:
        try:
            return json.loads(rec.FinalResult()).get("text", "").strip()
        except (json.JSONDecodeError, AttributeError):
            return ""


def pick_stt_engine(vosk_model_path: str = "", default: str = "") -> SttBackend:
    """Startup picker: offline Vosk vs online Google."""
    _require_audio()
    print("\nPick a speech-to-text engine:")
    print("  [1] Vosk (offline, runs on the Pi, needs a model file)")
    print("  [2] Google (online, no model file, needs internet)")
    default_choice = {"vosk": "1", "google": "2"}.get(default, "")
    hint = f" [{default_choice}]" if default_choice else ""
    while True:
        raw = input(f"> {hint} ").strip() or default_choice
        if raw == "1":
            return VoskBackend(vosk_model_path)
        if raw == "2":
            return GoogleBackend()
        print("Enter 1 or 2.")


# --------------------------------------------------------------------------------------
# Microphone capture
# --------------------------------------------------------------------------------------

def _rms_int16(frame: bytes) -> float:
    """Root-mean-square loudness of a 16-bit PCM frame (audioop is gone in 3.13+)."""
    if not frame or not _HAVE_NUMPY:
        return 0.0
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples * samples)))


def _mono_bytes(frame) -> bytes:
    """Collapse a sounddevice int16 read (shape (n,) or (n, channels)) to mono PCM bytes.

    Recording at the device's native channel count and downmixing here (rather than asking
    PortAudio for 1 channel) avoids the stereo-interleaved-as-mono bug that made playback
    sound an octave too low, and keeps WASAPI happy with the device's real format.
    """
    if frame.ndim == 2 and frame.shape[1] > 1:
        # int32 accumulator so summing channels can't overflow int16.
        frame = frame.astype(np.int32).mean(axis=1).astype(np.int16)
    return np.ascontiguousarray(frame.reshape(-1)).tobytes()


def _is_usable_input_index(index: int) -> bool:
    """True when ``index`` is a PortAudio device with at least one input channel."""
    try:
        info = sd.query_devices(int(index))
        return int(info.get("max_input_channels", 0)) > 0
    except Exception:  # pragma: no cover - host audio dependent
        return False


def _system_default_input_index() -> int | None:
    """PortAudio / OS default input index, or ``None`` if it cannot be resolved.

    Order matters: prefer ``sd.default.device``'s input half, then the current
    host API's ``default_input_device``, then ``query_devices(kind='input')``.
    Do **not** use the first name in :func:`_enumerate_input_devices` here —
    picker list order is not the system default.
    """
    candidates: list[int] = []

    try:
        default = sd.default.device
        if isinstance(default, (list, tuple)) and default:
            candidate = default[0]
            if candidate is not None and int(candidate) >= 0:
                candidates.append(int(candidate))
        elif isinstance(default, int) and default >= 0:
            candidates.append(int(default))
    except Exception:  # pragma: no cover - host audio dependent
        pass

    try:
        hostapi = sd.query_hostapis(sd.default.hostapi)
        candidate = hostapi.get("default_input_device")
        if candidate is not None and int(candidate) >= 0:
            candidates.append(int(candidate))
    except Exception:  # pragma: no cover - host audio dependent
        pass

    for idx in candidates:
        if _is_usable_input_index(idx):
            return idx

    try:
        info = sd.query_devices(kind="input")
        if not isinstance(info, dict):
            return None
        if "index" in info and int(info["index"]) >= 0 and _is_usable_input_index(int(info["index"])):
            return int(info["index"])
        name = info.get("name")
        hostapi = info.get("hostapi")
        for idx, device in enumerate(sd.query_devices()):
            if device.get("name") != name:
                continue
            if hostapi is not None and device.get("hostapi") != hostapi:
                continue
            if int(device.get("max_input_channels", 0)) > 0:
                return idx
    except Exception:  # pragma: no cover - host audio dependent
        pass
    return None


def resolve_input_device(device_index: int | None) -> int:
    """Return a concrete sounddevice input index.

    ``None`` means the OS / PortAudio default input. Passing that straight to
    ``sd.query_devices`` returns the full device list, so
    ``info["default_samplerate"]`` raises
    ``TypeError: tuple indices must be integers or slices, not str`` and the
    capture thread exits. Resolve a real index before any query/open.

    When unset, this uses the system default — not the first microphone in the
    picker list (those orders differ on multi-mic machines).
    """
    _require_audio()
    if device_index is not None:
        return int(device_index)

    default_idx = _system_default_input_index()
    if default_idx is not None:
        return default_idx

    devices = _enumerate_input_devices()
    if len(devices) == 1:
        return devices[0][0]
    if devices:
        # PortAudio exposed no default index; only then fall back to list order.
        print(
            "[mic] system default input index unavailable; "
            f"using first listed microphone: {devices[0][1]}"
        )
        return devices[0][0]
    raise AudioInputError("no input devices found. Is a microphone connected?")


def _input_channels(device_index: int | None) -> int:
    """Channels to open for capture: the device's native count, capped at stereo."""
    try:
        info = sd.query_devices(resolve_input_device(device_index))
        return max(1, min(2, int(info["max_input_channels"])))
    except Exception:  # pragma: no cover - host audio dependent
        return 1


class AudioInput:
    """Background microphone capture with VAD endpointing and voice barge-in.

    One capture thread owns the sounddevice stream and loops: wait for speech onset, record
    the phrase until silence, transcribe, and push the text onto an asyncio queue that
    :meth:`next_utterance` awaits. While the bot is speaking (:meth:`set_speaking`),
    detecting onset *also* fires the ``on_barge_in`` callback immediately  that's the
    voice-interrupt path, distinct from the keyboard path.

    Modes (:meth:`set_mode`): ``vad`` = open mic / continuous, ``muted`` = ignore the
    mic, ``ptt`` = parked until :meth:`trigger_ptt` arms a single capture.
    """

    # Onset needs sustained loudness so a single click does not trip a barge-in.
    _ONSET_FRAMES = 4
    # Rolling pre-buffer kept ahead of onset so the frames that *proved* loudness
    # (and a touch of leading silence) are handed to the recognizer instead of lost.
    _PREROLL_FRAMES = _ONSET_FRAMES + 2
    # Phrase ends after this many consecutive quiet frames.
    _SILENCE_FRAMES = 25
    # Hard cap so a noisy room cannot record forever.
    _MAX_PHRASE_FRAMES = 500
    # Floor for the onset threshold so a dead-silent room doesn't make it hyper-sensitive.
    _MIN_THRESHOLD = 250.0

    def __init__(
        self,
        device_index: int | None,
        backend: SttBackend,
        *,
        loop: asyncio.AbstractEventLoop,
        barge_in_threshold_factor: float = 2.5,
    ) -> None:
        _require_audio()
        self._device_index = device_index
        self._backend = backend
        self._loop = loop
        self._barge_in_factor = barge_in_threshold_factor
        # Calibrated from ambient noise during startup.
        self._energy_threshold = 300.0

        self._recognizer = sr.Recognizer()
        self._queue: asyncio.Queue[str] = asyncio.Queue()

        self._mode: ListenMode = "vad"
        self._speaking = threading.Event()
        self._ptt_armed = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        # Set by the demo so an onset while speaking can raise the interrupt.
        self.on_barge_in: Callable[[], None] | None = None
        # Fired when the user starts / stops talking, so the behavior manager can
        # switch the robot into its attentive "listening" pose (nodding along).
        # Called from the capture thread  handlers must be thread-safe.
        self.on_user_speech_start: Callable[[], None] | None = None
        self.on_user_speech_end: Callable[[], None] | None = None
        # Fired repeatedly with the interim transcript while the user is still speaking
        # (streaming backends only, e.g. Vosk). Lets a GUI show words as they are said.
        self.on_partial: Callable[[str], None] | None = None

    # -- lifecycle -------------------------------------------------------------------

    def start(self) -> None:
        """Start the capture thread. Never opens a second stream beside a live one.

        If a previous :meth:`stop` is still winding down (``_stop`` set, thread alive),
        this waits for that thread to finish before clearing the stop flag and starting
        again — so mute→unmute cannot leave two capture loops on the same device.
        """
        if self._thread is not None and self._thread.is_alive():
            if not self._stop.is_set():
                return  # already capturing
            if not self.stop(timeout=10.0):
                raise AudioInputError(
                    "previous microphone capture is still stopping; try mute again."
                )
        self._thread = None
        self._stop.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="obot-mic")
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> bool:
        """Signal the capture thread to exit and wait for it.

        Returns ``True`` when no capture thread is running afterward. If the thread is
        still alive after ``timeout``, this keeps the handle (does **not** set
        ``_thread`` to ``None``) so a later :meth:`start` cannot open a second stream.
        """
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        if thread is not None and thread.is_alive():
            return False
        self._thread = None
        return True

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- state toggles ---------------------------------------------------------------

    def set_speaking(self, speaking: bool) -> None:
        if speaking:
            self._speaking.set()
        else:
            self._speaking.clear()

    def is_speaking(self) -> bool:
        return self._speaking.is_set()

    def set_mode(self, mode: ListenMode) -> None:
        self._mode = mode
        if mode != "ptt":
            self._ptt_armed.clear()
        print(f"[mic] mode -> {mode}")

    @property
    def mode(self) -> ListenMode:
        return self._mode

    def trigger_ptt(self) -> None:
        """Arm a single capture in push-to-talk mode."""
        if self._mode == "ptt":
            self._ptt_armed.set()

    async def next_utterance(self) -> str:
        return await self._queue.get()

    def drain_queue(self) -> None:
        """Drop any utterances captured while we weren't listening (e.g. console mode)."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def _publish(self, text: str) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, text)

    # -- capture thread --------------------------------------------------------------

    def _capture_loop(self) -> None:
        try:
            device_index = resolve_input_device(self._device_index)
            device_info = sd.query_devices(device_index)
            sample_rate = int(device_info["default_samplerate"])
        except Exception as exc:  # pragma: no cover - host audio dependent
            print(f"[mic] could not query microphone: {exc}")
            events.emit(events.ERROR, {"where": "mic", "message": f"could not open microphone: {exc}"})
            return
        device_name = str(device_info.get("name", "?"))

        # Capture at the device's native channel count and downmix to mono ourselves
        # (see _mono_bytes). The recognizers expect mono 16-bit; forcing PortAudio to 1
        # channel produced octave-low / garbled audio on some Windows devices.
        stream_kwargs = dict(
            device=device_index,
            samplerate=sample_rate,
            channels=_input_channels(device_index),
            dtype="int16",
            blocksize=4096,
        )

        try:
            # Calibrate ambient noise: record silence for 0.6s and measure baseline RMS.
            print("[mic] calibrating (stay quiet)...")
            with sd.InputStream(**stream_kwargs) as stream:
                silence_frames = []
                for _ in range(int(sample_rate * 0.6 / 4096)):
                    if self._stop.is_set():
                        return
                    frame, _ = stream.read(4096)
                    silence_frames.append(_mono_bytes(frame))
                silence_rms = _rms_int16(b"".join(silence_frames))
                self._energy_threshold = max(self._MIN_THRESHOLD, silence_rms * 1.5)
            if self._stop.is_set():
                return
            print(f"[mic] calibrated (onset threshold {int(self._energy_threshold)}). Listening.")
            events.emit(events.LOG, {"level": "info",
                                     "message": f"microphone open on '{device_name}'  "
                                                f"listening ({self._mode}, onset {int(self._energy_threshold)})"})

            with sd.InputStream(**stream_kwargs) as stream:
                while not self._stop.is_set():
                    if not self._should_capture():
                        self._stop.wait(0.05)
                        continue
                    armed_ptt = self._mode == "ptt"
                    try:
                        text = self._capture_phrase(stream, sample_rate)
                    except AudioInputError as exc:
                        print(f"[mic] {exc}")
                        # Surface STT failures (e.g. the Google endpoint erroring) to the GUI
                        # instead of silently swallowing them  otherwise the mic looks dead.
                        events.emit(events.ERROR, {"where": "speech-to-text", "message": str(exc)})
                        text = ""
                    if armed_ptt:
                        self._ptt_armed.clear()
                    # Publish every finished phrase, including an empty one: the empty
                    # result lets a listener clear its "listening…" indicator (the console
                    # loop simply skips blanks).
                    self._publish(text)
        except Exception as exc:  # pragma: no cover - host audio dependent
            print(f"[mic] capture loop stopped: {exc}")
            events.emit(events.ERROR, {"where": "mic", "message": f"capture stopped: {exc}"})

    def _should_capture(self) -> bool:
        if self._mode == "muted":
            return False
        if self._mode == "ptt":
            return self._ptt_armed.is_set()
        return True  # vad

    def _capture_phrase(self, stream: "sd.InputStream", sample_rate: int) -> str:
        """Wait for onset, record until silence, then transcribe. Onset while the bot
        is speaking fires the barge-in callback right away."""
        chunk = 4096
        base_threshold = self._energy_threshold

        if not _HAVE_NUMPY:
            # Can't do onset detection without numpy; skip this backend entirely.
            return ""

        # Phase A: wait for onset (also the barge-in trigger). Every frame read here is
        # kept in a short rolling pre-buffer so that once onset fires, the loud frames
        # that proved it (plus a touch of leading silence) are still available instead
        # of only the single frame where the run happened to cross the threshold 
        # otherwise the start of the word that triggered detection gets cut off.
        loud_run = 0
        preroll: deque[bytes] = deque(maxlen=self._PREROLL_FRAMES)
        while not self._stop.is_set() and self._should_capture():
            frame, _ = stream.read(chunk)
            frame_bytes = _mono_bytes(frame)
            preroll.append(frame_bytes)
            speaking = self._speaking.is_set()
            threshold = base_threshold * (self._barge_in_factor if speaking else 1.0)
            if _rms_int16(frame_bytes) >= threshold:
                loud_run += 1
                if loud_run >= self._ONSET_FRAMES:
                    if speaking:
                        # Cut the bot off, but do NOT treat speaker bleed as a new user
                        # turn — that creates an endless echo loop (TTS → mic → same
                        # phrase again). Discard frames until TTS actually stops, then
                        # require a fresh onset for the real follow-up utterance.
                        if self.on_barge_in is not None:
                            self.on_barge_in()
                        # Cap the wait so a stuck speaking flag cannot deafen VAD forever
                        # (e.g. turn-level flags that outlive audible playback).
                        deaf_until = time.monotonic() + 8.0
                        while (
                            self._speaking.is_set()
                            and not self._stop.is_set()
                            and self._should_capture()
                            and time.monotonic() < deaf_until
                        ):
                            stream.read(chunk)
                        loud_run = 0
                        preroll.clear()
                        continue
                    self._notify(self.on_user_speech_start)
                    try:
                        return self._record_phrase(
                            stream, sample_rate, list(preroll), base_threshold
                        )
                    finally:
                        self._notify(self.on_user_speech_end)
            else:
                loud_run = 0
        return ""

    @staticmethod
    def _notify(callback: Callable[[], None] | None) -> None:
        # Listener callbacks must never be able to kill the capture loop.
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:  # pragma: no cover - user-supplied handler
            print(f"[mic] listener callback failed: {exc}")

    def _record_phrase(
        self,
        stream: "sd.InputStream",
        sample_rate: int,
        prefix: list[bytes],
        threshold: float,
    ) -> str:
        chunk = 4096
        streaming = self._backend.supports_streaming and self.on_partial is not None
        rec = self._backend.new_stream(sample_rate) if streaming else None
        frames: list[bytes] = list(prefix)
        quiet_run = 0
        last_partial = ""

        if streaming:
            # Seed the recognizer with the onset frames captured before endpointing began.
            for fb in prefix:
                self._backend.accept_stream(rec, fb)

        while not self._stop.is_set() and len(frames) < self._MAX_PHRASE_FRAMES:
            if not self._should_capture():
                break
            frame, _ = stream.read(chunk)
            frame_bytes = _mono_bytes(frame)
            frames.append(frame_bytes)
            if streaming:
                partial = self._backend.accept_stream(rec, frame_bytes)
                if partial and partial != last_partial:
                    last_partial = partial
                    self._notify(lambda p=partial: self.on_partial(p))  # type: ignore[misc]
            if _rms_int16(frame_bytes) < threshold:
                quiet_run += 1
                if quiet_run >= self._SILENCE_FRAMES:
                    break
            else:
                quiet_run = 0

        if streaming:
            return self._backend.final_stream(rec)
        audio = sr.AudioData(b"".join(frames), sample_rate, 2)
        return self._backend.transcribe(self._recognizer, audio)
