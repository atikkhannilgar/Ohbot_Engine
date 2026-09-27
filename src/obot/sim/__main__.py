"""Standalone digital OhBot: test speech, lip-sync, actions and tuning without hardware.

Usage (from the repo root):

    python -m obot.sim                      # window + interactive prompt
    python -m obot.sim --text "Hi [Nod] there!"   # speak once, then prompt
    python -m obot.sim --no-tuning          # hide the mouth tuning sliders

Type sentences (inline tags like [Nod], (Happy), !Delay500 all work) and watch
the face speak them with the configured TTS voice. While the bot is talking,
press Enter to interrupt it at the next word boundary. Tune the mouth with the
sliders and hit "Save to config.json" to persist what sounds right.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import threading

from ..core.interrupt import InterruptController
from ..core.orchestrator import RobotPipeline
from ..llm.client import ScriptedLLMClient
from ..robot.behaviors import BehaviorManager, BehaviorSettings
from ..robot.controller import SimulatedObotController
from ..speech.config import MotionSettings, SpeechSettings
from .face import FaceWindow

_BANNER = """
Digital OhBot ready.
  - Type a sentence and press Enter to make it speak.
    Tags work: [Nod] [Blink] [Wink] [LookLeft] [LookRight] [ShakeHead] (Happy) (Sad) !Delay500
  - Press Enter (empty line) WHILE it talks to interrupt at the next word boundary.
  - Type q to quit. Closing the window quits too.
"""


def _load_settings():
    """Config if present; otherwise defaults (local TTS, no API key needed)."""
    try:
        from ..config import load_config

        cfg = load_config()
        return cfg, cfg.speech, cfg.motion, cfg.behaviors, cfg.gemini_api_key
    except FileNotFoundError:
        print("[sim] no config.json found - using defaults with the local voice.")
        return None, SpeechSettings(), MotionSettings(), BehaviorSettings(), ""


async def _run(text: str | None, tuning: bool) -> None:
    cfg, speech, motion, behaviors, api_key = _load_settings()

    def on_save() -> None:
        if cfg is not None:
            cfg.save()
            print("\n[sim] mouth settings saved to config.json")

    face = FaceWindow(
        mouth_settings=speech.mouth,
        on_save=on_save if cfg is not None else None,
        tuning=tuning,
    )
    controller = SimulatedObotController(
        face, speech_settings=speech, motion_settings=motion, gemini_api_key=api_key
    )
    manager = BehaviorManager(controller, behaviors)
    manager.start()

    loop = asyncio.get_running_loop()
    lines: asyncio.Queue[str | None] = asyncio.Queue()

    def reader() -> None:
        # Plain blocking stdin reader; daemon thread so it never blocks shutdown.
        while True:
            try:
                line = input()
            except (EOFError, KeyboardInterrupt):
                loop.call_soon_threadsafe(lines.put_nowait, None)
                return
            loop.call_soon_threadsafe(lines.put_nowait, line)

    threading.Thread(target=reader, daemon=True, name="obot-sim-stdin").start()
    print(_BANNER)

    async def next_line(timeout: float) -> str | None | object:
        # Returns the line, None (EOF), or _PENDING when nothing arrived in time.
        try:
            return await asyncio.wait_for(lines.get(), timeout)
        except asyncio.TimeoutError:
            return _PENDING

    _PENDING = object()
    queued_text: str | None = text
    try:
        while face.is_open:
            if queued_text is None:
                got = await next_line(0.2)
                if got is _PENDING:
                    continue
                if got is None:
                    break
                queued_text = str(got).strip()
                if not queued_text:
                    queued_text = None
                    continue
                if queued_text.lower() in ("q", "quit", "exit"):
                    break

            face.set_status(queued_text)
            pipeline = RobotPipeline(
                llm_client=ScriptedLLMClient(queued_text, chunk_size=200),
                controller=controller,
            )
            interrupt = InterruptController(loop)
            manager.set_speaking(True)
            run_task = asyncio.create_task(pipeline.run(queued_text, interrupt))
            queued_text = None

            while not run_task.done():
                got = await next_line(0.1)
                if got is _PENDING:
                    if not face.is_open:
                        interrupt.trigger("keyboard")
                    continue
                if got is None or str(got).strip().lower() in ("q", "quit", "exit"):
                    interrupt.trigger("keyboard")
                    with contextlib.suppress(Exception):
                        await run_task
                    manager.set_speaking(False)
                    return
                # Any line while speaking = interrupt; non-empty also queues as next input.
                interrupt.trigger("keyboard")
                nxt = str(got).strip()
                if nxt:
                    queued_text = nxt

            with contextlib.suppress(Exception):
                await run_task
            manager.set_speaking(False)
            face.set_status("")
    finally:
        manager.set_speaking(False)
        await manager.stop()
        controller.close()
        face.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Digital OhBot simulator / speech test bench.")
    parser.add_argument("--text", help="Speak this once at startup (tags allowed).")
    parser.add_argument("--no-tuning", action="store_true", help="Hide the mouth tuning sliders.")
    args = parser.parse_args()
    try:
        asyncio.run(_run(args.text, tuning=not args.no_tuning))
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
