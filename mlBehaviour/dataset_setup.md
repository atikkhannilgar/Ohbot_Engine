# Dataset setup

## Overview

The used dataset is a subset of the BEAT2 dataset, which contains motion and audio data. The `beat2_to_ohbot.py` script is used to convert the BEAT2 dataset into a format suitable for the OhBot platform.

## BEAT2 dataset

BEAT2 (BEAT-SMPLX-FLAME) is a mesh-level, holistic co-speech motion dataset introduced alongside the EMAGE paper (Liu et al., CVPR 2024). It re-releases the motion capture data from the original BEAT dataset in a unified, mesh-based format: **SMPL-X** for the body/hands and **FLAME** for the face.
Each recording pairs synchronized **speech audio** with **full-body 3D motion** (body pose, hand pose, facial expression, and global translation) plus **text/phoneme alignment** and **semantic/emotion annotations** carried over from BEAT.

### Scale and composition

| Property | Value |
|---|---|
| Total motion data | ~60 hours |
| Speakers | 25 subjects (12 female, 13 male) in the standard subset (up to 30 in the full corpus) |
| Sequences | ~1,762 sequences, ~65.7 seconds average length |
| Subsets | **BEAT2-Standard** (~27h) and **BEAT2-Additional** (~33h) |
| Frame rate | 30 fps motion |
| Audio | 16 kHz mono WAV |
| Languages | English, Chinese, Japanese, Spanish |
| Split | Per-sequence train/val/test provided in `train_test_split.csv` |
| License | Apache 2.0 |

### Motion representation

Each frame of body motion is stored as pose parameters for a shared, rigged human template rather than raw joint positions or a per-actor skeleton:

- **SMPL-X body model** captures body shape (betas), body pose, hand pose (fingers), and root translation as axis-angle rotations per joint. This is what lets the same parameter set drive any SMPL-X-compatible avatar without retargeting.
- **FLAME head model** captures facial expression and jaw pose as a low-dimensional expression/blendshape vector, refined from the original ARKit blendshapes via an optimization step.
- Refinements over a naive MoSh++ fit: corrected neck/head proportions, improved neck flexion, and higher-fidelity finger articulation.

Because SMPL-X decouples shape from pose, sequences from different speakers (different body proportions) can be trained on jointly without per-subject retargeting.

### Sources
- dataset: [H-Liu1997/BEAT2](https://huggingface.co/datasets/H-Liu1997/BEAT2)

## BEAT2  conversion

Due to the representation differences between BEAT2 and the Ohbot platform, a conversion step is necessary. The `beat2_to_ohbot.py` script handles this conversion, extracting relevant motion channels and aligning them with the audio data.

Before running the conversion script, ensure you have the BEAT2 dataset downloaded and placed in the appropriate directory and that you have the necessary dependencies installed as well as created the output directory for the converted data.

### 1. Calibrate once on your dataset (percentile-based min/max per axis)
```sh
python beat2_to_ohbot.py calibrate --beat2-root ./BEAT2 --out-dir ./ohbot_data
```


### 2. Convert every matched (motion, audio) pair
```sh
python beat2_to_ohbot.py convert --beat2-root ./BEAT2 --out-dir ./ohbot_data --control-hz 20
```