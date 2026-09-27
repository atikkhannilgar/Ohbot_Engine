"""Standalone runner: drives the Ohbot straight from the BEAT2-trained
gesture model, no LLM/chat pipeline involved. Point it at a checkpoint and a
wav file and watch the predicted pose play out.

    python -m obot.ml mlBehaviour/training_run/best_model.pt clip.wav --sim
    python -m obot.ml mlBehaviour/training_run/best_model.pt clip.wav --console
    python -m obot.ml mlBehaviour/training_run/best_model.pt clip.wav   # real hardware
"""

from __future__ import annotations

import argparse
import asyncio

from ..__main__ import _try_load_config, make_controller
from .driver import AIGestureDriver
from .inference import GestureModel


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Drive the Ohbot from a trained BEAT2 gesture model.")
    parser.add_argument("checkpoint", help="Path to a train.py checkpoint (e.g. best_model.pt).")
    parser.add_argument("wav", help="Audio file to play and gesture along to.")
    parser.add_argument("--control-hz", type=float, default=20.0, help="Must match training's --control-hz.")
    parser.add_argument("--device", default="cpu", help="torch device for inference (cpu/cuda).")
    parser.add_argument(
        "--intensity", type=float, default=1.0,
        help="Scale predicted movement around rest position: >1 exaggerates, <1 dampens.",
    )
    parser.add_argument("--console", action="store_true", help="Force the hardware-free console controller.")
    parser.add_argument("--sim", action="store_true", help="Use the digital Ohbot simulator window.")
    return parser


async def _run(args: argparse.Namespace) -> None:
    cfg = _try_load_config()
    controller = make_controller(force_console=args.console, sim=args.sim, cfg=cfg)
    model = GestureModel(args.checkpoint, device=args.device)
    driver = AIGestureDriver(controller, model)
    try:
        print(f"[ai] driving pose from {args.wav} via {args.checkpoint}")
        await driver.play_wav(args.wav, control_hz=args.control_hz, intensity=args.intensity)
    finally:
        controller.close()


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
