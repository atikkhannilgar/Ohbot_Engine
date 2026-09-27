"""Finds, names and describes gesture-model checkpoints for the GUI's ML Control page.

Two sources feed the model library: the named entries in config.json's ``ml.models``,
and a scan of the folders where checkpoints actually land -- ``mlBehaviour/runs/<run>/``
(train.py's output) and ``src/obot/ml/models/`` (models supplied locally).
So a freshly trained run shows up in the GUI without anyone editing config.json first.

Everything here stays torch-free at *import* time: listing the library, resolving paths
and browsing the dataset must work on a checkout that never installed torch. Only
:func:`inspect_checkpoint` (which has to open the file) imports it, lazily.
"""

from __future__ import annotations

import csv
import importlib
import importlib.metadata
import importlib.util
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..robot import joints

# src/obot/ml/registry.py -> ml -> obot -> src -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]

# Folders scanned for checkpoints: where train.py writes its named runs, and the
# checkpoints added locally; none are bundled in the review package.
DEFAULT_SCAN_DIRS: tuple[str, ...] = ("src/obot/ml/models", "mlBehaviour/runs")

# Default output of "beat2_to_ohbot.py convert", used for ground-truth clip replay.
DEFAULT_MANIFEST = REPO_ROOT / "mlBehaviour" / "ohbot_data" / "manifest.csv"

CHECKPOINT_SUFFIX = ".pt"

# Requirements file that installs everything below (see requirements/ml.txt).
ML_REQUIREMENTS_FILE = "requirements/ml.txt"

# Third-party modules the inference path actually imports, with why -- so the GUI can say
# what is missing instead of just failing on the first model load. scipy is not optional
# despite only being used for one conversion helper: inference.py executes
# beat2_to_ohbot.py, which imports scipy.spatial.transform at module level.
ML_MODULES: tuple[tuple[str, str], ...] = (
    ("torch", "runs the model"),
    ("numpy", "audio and pose arrays"),
    ("scipy", "resampling and rotation maths in beat2_to_ohbot.py"),
    ("soundfile", "reads the .wav files a preview plays"),
)

# The training pipeline itself: inference.py loads the architecture and feature extraction
# from these files rather than duplicating them, so a checkout missing mlBehaviour/ cannot
# run a model no matter which packages are installed.
ML_PIPELINE_FILES: tuple[str, ...] = (
    "mlBehaviour/model.py",
    "mlBehaviour/features.py",
    "mlBehaviour/beat2_to_ohbot.py",
)

# Column order beat2_to_ohbot.py writes motion targets in (OHBOT_AXES) -- a checkpoint's
# output columns line up with this, in order, left to right. Defined here rather than in
# inference.py so the axis mapping is available without importing torch (the GUI's model
# listing and replay_dataset.py both need it, neither needs a model).
AXIS_ORDER: tuple[str, ...] = (
    "HEADNOD", "HEADTURN", "EYETURN", "EYETILT", "LIDBLINK", "TOPLIP", "BOTTOMLIP", "HEADTILT",
)

AXIS_TO_JOINT: dict[str, int] = {
    "HEADNOD": joints.HEADNOD,
    "HEADTURN": joints.HEADTURN,
    "EYETURN": joints.EYETURN,
    "EYETILT": joints.EYETILT,
    "LIDBLINK": joints.LIDBLINK,
    "TOPLIP": joints.TOPLIP,
    "BOTTOMLIP": joints.BOTTOMLIP,
    "HEADTILT": joints.HEADTILT,
}


def resolve_path(path: str | Path) -> Path:
    """Absolute path for a config value.

    Relative paths are resolved against the repo root, not the cwd: config.json stores
    paths like ``src/obot/ml/models/x.pt`` and the engine gets launched from anywhere
    (the GUI's child process, a service unit, a shell in some subfolder).
    """
    p = Path(str(path)).expanduser()
    return p if p.is_absolute() else REPO_ROOT / p


def display_path(path: str | Path) -> str:
    """Repo-relative POSIX form when the file lives inside the checkout, else absolute.

    This is the form written back into config.json, so registering a model through the
    GUI keeps the config portable instead of baking in one machine's home directory.
    """
    resolved = resolve_path(path)
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _default_name(path: Path) -> str:
    """Readable name for a discovered checkpoint: run folder plus file stem inside a
    train.py run, plain stem for the loose checkpoints in ml/models."""
    parent = path.parent.name
    if parent and parent != "models":
        return f"{parent} / {path.stem}"
    return path.stem


def _timestamp(path: Path) -> str | None:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat(timespec="seconds")


def describe(
    path: str | Path,
    *,
    name: str = "",
    notes: str = "",
    source: str = "discovered",
    selected: bool = False,
) -> dict[str, Any]:
    """One model-library row for the GUI: identity plus what we know without torch."""
    resolved = resolve_path(path)
    exists = resolved.is_file()
    return {
        "name": name or _default_name(resolved),
        "path": display_path(resolved),
        "abs_path": str(resolved),
        "notes": notes,
        # "registry" = a named entry from config.json, "discovered" = found by the scan.
        "source": source,
        "exists": exists,
        "size_bytes": resolved.stat().st_size if exists else 0,
        "modified": _timestamp(resolved) if exists else None,
        "selected": selected,
    }


