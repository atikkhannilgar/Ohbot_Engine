"""Loads a train.py checkpoint and predicts an Ohbot pose track from audio.

The model architecture and feature extraction are loaded straight from
mlBehaviour/ (the training pipeline) via importlib rather than duplicated
here, so inference always matches whatever code a checkpoint was actually
trained with -- a hand-copied second implementation would silently drift the
moment someone tweaks model.py or features.py for a new training run.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import numpy as np
import torch

from ..robot import joints
from .registry import AXIS_ORDER, AXIS_TO_JOINT, REPO_ROOT, resolve_path

_ML_DIR = REPO_ROOT / "mlBehaviour"


def _load_module(name: str, filename: str) -> ModuleType:
    path = _ML_DIR / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_model_mod = _load_module("obot_ml_beat2_model", "model.py")
_features_mod = _load_module("obot_ml_beat2_features", "features.py")
_convert_mod = _load_module("obot_ml_beat2_convert", "beat2_to_ohbot.py")

OhbotAudioModel = _model_mod.OhbotAudioModel
log_mel_spectrogram = _features_mod.log_mel_spectrogram
normalize_features = _features_mod.normalize_features
resample_channel = _convert_mod.resample_channel

# AXIS_ORDER / AXIS_TO_JOINT live in ml/registry.py (re-exported above): the GUI's
# model listing and replay_dataset.py need the same mapping without importing torch.

# Sample rate beat2_to_ohbot.py resampled training audio to before extracting
# features -- inference must feed the model audio at the same rate.
MODEL_AUDIO_SR = 16000


@dataclass(frozen=True)
class GesturePrediction:
    motion: np.ndarray  # (T, n_axes), values in 0..10
    control_hz: float
    axis_names: list[str]

    def row_to_pose(self, row: np.ndarray) -> dict[int, float]:
        """One frame's predicted values -> {joint_id: position}, clamped to 0..10."""
        pose: dict[int, float] = {}
        for name, value in zip(self.axis_names, row):
            joint_id = AXIS_TO_JOINT.get(name)
            if joint_id is None:
                continue
            pose[joint_id] = float(min(10.0, max(0.0, value)))
        return pose


class GestureModel:
    """Wraps an OhbotAudioModel loaded from a train.py checkpoint."""

    def __init__(self, checkpoint_path: str | Path, device: str = "cpu") -> None:
        # Repo-root-relative paths (what config.json stores) must resolve the same way
        # whatever directory the engine was launched from.
        ckpt = torch.load(resolve_path(checkpoint_path), map_location=device, weights_only=False)
        args = ckpt.get("args") or ckpt["config"]
        n_axes = int(ckpt["n_axes"])

        self.model = OhbotAudioModel(
            n_mels=args["n_mels"],
            n_axes=n_axes,
            conv_channels=args["conv_channels"],
            gru_hidden=args["gru_hidden"],
        )
        self.model.load_state_dict(ckpt["model_state"])
        self.model.to(device)
        self.model.eval()

        self.device = device
        self.n_mels = int(args["n_mels"])
        self.feature_mean = ckpt["feature_mean"]
        self.feature_std = ckpt["feature_std"]
        self.axis_names = list(AXIS_ORDER[:n_axes])

    @torch.no_grad()
    def predict(
        self,
        audio: np.ndarray,
        sample_rate: int,
        control_hz: float = 20.0,
        intensity: float = 1.0,
    ) -> GesturePrediction:
        """audio: (n_samples,) float32 mono, any sample rate.

        ``intensity`` scales predicted movement around Ohbot's neutral rest
        position (5.0), not the raw 0..10 value -- so e.g. HEADNOD stays
        centered while amplified. 1.0 = model output unchanged, >1 exaggerates,
        <1 dampens. Result is clamped back to 0..10.
        """
        if sample_rate != MODEL_AUDIO_SR:
            audio = resample_channel(audio, sample_rate, MODEL_AUDIO_SR)
            sample_rate = MODEL_AUDIO_SR

        duration_s = len(audio) / float(sample_rate)
        target_frames = max(1, int(round(duration_s * control_hz)))
        hop = int(round(sample_rate / control_hz))

        feats = log_mel_spectrogram(
            audio, sample_rate, n_mels=self.n_mels, hop_length=hop, target_frames=target_frames,
        )
        feats, _, _ = normalize_features(feats, self.feature_mean, self.feature_std)

        x = torch.from_numpy(feats).unsqueeze(0).to(self.device)  # (1, T, n_mels)
        out = self.model(x)  # (1, T, n_axes)
        motion = out.squeeze(0).cpu().numpy()

        if intensity != 1.0:
            motion = joints.REST_POSITION + (motion - joints.REST_POSITION) * intensity
            motion = np.clip(motion, 0.0, 10.0)

        return GesturePrediction(motion=motion, control_hz=control_hz, axis_names=self.axis_names)
