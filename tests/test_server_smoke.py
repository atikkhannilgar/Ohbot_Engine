"""End-to-end smoke test for the ``python -m obot --serve`` control server.

Launches the server as a child process (no robot required), then drives the full
protocol over a WebSocket: read config, list mics/voices/models, start a
scripted-backend session, send a typed turn, observe ``transcript``/``state``/
``speech``/``joints`` events, interrupt mid-speech, and stop.

Run it directly (spawns its own server):

    OhBots/Scripts/python.exe tests/test_server_smoke.py                 # controller=virtual
    OhBots/Scripts/python.exe tests/test_server_smoke.py --controller console
    OhBots/Scripts/python.exe tests/test_server_smoke.py --controller sim  # opens the face window

Or point it at an already-running server:  ... --attach 8765

Exit code 0 = all checks passed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import socket
import subprocess
import sys
from pathlib import Path

import websockets

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Client:
    """Minimal RPC client: one reader task demultiplexes results (by id) from events."""

    def __init__(self, ws) -> None:
        self._ws = ws
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self.events: asyncio.Queue = asyncio.Queue()
        self.by_topic: dict[str, list] = {}
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        import json
        with contextlib.suppress(websockets.ConnectionClosed, asyncio.CancelledError):
            async for raw in self._ws:
                msg = json.loads(raw)
                if msg.get("type") == "result":
                    fut = self._pending.pop(msg.get("id"), None)
                    if fut and not fut.done():
                        fut.set_result(msg)
                elif msg.get("type") == "event":
                    self.by_topic.setdefault(msg["topic"], []).append(msg.get("data"))
                    await self.events.put(msg)

    async def call(self, method: str, **params):
        import json
        self._next_id += 1
        req_id = self._next_id
        fut = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        await self._ws.send(json.dumps({"type": "call", "id": req_id,
                                        "method": method, "params": params}))
        reply = await asyncio.wait_for(fut, timeout=30)
        if not reply.get("ok"):
            raise RuntimeError(f"{method} failed: {reply.get('error')}")
        return reply.get("data")

    async def wait_topic(self, topic: str, timeout: float = 10.0) -> None:
        """Block until at least one event on ``topic`` has been seen."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not self.by_topic.get(topic):
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise AssertionError(f"timed out waiting for a '{topic}' event")
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.events.get(), timeout=remaining)

    async def close(self) -> None:
        self._reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._reader
        await self._ws.close()