def scan_dirs(cfg) -> list[str]:
    """Folders to scan: the built-in ones plus anything in ``ml.scan_dirs``."""
    extra = list(getattr(cfg.ml, "scan_dirs", []) or []) if cfg is not None else []
    seen: list[str] = []
    for entry in [*DEFAULT_SCAN_DIRS, *extra]:
        if entry and entry not in seen:
            seen.append(entry)
    return seen


def discover(dirs: list[str] | tuple[str, ...] = DEFAULT_SCAN_DIRS) -> list[Path]:
    """Every ``*.pt`` under the given folders (recursive), newest first."""
    found: dict[Path, float] = {}
    for entry in dirs:
        root = resolve_path(entry)
        if not root.is_dir():
            continue
        for path in root.rglob(f"*{CHECKPOINT_SUFFIX}"):
            if not path.is_file():
                continue
            try:
                found[path.resolve()] = path.stat().st_mtime
            except OSError:
                continue
    return sorted(found, key=lambda p: found[p], reverse=True)


def list_models(cfg) -> dict[str, Any]:
    """The full model library: registered entries first, then everything discovered.

    Registered entries keep their configured name/notes and their position in
    config.json; a discovered checkpoint that is already registered is not listed twice.
    """
    selected = str(cfg.speech.gesture.checkpoint_path or "")
    selected_resolved = resolve_path(selected) if selected else None

    rows: list[dict[str, Any]] = []
    seen: set[Path] = set()

    for entry in cfg.ml.models:
        if not entry.path:
            continue
        resolved = resolve_path(entry.path)
        seen.add(resolved)
        rows.append(describe(
            resolved, name=entry.name, notes=entry.notes, source="registry",
            selected=resolved == selected_resolved,
        ))

    for path in discover(scan_dirs(cfg)):
        if path in seen:
            continue
        seen.add(path)
        rows.append(describe(path, selected=path == selected_resolved))

    # A configured checkpoint that is neither registered nor discoverable (a path
    # outside every scan folder, or one that has since been deleted) still has to
    # appear -- otherwise the page shows nothing selected while the engine uses it.
    if selected_resolved is not None and selected_resolved not in seen:
        rows.append(describe(selected_resolved, source="configured", selected=True))

    return {
        "models": rows,
        "selected_path": display_path(selected) if selected else "",
        "scan_dirs": scan_dirs(cfg),
        "default_scan_dirs": list(DEFAULT_SCAN_DIRS),
    }


def inspect_checkpoint(path: str | Path) -> dict[str, Any]:
    """Open a train.py checkpoint and report its shape/training metadata.

    Answers what the GUI cannot guess: how many axes the model drives (7 when the data
    was converted with --exclude-head-tilt, 8 otherwise), the hyperparameters inference
    has to match, and how far training got. Imports torch, so this is the one call here
    that needs the ML extras installed.
    """
    resolved = resolve_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"no checkpoint at {resolved}")

    import torch

    ckpt = torch.load(resolved, map_location="cpu", weights_only=False)
    if not isinstance(ckpt, dict) or "model_state" not in ckpt:
        raise ValueError(
            f"{display_path(resolved)} is not a train.py checkpoint (no 'model_state')."
        )

    config = ckpt.get("args") or ckpt.get("config") or {}
    n_axes = int(ckpt.get("n_axes", 0) or 0)
    state = ckpt.get("model_state") or {}
    params = sum(int(t.numel()) for t in state.values() if hasattr(t, "numel"))
    best_val = ckpt.get("best_val")

    return {
        "path": display_path(resolved),
        "run_name": config.get("name") or resolved.parent.name,
        "n_axes": n_axes,
        "axis_names": list(AXIS_ORDER[:n_axes]) if n_axes else [],
        "n_mels": int(config.get("n_mels", 0) or 0),
        "conv_channels": int(config.get("conv_channels", 0) or 0),
        "gru_hidden": int(config.get("gru_hidden", 0) or 0),
        "parameters": params,
        # Present in checkpoint.pt (resumable), absent from best_model.pt.
        "epoch": int(ckpt["epoch"]) if "epoch" in ckpt else None,
        "epochs_planned": int(config.get("epochs", 0) or 0) or None,
        "best_val": float(best_val) if isinstance(best_val, (int, float)) else None,
        "learning_rate": float(config.get("lr", 0) or 0) or None,
        "batch_size": int(config.get("batch_size", 0) or 0) or None,
        "data_dir": config.get("data_dir") or "",
        "size_bytes": resolved.stat().st_size,
        "has_optimizer_state": "optimizer_state" in ckpt,
    }


