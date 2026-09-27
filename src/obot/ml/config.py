"""Settings for the gesture-model *library* (config.json's ``ml`` section).

``speech.gesture`` (see speech/config.py) holds the inference settings the speech
engine actually reads: which checkpoint drives the servos, on what device, how hard.
This section is the library around it -- the named checkpoints the GUI's ML Control
page offers, extra folders to scan for more, and the clips used to preview them.
Nothing here is read by the speech engine, so an old config.json keeps working
untouched and a checkout that never installed torch still loads its config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MLModelEntry:
    """One named checkpoint in the library.

    ``path`` points at a train.py checkpoint (``best_model.pt`` / ``checkpoint.pt``).
    Relative paths are resolved against the repo root (see ml/registry.py), so a
    config.json stays portable between machines and whatever cwd the engine runs in.
    """

    name: str = ""
    path: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "MLModelEntry":
        data = data or {}
        return cls(
            name=str(data.get("name", "")),
            path=str(data.get("path", "")),
            notes=str(data.get("notes", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "path": self.path, "notes": self.notes}


@dataclass
class MLSettings:
    # Checkpoints the user registered by name, in the order the GUI lists them.
    models: list[MLModelEntry] = field(default_factory=list)
    # Extra folders searched for *.pt checkpoints on top of the built-in ones
    # (src/obot/ml/models and mlBehaviour/runs). Repo-root-relative or absolute.
    scan_dirs: list[str] = field(default_factory=list)
    # Audio clip the ML Control page's Preview button plays through the model.
    # The default ships with the training pipeline, so Preview works on a fresh checkout.
    preview_wav: str = "mlBehaviour/sample_clip.wav"
    # manifest.csv written by beat2_to_ohbot.py, for ground-truth clip replay.
    dataset_manifest: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "MLSettings":
        data = data or {}
        models = data.get("models") or []
        return cls(
            models=[MLModelEntry.from_dict(m) for m in models if isinstance(m, dict)],
            scan_dirs=[str(d) for d in (data.get("scan_dirs") or [])],
            preview_wav=str(data.get("preview_wav", cls.preview_wav)),
            dataset_manifest=str(data.get("dataset_manifest", cls.dataset_manifest)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "models": [m.to_dict() for m in self.models],
            "scan_dirs": list(self.scan_dirs),
            "preview_wav": self.preview_wav,
            "dataset_manifest": self.dataset_manifest,
        }
