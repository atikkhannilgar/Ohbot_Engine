"""Replays a converted BEAT2->Ohbot training clip (beat2_to_ohbot.py's output)
through a running ``python -m obot --serve`` control server, so the dotnet
GUI's visualizer shows exactly what the conversion script extracted -- ground
truth training data, not a model prediction (see ml/driver.py for that). This
is the fastest way to sanity-check that beat2_to_ohbot.py is pulling sensible
per-axis motion out of a BEAT2 clip: watch the head/eyes/lips move in the GUI
and compare against what the speaker was actually doing.

Usage:

    python -m obot --serve                       # in one terminal
    # open the GUI, connect, and press Start on the Dashboard (any backend)
    python -m obot.ml.replay_dataset --list
    python -m obot.ml.replay_dataset --clip 10_kieks_0_103_103
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import itertools
import json
from pathlib import Path

import numpy as np
import websockets

# registry.py holds the axis -> joint mapping (and the default dataset location)
# without importing torch, so this tool stays usable for looking at recorded data
# on a checkout that never installed the ML extras.
from .registry import AXIS_TO_JOINT, DEFAULT_MANIFEST


def read_manifest(manifest_path: Path) -> list[dict]:
    with open(manifest_path, newline="") as f:
        return list(csv.DictReader(f))


def load_clip(npz_path: Path) -> dict:
    d = np.load(npz_path, allow_pickle=True)
    return {
        "motion": d["ohbot_motion"].astype(np.float32),  # (T, n_axes), 0..10
        "axis_names": [str(x) for x in d["ohbot_axis_names"]],
        "control_hz": float(d["control_hz"]),
        "audio": d["audio"].astype(np.float32) if "audio" in d.files else None,
        "audio_sr": int(d["audio_sr"]) if "audio_sr" in d.files else None,
    }


def _to_int16(samples: np.ndarray) -> np.ndarray:
    return np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)


class EngineLink:
    """Minimal client for the control server's call/result protocol (see
    server/server.py's module docstring) -- just enough to drive joints, no
    GUI framework involved."""

    def __init__(self, ws) -> None:
        self._ws = ws
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._reader = asyncio.ensure_future(self._read_loop())

    async def _read_loop(self) -> None:
        async for raw in self._ws:
            msg = json.loads(raw)
            if msg.get("type") != "result":
                continue
            fut = self._pending.pop(msg.get("id"), None)
            if fut is None or fut.done():
                continue
            if msg.get("ok"):
                fut.set_result(msg.get("data"))
            else:
                fut.set_exception(RuntimeError(msg.get("error", "unknown error")))

    async def call(self, method: str, **params) -> object:
        req_id = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        await self._ws.send(json.dumps(
            {"type": "call", "id": req_id, "method": method, "params": params}
        ))
        return await fut

    async def close(self) -> None:
        self._reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._reader


async def _ensure_session(link: EngineLink, controller: str) -> None:
    try:
        await link.call("session_start", backend="scripted", controller=controller)
    except RuntimeError as exc:
        if "already running" not in str(exc):
            raise
        print(f"[replay] a session is already running on the server; reusing it ({exc}).")


async def replay(clip: dict, link: EngineLink, speed: float, play_audio: bool) -> None:
    motion = clip["motion"]
    axis_names = clip["axis_names"]
    control_hz = clip["control_hz"] * speed
    joint_ids = [AXIS_TO_JOINT.get(name) for name in axis_names]
    unmapped = sorted({n for n, j in zip(axis_names, joint_ids) if j is None})
    if unmapped:
        print(f"[replay] warning: no joint mapping for axes {unmapped}; skipping them.")

    player = None
    if play_audio and clip["audio"] is not None:
        from ..speech.player import AudioPlayer

        player = AudioPlayer()
        player.play(_to_int16(clip["audio"]), clip["audio_sr"])

    n_frames = motion.shape[0]
    tick = 1.0 / control_hz
    print(f"[replay] {n_frames} frames @ {control_hz:.1f}Hz ({n_frames / control_hz:.1f}s)")
    try:
        for i in range(n_frames):
            for joint_id, value in zip(joint_ids, motion[i]):
                if joint_id is None:
                    continue
                await link.call("set_joint", joint=joint_id, position=float(value))
            await asyncio.sleep(tick)
    finally:
        await link.call("release_all_joints")
        if player is not None:
            player.abort()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                    help="manifest.csv produced by beat2_to_ohbot.py convert")
    p.add_argument("--clip", help="clip_id from the manifest to replay")
    p.add_argument("--list", action="store_true", help="list available clip_ids and exit")
    p.add_argument("--host", default="127.0.0.1", help="control server host (--serve's --host)")
    p.add_argument("--port", type=int, default=8765, help="control server port (--serve's --port)")
    p.add_argument("--controller", default="virtual",
                    choices=["virtual", "sim", "console", "hardware"],
                    help="controller kind to start a session with, if none is running yet")
    p.add_argument("--speed", type=float, default=1.0, help="playback speed multiplier")
    p.add_argument("--no-audio", action="store_true", help="don't play the clip's audio locally")
    return p


async def _run(args: argparse.Namespace) -> None:
    rows = read_manifest(args.manifest)

    if args.list:
        for row in rows:
            print(f"{row['clip_id']:35s} {row['n_frames']:>6s} frames  {row['duration_s']:>7s}s")
        return

    if not args.clip:
        raise SystemExit("pass --clip <clip_id> (see --list) or --list to browse available clips.")
    if not any(row["clip_id"] == args.clip for row in rows):
        raise SystemExit(f"clip '{args.clip}' not in {args.manifest}. Use --list to see available clips.")

    clip_path = args.manifest.parent / "clips" / f"{args.clip}.npz"
    if not clip_path.exists():
        raise SystemExit(f"clip file not found: {clip_path}")
    clip = load_clip(clip_path)

    print(f"[replay] connecting to ws://{args.host}:{args.port} ...")
    try:
        async with websockets.connect(f"ws://{args.host}:{args.port}") as ws:
            link = EngineLink(ws)
            await link.call("ping")
            await _ensure_session(link, args.controller)
            await replay(clip, link, speed=args.speed, play_audio=not args.no_audio)
            await link.close()
    except OSError as exc:
        raise SystemExit(
            f"can't reach the control server at {args.host}:{args.port} ({exc}).\n"
            f"Start it first with: python -m obot --serve"
        ) from exc


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
