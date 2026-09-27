#!/usr/bin/env python3
"""
train.py

Trains the small audio -> Ohbot-servo model on clips produced by
beat2_to_ohbot.py (expects <data-dir>/manifest.csv and <data-dir>/clips/*.npz).

------------------------------------------------------------------------------
NAMED RUNS & RESUME
------------------------------------------------------------------------------
Every training run has a name (--name, default "default"). The script creates
a folder  runs/<name>/  containing:

    config.json   -- all hyperparameters (frozen on first launch)
    checkpoint.pt -- model + optimizer state + epoch counter (updated each epoch)
    best_model.pt -- best checkpoint by validation loss
    train.log     -- append-only training log

To start a new run:
    python train.py --name test1 --data-dir ./ohbot_data --epochs 100

To stop: Ctrl-C at any time. Progress is saved after every epoch.

To resume the same run later (uses the ORIGINAL settings from config.json):
    python train.py --name test1 --resume

You can have many independent runs side by side:
    python train.py --name test2 --data-dir ./ohbot_data --lr 0.0005 --epochs 50

------------------------------------------------------------------------------
YAW CENTERING LOSS
------------------------------------------------------------------------------
The trained model tends to drift the head yaw (HEADTURN) toward one side by
the end of a clip. To counteract this, an auxiliary loss nudges the yaw axis
back toward neutral (5.0) at the end of each clip. The penalty is NOT applied
uniformly -- it ramps linearly from zero to full strength over the last portion
of the clip, so normal head-turn behaviour during speech is preserved.

Only the yaw axis is affected; pitch (HEADNOD) and roll (HEADTILT) are free
to remain wherever the data takes them.

Arguments:
    --yaw-center-weight  Weight of the centering loss (default 0.1, 0 to disable)
    --yaw-center-ramp    Fraction of clip where the ramp is active (default 0.3,
                         i.e. loss ramps from 0 to full over the last 30%)
    --yaw-axis           Index of the HEADTURN axis (default 1)

Example:
    python train.py --name centered --data-dir ./ohbot_data --yaw-center-weight 0.15 --yaw-center-ramp 0.25

------------------------------------------------------------------------------
RECOMMENDED FIRST RUN: verify the pipeline, not the model
------------------------------------------------------------------------------
    python train.py --name smoke --data-dir ./ohbot_data --overfit-one-batch --epochs 200

Once that works:
    python train.py --name first_real --data-dir ./ohbot_data --epochs 30 --batch-size 4

------------------------------------------------------------------------------
"""

import argparse
import json
import logging
import os
import random
import signal
import sys

import numpy as np
import torch
from torch.utils.data import DataLoader

from ohbot_dataset import OhbotDataset, read_manifest, collate_fn
from model import OhbotAudioModel

log = logging.getLogger("train")

RUNS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs")

_stop_requested = False


def _handle_stop_signal(signum, frame):
    global _stop_requested
    _stop_requested = True
    log.info("[signal] Stop requested -- exiting.")
    sys.exit(0)