async def _wait_port(port: int, timeout: float = 30.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        try:
            ws = await websockets.connect(f"ws://127.0.0.1:{port}")
            await ws.close()
            return
        except OSError:
            await asyncio.sleep(0.25)
    raise TimeoutError(f"server did not open port {port} within {timeout}s")


async def run_checks(port: int, controller: str) -> None:
    ws = await websockets.connect(f"ws://127.0.0.1:{port}", max_size=4 * 1024 * 1024)
    client = Client(ws)
    try:
        assert (await client.call("ping"))["pong"] is True

        cfg = await client.call("get_config")
        assert "speech" in cfg and "motion" in cfg, "get_config returned an unexpected shape"
        print(f"  [ok] get_config ({len(cfg)} top-level keys)")

        mics = (await client.call("list_mics"))["mics"]
        print(f"  [ok] list_mics -> {len(mics)} device(s)")

        voices = await client.call("list_tts_voices")
        assert set(voices) >= {"gemini", "piper", "local"}
        print(f"  [ok] list_tts_voices (gemini={len(voices['gemini'])}, "
              f"piper={len(voices['piper'])}, local={len(voices['local'])})")

        # Models need a key/tunnel; just confirm the RPC round-trips (ok or a clean error).
        with contextlib.suppress(RuntimeError):
            g = await client.call("list_gemini_models")
            print(f"  [ok] list_gemini_models -> {len(g['models'])}")

        # ML control: the library/status calls must work whether or not torch is
        # installed on this host -- the GUI's ML Control page opens before anything else.
        library = await client.call("list_ml_models")
        assert "models" in library and "scan_dirs" in library
        print(f"  [ok] list_ml_models -> {len(library['models'])} checkpoint(s) "
              f"in {', '.join(library['scan_dirs'])}")

        ml = await client.call("ml_status")
        assert "torch_available" in ml and "enabled" in ml
        assert ml["session"] is False, "ml_status reported a session before one started"
        print(f"  [ok] ml_status (torch={ml['torch_available']}, gesture_enabled={ml['enabled']})")

        # The dependency report drives the GUI's install card: every requirement is listed
        # with its own verdict, and the engine names the interpreter to install into.
        req = ml["requirements"]
        assert req["python"], "requirements report must name the engine's own interpreter"
        assert req["requirements_exists"] is True, f"{req['requirements_file']} is missing"
        names = {item["name"] for item in req["items"]}
        assert {"torch", "numpy", "scipy", "soundfile"} <= names, names
        assert req["ready"] == (not req["missing"])
        assert set(req["installable"]) <= set(req["missing"])
        print(f"  [ok] ml_status requirements (ready={req['ready']}, "
              f"missing={req['missing'] or 'none'}, python={req['python_version']})")

        clips = await client.call("list_ml_clips")
        assert "clips" in clips and "manifest" in clips
        print(f"  [ok] list_ml_clips -> {len(clips['clips'])} clip(s) from {clips['manifest']}")

        # Reading a checkpoint needs torch; without it the RPC must fail cleanly rather
        # than taking the server down, which is what suppressing RuntimeError checks here.
        if library["models"]:
            first = library["models"][0]["path"]
            with contextlib.suppress(RuntimeError):
                info = await client.call("inspect_ml_model", path=first)
                assert info["n_axes"] > 0 and info["parameters"] > 0
                print(f"  [ok] inspect_ml_model {first} -> {info['n_axes']} axes, "
                      f"{info['parameters']:,} params")

        state = await client.call("session_start", backend="scripted",
                                  model="", controller=controller)
        assert state["session"] is True and state["controller"] == controller
        print(f"  [ok] session_start (backend=scripted, controller={controller})")

        if controller in ("virtual", "sim", "hardware"):
            await client.wait_topic("joints", timeout=10.0)
            print(f"  [ok] joints events streaming ({len(client.by_topic['joints'])} so far)")

            # Manual control: hold HeadNod fully forward, confirm the joints stream
            # reflects the held position, then release it back to ambient control.
            await client.call("set_joint", joint="HeadNod", position=10.0)
            held = await _wait_joint_value(client, "HeadNod", 10.0, tolerance=0.2, timeout=5.0)
            assert held, "HeadNod did not reach the manually-held position"
            print("  [ok] set_joint holds an absolute position")
            await client.call("release_joint", joint="HeadNod")
            await client.call("release_all_joints")
            print("  [ok] release_joint / release_all_joints accepted")

            # Emotions: applying "Sad" persistently shifts the resting pose away from
            # Neutral's own baseline (unlike a one-shot offset, it must not decay), and
            # re-selecting "Neutral" returns to exactly that baseline. Compared against
            # Neutral's own live value rather than a fixed number, since the exact
            # per-emotion deltas (and Neutral's rest-position override itself) are
            # hand-tuned and may change -- see robot/emotions.py.
            names = (await client.call("list_emotions"))["emotions"]
            assert "Sad" in names and "Neutral" in names

            await client.call("set_emotion", emotion="Neutral")
            await asyncio.sleep(1.0)
            neutral_top_lip = client.by_topic["joints"][-1]["TopLip"]

            await client.call("set_emotion", emotion="Sad")
            sad_top_lip = await _wait_joint_predicate(
                client, "TopLip", lambda v: abs(v - neutral_top_lip) > 0.3, timeout=5.0
            )
            assert sad_top_lip is not None, "TopLip did not move away from Neutral for Sad"
            await asyncio.sleep(0.5)
            assert abs(client.by_topic["joints"][-1]["TopLip"] - sad_top_lip) < 0.3, \
                "Sad pose decayed instead of persisting"

            state_mid = await client.call("get_state")
            assert state_mid["emotion"] == "Sad"

            await client.call("set_emotion", emotion="Neutral")
            released = await _wait_joint_value(client, "TopLip", neutral_top_lip, tolerance=0.3, timeout=5.0)
            assert released, "TopLip did not return to the Neutral baseline"
            print("  [ok] set_emotion / list_emotions apply and clear a persistent default pose")

            # Loading the gesture model into the live session: with torch absent (or the
            # feature off) this reports "not loaded" instead of failing, and the session
            # keeps using the scripted mouth track.
            reloaded = await client.call("ml_reload_model")
            assert reloaded["session"] is True
            print(f"  [ok] ml_reload_model (loaded={reloaded['gesture_loaded']})")

            # Nothing is playing, so this is a no-op -- the point is that a stray Stop
            # click is answered rather than erroring.
            assert (await client.call("ml_preview_stop"))["stopped"] is False
            print("  [ok] ml_preview_stop with nothing playing")

        await client.call("send_text", text="Hello there [Nod] (Happy) I am Ms Mimic. "
                                            "This is a fairly long test sentence so there is "
                                            "time to interrupt. And one more sentence here.")
        await client.wait_topic("transcript", timeout=5.0)
        assert client.by_topic["transcript"][0]["text"].startswith("Hello there")
        print("  [ok] transcript event for the typed turn")

        await client.wait_topic("state", timeout=10.0)
        await client.wait_topic("speech", timeout=10.0)
        print("  [ok] state + speech events during the turn")

        # Interrupt mid-speech and confirm the turn winds down (idle again).
        await asyncio.sleep(0.4)
        client.by_topic["state"] = []  # Do not accept the initial idle event.
        await client.call("interrupt")
        idle_seen = await _wait_state(client, "idle", timeout=15.0)
        assert idle_seen, "session did not return to idle after interrupt"
        print("  [ok] interrupt -> back to idle")

        stopped = await client.call("session_stop")
        assert stopped["session"] is False
        print("  [ok] session_stop")
    finally:
        await client.close()


async def _wait_joint_value(client: Client, joint: str, target: float,
                            tolerance: float, timeout: float) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        frames = client.by_topic.get("joints", [])
        if frames and abs(frames[-1].get(joint, -999) - target) <= tolerance:
            return True
        remaining = deadline - loop.time()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(client.events.get(), timeout=max(0.1, remaining))
    return False


async def _wait_joint_predicate(client: Client, joint: str, predicate, timeout: float):
    """Poll the latest `joints` frame until predicate(value) holds; returns the
    matching value, or None on timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        frames = client.by_topic.get("joints", [])
        if frames:
            value = frames[-1].get(joint)
            if value is not None and predicate(value):
                return value
        remaining = deadline - loop.time()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(client.events.get(), timeout=max(0.1, remaining))
    return None


async def _wait_state(client: Client, target: str, timeout: float) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        states = [e["state"] for e in client.by_topic.get("state", [])]
        if target in states:
            return True
        remaining = deadline - loop.time()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(client.events.get(), timeout=max(0.1, remaining))
    return target in [e["state"] for e in client.by_topic.get("state", [])]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller", default="virtual",
                        choices=["virtual", "sim", "console", "hardware"])
    parser.add_argument("--attach", type=int, default=None,
                        help="Connect to an already-running server on this port instead of spawning one.")
    args = parser.parse_args()

    if args.attach is not None:
        print(f"Attaching to existing server on port {args.attach} (controller={args.controller})")
        await run_checks(args.attach, args.controller)
        print("\nALL CHECKS PASSED")
        return 0

    port = _free_port()
    print(f"Launching: {sys.executable} -m obot --serve --port {port}")
    proc = subprocess.Popen(
        [sys.executable, "-m", "obot", "--serve", "--port", str(port)],
        cwd=str(_REPO_ROOT),
    )
    try:
        await _wait_port(port)
        await run_checks(port, args.controller)
        print("\nALL CHECKS PASSED")
        return 0
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=10)
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
