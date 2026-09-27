"""
features.py

Turns a raw audio waveform into a log-mel spectrogram whose frame rate is
locked to the robot's control rate (control_hz), so every mel frame lines
up 1:1 with one row of ohbot_motion. Pure numpy -- no librosa/torchaudio
dependency, so it works in minimal environments.
"""

import numpy as np


def hz_to_mel(hz):
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def mel_to_hz(mel):
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def mel_filterbank(n_mels, n_fft, sr, fmin=0.0, fmax=None):
    """Standard triangular mel filterbank, shape (n_mels, n_fft//2 + 1)."""
    fmax = fmax or sr / 2.0
    mel_lo, mel_hi = hz_to_mel(fmin), hz_to_mel(fmax)
    mel_points = np.linspace(mel_lo, mel_hi, n_mels + 2)
    hz_points = mel_to_hz(mel_points)
    bin_points = np.floor((n_fft + 1) * hz_points / sr).astype(int)
    bin_points = np.clip(bin_points, 0, n_fft // 2)

    fb = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
    for m in range(1, n_mels + 1):
        left, center, right = bin_points[m - 1], bin_points[m], bin_points[m + 1]
        if center == left:
            center += 1
        if right == center:
            right += 1
        for k in range(left, center):
            fb[m - 1, k] = (k - left) / max(center - left, 1)
        for k in range(center, right):
            fb[m - 1, k] = (right - k) / max(right - center, 1)
    return fb


def log_mel_spectrogram(audio, sr, n_mels=40, hop_length=None, n_fft=None,
                         target_frames=None):
    """
    audio: (n_samples,) float32, mono
    hop_length: samples between successive frames. If you want the mel frame
        rate to exactly match the robot control rate, pass
        hop_length = round(sr / control_hz).
    n_fft: analysis window size. Defaults to 2x hop_length (min 256), which
        gives every frame some overlap/context.
    target_frames: if given, the output is padded/truncated to exactly this
        many frames (use this to force exact alignment with ohbot_motion,
        since STFT frame counts and simple duration*control_hz rounding can
        differ by a frame).

    Returns: (n_frames, n_mels) float32 log-mel features.
    """
    if hop_length is None:
        hop_length = int(round(sr * 0.01))  # 10ms default
    if n_fft is None:
        n_fft = max(256, 2 * hop_length)

    audio = np.asarray(audio, dtype=np.float32)
    # pad so the last frame isn't cut off
    pad = n_fft // 2
    padded = np.pad(audio, (pad, pad), mode="reflect") if len(audio) > pad else np.pad(audio, (pad, pad))

    n_frames = 1 + (len(padded) - n_fft) // hop_length
    n_frames = max(n_frames, 1)

    window = np.hanning(n_fft).astype(np.float32)
    frames = np.zeros((n_frames, n_fft), dtype=np.float32)
    for i in range(n_frames):
        start = i * hop_length
        frames[i] = padded[start:start + n_fft] * window

    spec = np.fft.rfft(frames, n=n_fft, axis=1)
    power = (np.abs(spec) ** 2).astype(np.float32)

    fb = mel_filterbank(n_mels, n_fft, sr)
    mel = power @ fb.T  # (n_frames, n_mels)
    log_mel = np.log(np.clip(mel, 1e-10, None)).astype(np.float32)

    if target_frames is not None:
        if log_mel.shape[0] < target_frames:
            pad_rows = target_frames - log_mel.shape[0]
            log_mel = np.pad(log_mel, ((0, pad_rows), (0, 0)), mode="edge")
        log_mel = log_mel[:target_frames]

    return log_mel


def normalize_features(feats, mean=None, std=None, eps=1e-6):
    """Per-channel standardization. If mean/std are given (e.g. computed once
    over the training set), applies them; otherwise computes and returns them
    too, so callers can reuse the same stats for val/test."""
    if mean is None:
        mean = feats.mean(axis=0, keepdims=True)
    if std is None:
        std = feats.std(axis=0, keepdims=True) + eps
    return (feats - mean) / std, mean, std