def setup_logging(log_path):
    log.setLevel(logging.INFO)
    log.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    log.addHandler(console_handler)

    file_handler = logging.FileHandler(log_path, mode="a")
    file_handler.setFormatter(fmt)
    log.addHandler(file_handler)

    def log_uncaught_exceptions(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = log_uncaught_exceptions
    log.info(f"Logging to console and to {log_path}")


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def masked_mse(pred, target, mask):
    diff2 = (pred - target) ** 2
    mask = mask.unsqueeze(-1).float()
    return (diff2 * mask).sum() / mask.sum().clamp(min=1) / pred.shape[-1]


def baseline_mse(target, mask, rest_value=5.0):
    rest = torch.full_like(target, rest_value)
    return masked_mse(rest, target, mask).item()


def yaw_centering_loss(pred, mask, lengths, yaw_axis=1, ramp_fraction=0.3, neutral=5.0):
    """Penalize yaw (HEADTURN) deviating from neutral at the end of each clip.

    The penalty ramps linearly from 0 to 1 over the last `ramp_fraction` of
    each clip, so it only gradually kicks in toward the end.
    """
    B, T, _ = pred.shape
    device = pred.device

    t_idx = torch.arange(T, device=device).float().unsqueeze(0)  # (1, T)
    clip_lengths = lengths.to(device).float().unsqueeze(1)  # (B, 1)

    ramp_start = clip_lengths * (1.0 - ramp_fraction)  # (B, 1)
    ramp_duration = clip_lengths * ramp_fraction        # (B, 1)

    ramp = ((t_idx - ramp_start) / ramp_duration.clamp(min=1)).clamp(0.0, 1.0)  # (B, T)
    ramp = ramp * mask.float()  # zero out padding

    yaw_pred = pred[:, :, yaw_axis]  # (B, T)
    yaw_diff2 = (yaw_pred - neutral) ** 2  # (B, T)

    weighted = (yaw_diff2 * ramp).sum()
    denom = ramp.sum().clamp(min=1)
    return weighted / denom


def run_epoch(model, loader, optimizer, device, train=True,
              yaw_center_weight=0.0, yaw_center_ramp=0.3, yaw_axis=1):
    model.train(train)
    total_loss, n_batches = 0.0, 0
    for batch in loader:
        features = batch["features"].to(device)
        motion = batch["motion"].to(device)
        mask = batch["mask"].to(device)
        lengths = batch["lengths"]

        with torch.set_grad_enabled(train):
            pred = model(features, lengths=lengths)
            loss = masked_mse(pred, motion, mask)

            if yaw_center_weight > 0:
                yaw_loss = yaw_centering_loss(
                    pred, mask, lengths,
                    yaw_axis=yaw_axis, ramp_fraction=yaw_center_ramp,
                )
                loss = loss + yaw_center_weight * yaw_loss

            if train:
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

        total_loss += loss.item()
        n_batches += 1
    return total_loss / max(n_batches, 1)


def save_checkpoint(run_dir, model, optimizer, epoch, best_val, feature_stats, n_axes, config):
    ckpt = {
        "model_state": model.state_dict(),
        "optimizer_state": optimizer.state_dict(),
        "epoch": epoch,
        "best_val": best_val,
        "feature_mean": feature_stats[0],
        "feature_std": feature_stats[1],
        "n_axes": n_axes,
        "config": config,
    }
    torch.save(ckpt, os.path.join(run_dir, "checkpoint.pt"))


def save_best_model(run_dir, model, feature_stats, n_axes, config):
    torch.save({
        "model_state": model.state_dict(),
        "config": config,
        "feature_mean": feature_stats[0],
        "feature_std": feature_stats[1],
        "n_axes": n_axes,
    }, os.path.join(run_dir, "best_model.pt"))


def load_config(run_dir):
    config_path = os.path.join(run_dir, "config.json")
    with open(config_path, "r") as f:
        return json.load(f)


def save_config(run_dir, config):
    config_path = os.path.join(run_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", default="default",
                   help="Name for this training run. Creates runs/<name>/ folder.")
    p.add_argument("--resume", action="store_true",
                   help="Resume a previously stopped run. Uses the saved config.json, "
                        "ignoring other CLI args (except --name and --device).")
    p.add_argument("--data-dir", default="./ohbot_data", help="Directory containing manifest.csv and clips/")
    p.add_argument("--n-mels", type=int, default=40)
    p.add_argument("--conv-channels", type=int, default=32)
    p.add_argument("--gru-hidden", type=int, default=64)
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--batch-size", type=int, default=4)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--val-frac", type=float, default=0.15)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--limit", type=int, default=None, help="Only use the first N clips (quick tests)")
    p.add_argument("--overfit-one-batch", action="store_true",
                   help="Pipeline smoke test: train on a single batch repeatedly, no val split.")
    p.add_argument("--yaw-center-weight", type=float, default=0.1,
                   help="Weight for the yaw-centering loss that nudges HEADTURN back to neutral "
                        "at the end of each clip (0 to disable, default 0.1)")
    p.add_argument("--yaw-center-ramp", type=float, default=0.3,
                   help="Fraction of the clip over which the yaw-centering loss ramps up "
                        "(e.g. 0.3 = last 30%% of the clip, default 0.3)")
    p.add_argument("--yaw-axis", type=int, default=1,
                   help="Index of the yaw (HEADTURN) axis in the motion tensor (default 1)")
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = p.parse_args()

    run_dir = os.path.join(RUNS_DIR, args.name)
    config_path = os.path.join(run_dir, "config.json")
    checkpoint_path = os.path.join(run_dir, "checkpoint.pt")

    if args.resume:
        if not os.path.isfile(config_path):
            print(f"Error: no existing run '{args.name}' found at {run_dir}", file=sys.stderr)
            sys.exit(1)
        if not os.path.isfile(checkpoint_path):
            print(f"Error: run '{args.name}' has no checkpoint to resume from.", file=sys.stderr)
            sys.exit(1)
        config = load_config(run_dir)
        log.info(f"Resuming run '{args.name}' with saved config.")
    else:
        if os.path.isfile(config_path):
            print(f"Error: run '{args.name}' already exists at {run_dir}.", file=sys.stderr)
            print(f"Use --resume to continue it, or pick a different --name.", file=sys.stderr)
            sys.exit(1)
        if args.data_dir is None:
            print("Error: --data-dir is required when starting a new run.", file=sys.stderr)
            sys.exit(1)
        config = {
            "name": args.name,
            "data_dir": os.path.abspath(args.data_dir),
            "n_mels": args.n_mels,
            "conv_channels": args.conv_channels,
            "gru_hidden": args.gru_hidden,
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "lr": args.lr,
            "val_frac": args.val_frac,
            "seed": args.seed,
            "limit": args.limit,
            "overfit_one_batch": args.overfit_one_batch,
            "yaw_center_weight": args.yaw_center_weight,
            "yaw_center_ramp": args.yaw_center_ramp,
            "yaw_axis": args.yaw_axis,
        }
        os.makedirs(run_dir, exist_ok=True)
        save_config(run_dir, config)

    device = args.device
    log_path = os.path.join(run_dir, "train.log")
    setup_logging(log_path)
    log.info("=" * 70)
    log.info(f"Run '{config['name']}' | device={device} | dir={run_dir}")
    log.info(f"Config: {json.dumps(config, indent=2)}")

    signal.signal(signal.SIGINT, _handle_stop_signal)
    signal.signal(signal.SIGTERM, _handle_stop_signal)

    set_seed(config["seed"])

    manifest_path = os.path.join(config["data_dir"], "manifest.csv")
    rows = read_manifest(manifest_path)
    if config["limit"]:
        rows = rows[: config["limit"]]
    if len(rows) == 0:
        raise RuntimeError(f"No rows found in {manifest_path} -- did convert step run?")

    random.shuffle(rows)

    if config["overfit_one_batch"]:
        rows = rows[: config["batch_size"]]
        train_rows, val_rows = rows, rows
        log.info(f"[overfit-one-batch] using {len(rows)} clip(s) as a single batch.")
    else:
        n_val = max(1, int(round(len(rows) * config["val_frac"]))) if len(rows) > 3 else 0
        val_rows = rows[:n_val]
        train_rows = rows[n_val:]
        if len(train_rows) == 0:
            train_rows, val_rows = rows, []
        log.info(f"[data] {len(train_rows)} train clips, {len(val_rows)} val clips (from {len(rows)} total)")

    train_ds = OhbotDataset(train_rows, n_mels=config["n_mels"])
    log.info("[data] computing feature normalization stats from the training set...")
    mean, std = train_ds.compute_and_set_feature_stats()

    val_ds = OhbotDataset(val_rows, n_mels=config["n_mels"], feature_stats=(mean, std)) if val_rows else None

    train_loader = DataLoader(train_ds, batch_size=config["batch_size"], shuffle=True,
                              collate_fn=collate_fn, drop_last=False)
    val_loader = DataLoader(val_ds, batch_size=config["batch_size"], shuffle=False,
                            collate_fn=collate_fn) if val_ds else None

    n_axes = train_ds[0]["motion"].shape[1]
    model = OhbotAudioModel(n_mels=config["n_mels"], n_axes=n_axes,
                            conv_channels=config["conv_channels"], gru_hidden=config["gru_hidden"])
    model.to(device)
    log.info(f"[model] {model.num_params():,} trainable parameters, {n_axes} output axes")

    optimizer = torch.optim.Adam(model.parameters(), lr=config["lr"])

    start_epoch = 1
    best_val = float("inf")

    if args.resume and os.path.isfile(checkpoint_path):
        ckpt = torch.load(checkpoint_path, map_location=device, weights_only=False)
        model.load_state_dict(ckpt["model_state"])
        optimizer.load_state_dict(ckpt["optimizer_state"])
        start_epoch = ckpt["epoch"] + 1
        best_val = ckpt.get("best_val", float("inf"))
        log.info(f"[resume] Loaded checkpoint from epoch {ckpt['epoch']}, best_val={best_val:.4f}")
        if start_epoch > config["epochs"]:
            log.info(f"[resume] Already completed {config['epochs']} epochs. Nothing to do.")
            return

    example_batch = next(iter(train_loader))
    b_mse = baseline_mse(example_batch["motion"], example_batch["mask"])
    log.info(f"[baseline] always-predict-rest MSE: {b_mse:.4f}")

    feature_stats = (mean, std)

    yaw_kwargs = {
        "yaw_center_weight": config.get("yaw_center_weight", 0.0),
        "yaw_center_ramp": config.get("yaw_center_ramp", 0.3),
        "yaw_axis": config.get("yaw_axis", 1),
    }

    for epoch in range(start_epoch, config["epochs"] + 1):
        train_loss = run_epoch(model, train_loader, optimizer, device, train=True, **yaw_kwargs)

        if val_loader is not None:
            val_loss = run_epoch(model, val_loader, optimizer, device, train=False, **yaw_kwargs)
            log.info(f"epoch {epoch:4d}/{config['epochs']}  train_loss={train_loss:.4f}  val_loss={val_loss:.4f}")
            if val_loss < best_val:
                best_val = val_loss
                save_best_model(run_dir, model, feature_stats, n_axes, config)
        else:
            log.info(f"epoch {epoch:4d}/{config['epochs']}  train_loss={train_loss:.4f}")

        save_checkpoint(run_dir, model, optimizer, epoch, best_val, feature_stats, n_axes, config)

    if val_loader is None:
        save_best_model(run_dir, model, feature_stats, n_axes, config)
    log.info(f"[done] Training complete. Best val loss: {best_val:.4f}")
    log.info(f"[saved] Run '{config['name']}' checkpoints in {run_dir}")


if __name__ == "__main__":
    main()
