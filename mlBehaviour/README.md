> Review package: training and preview code is included. BEAT2 data, converted recordings, sample audio and trained checkpoints are not bundled. Obtain the data separately and train or supply a checkpoint before using these examples.




# Training pipeline

## Overview

This Pipeline is designed to train a small ml model to predict Ohbot servo positions from audio features. We use a converted subset of the BEAT2 dataset, which contains motion and audio data. The `beat2_to_ohbot.py` script is used to convert the BEAT2 dataset into a format suitable for the OhBot platform. For more information about the BEAT2 dataset, please refer to the [BEAT2 dataset documentation](dataset_setup.md).

This directory contains the following key files:
- `features.py` -- log-mel spectrogram extraction, frame-aligned to your control_hz (pure numpy, tested)
- `ohbot_dataset.py` -- PyTorch `Dataset` reading `manifest.csv`/`clips/*.npz` from `beat2_to_ohbot.py`
- `model.py` -- small Conv1d + GRU model, outputs 8 servo values in [0, 10] (7 if converted with `--exclude-head-tilt`)
- `train.py` -- training loop with **named runs**, **stop/resume**, and a pipeline smoke test

## Install

The ML training pipeline requires Python 3.10+ and the following dependencies:

```bash
pip install torch numpy scipy
```

If you have already installed the dependencies via the main application, you can skip this step. Otherwise, you can install the required dependencies by running:

```bash
pip install -r requirements/ml.txt
```


## Training runs

Every training run has a **name** (`--name`, default `"default"`). The script
creates a folder `runs/<name>/` containing:

| File | Purpose |
|------|---------|
| `config.json` | All hyperparameters. Frozen when the run is first created and used when resuming stopped training runs |
| `checkpoint.pt` | Full training state (model + optimizer + epoch), saved every epoch |
| `best_model.pt` | Best model checkpoint by validation loss |
| `train.log` | Append-only training log |

### Starting a new run

```bash
python train.py --name my_experiment --data-dir ./ohbot_data --epochs 100 --lr 0.001
```

### Stopping

Press **Ctrl-C** at any time. The current epoch is cut short, the checkpoint is
saved, and the script prints the command to resume.

### Resuming a run

```bash
python train.py --name my_experiment --resume
```

This loads `config.json` from the run folder and picks up training from the
last completed epoch. All hyperparameters come from the saved config. CLI
args other than `--name` and `--device` are ignored on resume.

### Running multiple experiments side by side

```bash
python train.py --name fast_lr   --data-dir ./ohbot_data --lr 0.003 --epochs 50
python train.py --name slow_lr   --data-dir ./ohbot_data --lr 0.0003 --epochs 200
python train.py --name big_model --data-dir ./ohbot_data --gru-hidden 128 --conv-channels 64
```

Each gets its own folder under `runs/` with independent configs and checkpoints.
You can stop any of them and resume later without affecting the others.

### All training flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--name` | string | `"default"` | Name for this training run. Creates `runs/<name>/` folder |
| `--resume` | flag | off | Resume a previously stopped run. Uses the saved `config.json`, ignoring other CLI args (except `--name` and `--device`) |
| `--data-dir` | path | `"./ohbot_data"` | Directory containing the converted BEAT2 dataset (`manifest.csv` and `clips/`) |
| `--n-mels` | int | `40` | Number of mel-frequency bins for the log-mel spectrogram input features |
| `--conv-channels` | int | `32` | Number of output channels in the Conv1d layers |
| `--gru-hidden` | int | `64` | Hidden size of the GRU recurrent layer |
| `--epochs` | int | `30` | Total number of training epochs |
| `--batch-size` | int | `4` | Number of clips per training batch |
| `--lr` | float | `1e-3` | Learning rate for the optimizer |
| `--val-frac` | float | `0.15` | Fraction of clips held out for validation |
| `--seed` | int | `0` | Random seed for reproducibility (data splits, weight init) |
| `--limit` | int | None | Only use the first N clips (useful for quick pipeline tests) |
| `--overfit-one-batch` | flag | off | Pipeline smoke test: train on a single batch repeatedly with no val split |
| `--yaw-center-weight` | float | `0.1` | Weight of the yaw-centering loss (0 to disable) |
| `--yaw-center-ramp` | float | `0.3` | Fraction of each clip over which the centering loss ramps up (e.g. 0.3 = last 30%) |
| `--yaw-axis` | int | `1` | Index of the HEADTURN (yaw) axis in the motion tensor |
| `--device` | string | `"cuda"` if available, else `"cpu"` | PyTorch device to train on (e.g. `cpu`, `cuda`, `cuda:1`) |

### Yaw centering loss

The model tends to drift the head yaw (HEADTURN) toward one side by the end of a clip. An auxiliary loss penalizes the yaw axis for deviating from neutral (5.0) at the end of each clip. The penalty is not applied uniformly -- it ramps linearly from zero to full strength over the final portion of the clip, controlled by `--yaw-center-ramp`. This preserves natural head-turning during speech while gently pulling yaw back to center as the clip ends.

Only the yaw axis is affected; pitch (HEADNOD) and roll (HEADTILT) remain free to follow the data.

```bash
# Default (enabled at weight 0.1, ramp over last 30% of clip)
python train.py --name default_centering --data-dir ./ohbot_data

# Stronger centering, shorter ramp (last 20%)
python train.py --name strong_center --data-dir ./ohbot_data --yaw-center-weight 0.2 --yaw-center-ramp 0.2

# Disable centering entirely
python train.py --name no_center --data-dir ./ohbot_data --yaw-center-weight 0
```
