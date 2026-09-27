"""
ohbot_dataset.py

Reads the manifest.csv + clips/*.npz produced by beat2_to_ohbot.py and turns
each clip into (audio_features, motion_targets) pairs for training.

Kept deliberately simple: one clip = one training sequence (no chunking of
long clips), padded to the longest sequence in a batch. Fine for a first
pipeline-verification run; revisit if your clips are very long/GPU memory
is tight.
"""

import csv
import os

import numpy as np
import torch
from torch.utils.data import Dataset

from features import log_mel_spectrogram, normalize_features


def read_manifest(manifest_path):
    rows = []
    with open(manifest_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_clip(npz_path):
    d = np.load(npz_path, allow_pickle=True)
    return {
        "motion": d["ohbot_motion"].astype(np.float32),       # (T, n_axes), 0-10
        "axis_names": [str(x) for x in d["ohbot_axis_names"]],
        "control_hz": float(d["control_hz"]),
        "audio": d["audio"].astype(np.float32),               # (n_samples,)
        "audio_sr": int(d["audio_sr"]),
    }


class OhbotDataset(Dataset):
    """
    feature_stats: optional (mean, std) tuple, computed on the TRAIN split
    and reused for val/test so normalization doesn't leak information.
    Pass feature_stats=None and call `.compute_and_set_feature_stats()`
    once on the training set, then pass the returned stats into the val set.
    """

    def __init__(self, manifest_rows, n_mels=40, feature_stats=None):
        self.rows = manifest_rows
        self.n_mels = n_mels
        self.feature_stats = feature_stats  # (mean, std) or None

    def __len__(self):
        return len(self.rows)

    def _extract(self, clip):
        hop = int(round(clip["audio_sr"] / clip["control_hz"]))
        target_frames = clip["motion"].shape[0]
        feats = log_mel_spectrogram(
            clip["audio"], clip["audio_sr"],
            n_mels=self.n_mels, hop_length=hop, target_frames=target_frames,
        )
        return feats

    def __getitem__(self, idx):
        row = self.rows[idx]
        clip = load_clip(row["out_path"])
        feats = self._extract(clip)  # (T, n_mels)

        mean, std = self.feature_stats if self.feature_stats else (None, None)
        feats, mean, std = normalize_features(feats, mean, std)
        if self.feature_stats is None:
            # not saving per-item stats back -- see compute_and_set_feature_stats
            pass

        return {
            "features": torch.from_numpy(feats),          # (T, n_mels)
            "motion": torch.from_numpy(clip["motion"]),    # (T, n_axes)
            "length": feats.shape[0],
            "clip_id": row["clip_id"],
        }

    def compute_and_set_feature_stats(self, max_clips=200):
        """Run this ONCE on the training split before training. Computes
        global per-mel-channel mean/std over up to `max_clips` clips and
        stores it on this dataset instance (and returns it, so you can pass
        the same stats into your val/test OhbotDataset)."""
        all_feats = []
        n = min(max_clips, len(self.rows))
        for i in range(n):
            clip = load_clip(self.rows[i]["out_path"])
            all_feats.append(self._extract(clip))
        concat = np.concatenate(all_feats, axis=0)
        mean = concat.mean(axis=0, keepdims=True)
        std = concat.std(axis=0, keepdims=True) + 1e-6
        self.feature_stats = (mean, std)
        return mean, std


def collate_fn(batch):
    """Pads variable-length sequences to the max length in the batch.
    Returns features (B,T,n_mels), motion (B,T,n_axes), lengths (B,), and a
    boolean mask (B,T) that's True for real (non-padding) frames -- use this
    to mask the loss so padding doesn't influence gradients."""
    lengths = torch.tensor([b["length"] for b in batch], dtype=torch.long)
    max_len = int(lengths.max())
    n_mels = batch[0]["features"].shape[1]
    n_axes = batch[0]["motion"].shape[1]
    B = len(batch)

    features = torch.zeros(B, max_len, n_mels, dtype=torch.float32)
    motion = torch.zeros(B, max_len, n_axes, dtype=torch.float32)
    mask = torch.zeros(B, max_len, dtype=torch.bool)

    for i, b in enumerate(batch):
        T = b["length"]
        features[i, :T] = b["features"]
        motion[i, :T] = b["motion"]
        mask[i, :T] = True

    clip_ids = [b["clip_id"] for b in batch]
    return {"features": features, "motion": motion, "lengths": lengths,
             "mask": mask, "clip_ids": clip_ids}