def _module_available(name: str) -> tuple[bool, str | None]:
    """Is ``name`` importable, and at what version -- without importing it.

    :func:`importlib.util.find_spec` only walks the finders, so this stays cheap even for
    torch. The version comes from package metadata, which likewise needs no import.
    """
    try:
        available = importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        # A half-removed distribution can leave a spec that raises rather than returning None.
        return False, None
    if not available:
        return False, None
    try:
        return True, importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return True, None


def requirements_status() -> dict[str, Any]:
    """Everything the gesture model needs on the engine host, and whether it is there.

    Reported per item so the GUI can list what is missing and offer to install it, rather
    than leaving the user to guess from a failed model load. ``python`` is this engine's own
    interpreter: the GUI installs into *that* environment, so it never has to guess which
    venv the engine was launched from.
    """
    # A pip install into the running engine's venv lands in a directory whose listing the
    # import system has already cached; without this, a just-installed torch stays
    # invisible until the engine restarts.
    importlib.invalidate_caches()

    items: list[dict[str, Any]] = []
    for name, purpose in ML_MODULES:
        available, version = _module_available(name)
        items.append({
            "name": name,
            "kind": "module",
            "purpose": purpose,
            "available": available,
            "detail": version or "",
        })
    for relative in ML_PIPELINE_FILES:
        path = resolve_path(relative)
        items.append({
            "name": relative,
            "kind": "file",
            "purpose": "training pipeline that inference is loaded from",
            "available": path.is_file(),
            "detail": "" if path.is_file() else "missing from this checkout",
        })

    missing = [item["name"] for item in items if not item["available"]]
    return {
        "ready": not missing,
        "missing": missing,
        # Only the modules are pip-installable; a missing mlBehaviour/ file is not.
        "installable": [
            item["name"] for item in items
            if not item["available"] and item["kind"] == "module"
        ],
        "requirements_file": ML_REQUIREMENTS_FILE,
        "requirements_exists": resolve_path(ML_REQUIREMENTS_FILE).is_file(),
        "python": sys.executable,
        "python_version": platform.python_version(),
        "items": items,
    }


def runtime_status(cfg, probe: bool = False) -> dict[str, Any]:
    """What the inference runtime looks like on the engine host.

    ``torch_available`` is answered with :func:`importlib.util.find_spec`, which never
    imports the package -- a status poll must not pay torch's multi-second import. Pass
    ``probe`` (the GUI's explicit check button) to actually import it and report whether
    CUDA is usable; until then ``cuda_available`` is None, meaning "nobody asked".
    """
    requirements = requirements_status()
    available, version = _module_available("torch")

    cuda: bool | None = None
    cuda_devices: list[str] = []
    if available and probe:
        try:
            import torch

            cuda = bool(torch.cuda.is_available())
            if cuda:
                cuda_devices = [
                    torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())
                ]
        except Exception as exc:  # noqa: BLE001 - a broken torch install must not fail the poll
            cuda = False
            cuda_devices = [f"probe failed: {exc}"]

    gesture = cfg.speech.gesture
    checkpoint = str(gesture.checkpoint_path or "")
    return {
        "torch_available": available,
        "torch_version": version,
        "cuda_available": cuda,
        "cuda_devices": cuda_devices,
        "probed": bool(available and probe),
        "enabled": bool(gesture.enabled),
        "checkpoint_path": display_path(checkpoint) if checkpoint else "",
        "checkpoint_exists": bool(checkpoint) and resolve_path(checkpoint).is_file(),
        "control_hz": float(gesture.control_hz),
        "intensity": float(gesture.intensity),
        "device": gesture.device,
        "scripted_mouth": bool(gesture.scripted_mouth),
        # Per-dependency report, so the GUI can offer to install what is missing.
        "requirements": requirements,
    }


def resolve_manifest(manifest: str | Path | None) -> Path:
    return resolve_path(manifest) if manifest else DEFAULT_MANIFEST


def list_clips(manifest: str | Path | None = None) -> dict[str, Any]:
    """Browse a converted BEAT2 dataset (beat2_to_ohbot.py's manifest.csv).

    These are the ground-truth clips the model was trained on; replaying one next to a
    model preview is how you tell "the model is weak" apart from "the conversion is
    wrong". A missing manifest is not an error -- most checkouts have no dataset.
    """
    path = resolve_manifest(manifest)
    result: dict[str, Any] = {
        "manifest": display_path(path),
        "exists": path.is_file(),
        "clips": [],
    }
    if not path.is_file():
        return result

    clips_dir = path.parent / "clips"
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            clip_id = row.get("clip_id") or ""
            if not clip_id:
                continue
            clip_path = clips_dir / f"{clip_id}.npz"
            result["clips"].append({
                "clip_id": clip_id,
                "path": display_path(clip_path),
                "exists": clip_path.is_file(),
                "n_frames": int(float(row.get("n_frames") or 0)),
                "duration_s": float(row.get("duration_s") or 0.0),
            })
    return result
