from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .ml.config import MLSettings
from .robot.behaviors import BehaviorSettings
from .speech.config import MotionSettings, SpeechSettings

CONFIG_FILENAME = "config.json"
EXAMPLE_FILENAME = "config.example.json"
# Hard cap on how many "recent models" we remember per backend.
RECENTS_CAP = 3

# Where the OhBot usually shows up when nothing is configured yet: COM7 on Windows,
# the first USB CDC device on Linux/the Pi. Only a starting point  the ohbot library
# scans every serial port anyway; this one is just tried first.
DEFAULT_OHBOT_PORT = "COM7" if sys.platform == "win32" else "/dev/ttyACM0"


@dataclass
class OllamaSSHConfig:
    host: str = ""
    port: int = 22
    user: str = ""
    key_path: str = ""
    remote_ollama_host: str = "localhost"
    remote_ollama_port: int = 11434


@dataclass
class AudioConfig:
    # Persisted so the mic/STT pickers can offer the last choice as the default.
    input_device_index: int | None = None
    stt_engine: str = ""  # "vosk" | "google"
    vosk_model_path: str = ""


@dataclass
class Config:
    gemini_api_key: str = ""
    ollama_ssh: OllamaSSHConfig = field(default_factory=OllamaSSHConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    recent_gemini_models: list[str] = field(default_factory=list)
    recent_ollama_models: list[str] = field(default_factory=list)
    ohbot_port: str = DEFAULT_OHBOT_PORT
    # Speech stack (TTS engine choice, voices, mouth animation), servo mixing,
    # and ambient behavior tunables. All optional in config.json  defaults apply.
    speech: SpeechSettings = field(default_factory=SpeechSettings)
    motion: MotionSettings = field(default_factory=MotionSettings)
    behaviors: BehaviorSettings = field(default_factory=BehaviorSettings)
    # The gesture-model library the GUI's ML Control page manages. Only that page
    # reads it -- the speech engine takes its checkpoint from speech.gesture.
    ml: MLSettings = field(default_factory=MLSettings)

    _path: Path | None = field(default=None, repr=False, compare=False)

    def record_gemini_model(self, model: str) -> None:
        self.recent_gemini_models = _bump(self.recent_gemini_models, model)
        self.save()

    def record_ollama_model(self, model: str) -> None:
        self.recent_ollama_models = _bump(self.recent_ollama_models, model)
        self.save()

    def record_audio(
        self,
        *,
        input_device_index: int | None = None,
        stt_engine: str | None = None,
    ) -> None:
        if input_device_index is not None:
            self.audio.input_device_index = input_device_index
        if stt_engine is not None:
            self.audio.stt_engine = stt_engine
        self.save()

    def to_dict(self) -> dict:
        """Serialize to the exact JSON shape written to config.json (round-trips with from_dict)."""
        return {
            "gemini_api_key": self.gemini_api_key,
            "ollama_ssh": asdict(self.ollama_ssh),
            "audio": asdict(self.audio),
            "recent_gemini_models": self.recent_gemini_models,
            "recent_ollama_models": self.recent_ollama_models,
            "ohbot_port": self.ohbot_port,
            "speech": self.speech.to_dict(),
            "motion": self.motion.to_dict(),
            "behaviors": self.behaviors.to_dict(),
            "ml": self.ml.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict, path: Path | None = None) -> "Config":
        """Build a Config from parsed JSON, applying defaults for missing keys.

        Shared by :func:`load_config` (reading the file) and the control server's
        ``set_config`` (validating an edited config before saving), so both paths
        parse identically.
        """
        ssh_data = data.get("ollama_ssh") or {}
        audio_data = data.get("audio") or {}
        device_index = audio_data.get("input_device_index")
        cfg = cls(
            gemini_api_key=data.get("gemini_api_key", ""),
            ollama_ssh=OllamaSSHConfig(
                host=ssh_data.get("host", ""),
                port=int(ssh_data.get("port", 22)),
                user=ssh_data.get("user", ""),
                key_path=ssh_data.get("key_path", ""),
                remote_ollama_host=ssh_data.get("remote_ollama_host", "localhost"),
                remote_ollama_port=int(ssh_data.get("remote_ollama_port", 11434)),
            ),
            audio=AudioConfig(
                input_device_index=int(device_index) if device_index is not None else None,
                stt_engine=audio_data.get("stt_engine", ""),
                vosk_model_path=audio_data.get("vosk_model_path", ""),
            ),
            recent_gemini_models=list(data.get("recent_gemini_models", [])),
            recent_ollama_models=list(data.get("recent_ollama_models", [])),
            ohbot_port=data.get("ohbot_port", DEFAULT_OHBOT_PORT),
            speech=SpeechSettings.from_dict(data.get("speech")),
            motion=MotionSettings.from_dict(data.get("motion")),
            behaviors=BehaviorSettings.from_dict(data.get("behaviors")),
            ml=MLSettings.from_dict(data.get("ml")),
        )
        cfg._path = path
        return cfg

    def save(self) -> None:
        if self._path is None:
            return
        # Atomic write: write to a temp file in the same directory then rename.
        # Protects the config from being half written if the process is killed mid save.
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def save_to(self, path: Path) -> None:
        """Point this config at ``path`` and save (used to create config.json from the GUI)."""
        self._path = path
        self.save()


def _bump(recents: list[str], model: str) -> list[str]:
    # MRU ordering: drop the model if it already appears, then put it at the front.
    # The cap keeps the list at three so the quick access menu never grows.
    deduped = [m for m in recents if m != model]
    return ([model] + deduped)[:RECENTS_CAP]


def _project_root() -> Path:
    # config.json lives at the repo root, two levels up from src/obot/config.py.
    return Path(__file__).resolve().parents[2]


def load_config() -> Config:
    root = _project_root()
    path = root / CONFIG_FILENAME
    if not path.exists():
        example = root / EXAMPLE_FILENAME
        raise FileNotFoundError(
            f"Missing {CONFIG_FILENAME}. Copy {example.name} to {path.name} and fill in your credentials."
        )

    data = json.loads(path.read_text(encoding="utf-8"))
    return Config.from_dict(data, path=path)


def config_path() -> Path:
    """Absolute path to config.json (whether or not it exists yet)."""
    return _project_root() / CONFIG_FILENAME
