"""The control server: a local WebSocket that exposes the engine to a GUI.

Protocol (see docs/gui-plan.md §3.2):

* request  ``{"type":"call","id":1,"method":"...","params":{...}}``
* result   ``{"type":"result","id":1,"ok":true,"data":{...}}`` (or ``ok:false,"error":"..."``)
* event    ``{"type":"event","topic":"state|transcript|speech|joints|log|...","data":{...}}``

All intelligence stays in the Python engine; the socket is a thin RPC + event
boundary so the GUI framework is swappable and the engine can later run on the Pi
with the GUI connecting over LAN. Binds to 127.0.0.1 only  no auth by design.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import fields, is_dataclass

import websockets

from ..config import Config, config_path
from ..core import events
from ..robot import joints
from ..robot.emotions import EMOTIONS
from .session import ServerSession

# Topics forwarded verbatim from the engine's event bus to every connected client.
_FORWARDED_TOPICS = (
    events.STATE, events.TRANSCRIPT, events.SPEECH, events.ACTION,
    events.EMOTION, events.JOINTS, events.MICLEVEL, events.LOG, events.ERROR,
)


def _copy_into(dst, src) -> None:
    """Recursively copy dataclass field values from ``src`` onto ``dst`` in place.

    In-place mutation (rather than object replacement) is what makes config edits
    hot-apply: the live controller holds the *same* ``speech``/``motion`` objects and
    the behavior manager the same ``behaviors`` sub-objects, so updating their fields
    is picked up by the running mixer / speech loop without a restart. Private
    (``_``-prefixed) fields such as ``Config._path`` are preserved on ``dst``.
    """
    for f in fields(dst):
        if f.name.startswith("_"):
            continue
        cur = getattr(dst, f.name)
        new = getattr(src, f.name)
        if is_dataclass(cur) and is_dataclass(new) and type(cur) is type(new):
            _copy_into(cur, new)
        else:
            setattr(dst, f.name, new)


class ControlServer:
    def __init__(self, cfg: Config, default_controller: str = "virtual") -> None:
        self.cfg = cfg
        self.default_controller = default_controller
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: set = set()
        self._out: asyncio.Queue = asyncio.Queue()
        self._session: ServerSession | None = None
        self._unsubs: list = []

    # -- event bridge ------------------------------------------------------------------

    def _on_event(self, topic: str, data) -> None:
        # Runs on whatever thread emitted (mixer/mic/loop). Hop onto the loop and hand
        # the payload to the broadcaster; never touch a websocket from another thread.
        loop = self._loop
        if loop is None:
            return
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(self._out.put_nowait, (topic, data))

    async def _broadcaster(self) -> None:
        while True:
            topic, data = await self._out.get()
            if not self._clients:
                continue
            message = json.dumps({"type": "event", "topic": topic, "data": data})
            await asyncio.gather(
                *(self._safe_send(ws, message) for ws in list(self._clients)),
                return_exceptions=True,
            )

    @staticmethod
    async def _safe_send(ws, message: str) -> None:
        with contextlib.suppress(Exception):
            await ws.send(message)

    # -- connection handling -----------------------------------------------------------

    async def _handler(self, websocket) -> None:
        self._clients.add(websocket)
        try:
            async for raw in websocket:
                # Each call runs concurrently so a long test_mic never blocks an
                # interrupt arriving on the same connection.
                task = asyncio.create_task(self._handle_message(websocket, raw))
                task.add_done_callback(lambda t: t.cancelled() or t.exception())
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)

    async def _handle_message(self, websocket, raw) -> None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return
        if msg.get("type") != "call":
            return
        req_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params") or {}
        handler = self._methods().get(method)
        if handler is None:
            await self._safe_send(websocket, json.dumps({
                "type": "result", "id": req_id, "ok": False,
                "error": f"unknown method '{method}'",
            }))
            return
        try:
            data = await handler(params)
            reply = {"type": "result", "id": req_id, "ok": True, "data": data}
        except Exception as exc:  # noqa: BLE001 - report any handler failure to the client
            reply = {"type": "result", "id": req_id, "ok": False, "error": str(exc)}
        await self._safe_send(websocket, json.dumps(reply))

    # -- RPC methods -------------------------------------------------------------------

    def _methods(self) -> dict:
        return {
            "get_config": self._m_get_config,
            "set_config": self._m_set_config,
            "list_mics": self._m_list_mics,
            "test_mic": self._m_test_mic,
            "list_gemini_models": self._m_list_gemini_models,
            "list_ollama_models": self._m_list_ollama_models,
            "list_tts_voices": self._m_list_tts_voices,
            "speak_test": self._m_speak_test,
            "session_start": self._m_session_start,
            "session_stop": self._m_session_stop,
            "send_text": self._m_send_text,
            "interrupt": self._m_interrupt,
            "set_mic_mode": self._m_set_mic_mode,
            "trigger_ptt": self._m_trigger_ptt,
            "set_joint": self._m_set_joint,
            "release_joint": self._m_release_joint,
            "release_all_joints": self._m_release_all_joints,
            "list_emotions": self._m_list_emotions,
            "set_emotion": self._m_set_emotion,
            "list_ml_models": self._m_list_ml_models,
            "inspect_ml_model": self._m_inspect_ml_model,
            "ml_status": self._m_ml_status,
            "ml_reload_model": self._m_ml_reload_model,
            "ml_preview": self._m_ml_preview,
            "ml_preview_stop": self._m_ml_preview_stop,
            "list_ml_clips": self._m_list_ml_clips,
            "ml_replay_clip": self._m_ml_replay_clip,
            "get_state": self._m_get_state,
            "ping": self._m_ping,
        }

    async def _m_ping(self, params: dict) -> dict:
        return {"pong": True}

    async def _m_get_config(self, params: dict) -> dict:
        return self.cfg.to_dict()

    async def _m_set_config(self, params: dict) -> dict:
        data = params.get("config")
        if not isinstance(data, dict):
            raise ValueError("set_config needs a 'config' object.")
        # Validate by parsing, then mutate the live cfg in place so an active session
        # hot-applies mouth/motion/behaviors, and persist atomically (engine owns the file).
        incoming = Config.from_dict(data)
        _copy_into(self.cfg, incoming)
        if self.cfg._path is None:
            self.cfg._path = config_path()
        self.cfg.save()
        events.emit(events.LOG, {"level": "info", "message": "config saved"})
        return self.cfg.to_dict()

    async def _m_list_mics(self, params: dict) -> dict:
        from ..audio.input import list_input_devices_detailed

        return {"mics": await asyncio.to_thread(list_input_devices_detailed)}

    async def _m_test_mic(self, params: dict) -> dict:
        from ..audio.input import stream_input_level

        index = params.get("index")
        index = int(index) if index is not None else None
        duration = float(params.get("duration_s", 3.0))

        def _on_level(rms: float, peak: float) -> None:
            events.emit(events.MICLEVEL, {"level": round(rms, 1), "peak": round(peak, 1)})

        peak = await asyncio.to_thread(
            stream_input_level, index, _on_level, duration_s=duration
        )
        return {"peak": round(peak, 1), "ok": peak >= 100}

    async def _m_list_gemini_models(self, params: dict) -> dict:
        from ..llm.gemini import list_gemini_models

        key = params.get("api_key") or self.cfg.gemini_api_key
        return {"models": await list_gemini_models(key)}

    async def _m_list_ollama_models(self, params: dict) -> dict:
        return {"models": await asyncio.to_thread(_list_ollama_blocking, self.cfg)}

    async def _m_list_tts_voices(self, params: dict) -> dict:
        from . import voices

        return await asyncio.to_thread(voices.list_tts_voices, self.cfg)

    async def _m_speak_test(self, params: dict) -> dict:
        from . import voices

        engine = params.get("engine", "local")
        voice = params.get("voice", "")
        text = params.get("text", "")
        used = await asyncio.to_thread(
            voices.speak_test_blocking, self.cfg, engine, voice, text
        )
        return {"engine": used}

    async def _m_session_start(self, params: dict) -> dict:
        session = self._ensure_session()
        return await session.start(
            backend=params.get("backend", "scripted"),
            model=params.get("model", ""),
            controller=params.get("controller") or self.default_controller,
        )

    async def _m_session_stop(self, params: dict) -> dict:
        if self._session is None:
            return {"session": False}
        return await self._session.stop()

    async def _m_send_text(self, params: dict) -> dict:
        self._require_session().send_text(params.get("text", ""))
        return {}

    async def _m_interrupt(self, params: dict) -> dict:
        self._require_session().interrupt()
        return {}

    async def _m_set_mic_mode(self, params: dict) -> dict:
        await self._require_session().set_mic_mode(params.get("mode", "muted"))
        return {}

    async def _m_trigger_ptt(self, params: dict) -> dict:
        self._require_session().trigger_ptt()
        return {}

    async def _m_set_joint(self, params: dict) -> dict:
        if "joint" not in params or "position" not in params:
            raise ValueError("set_joint needs 'joint' and 'position'.")
        joint_id = joints.resolve(params["joint"])
        position = max(0.0, min(10.0, float(params["position"])))
        self._require_session().set_joint(joint_id, position)
        return {}

    async def _m_release_joint(self, params: dict) -> dict:
        if "joint" not in params:
            raise ValueError("release_joint needs a 'joint'.")
        self._require_session().release_joint(joints.resolve(params["joint"]))
        return {}

    async def _m_release_all_joints(self, params: dict) -> dict:
        self._require_session().release_all_joints()
        return {}

    async def _m_list_emotions(self, params: dict) -> dict:
        return {"emotions": list(EMOTIONS.keys())}

    async def _m_set_emotion(self, params: dict) -> dict:
        emotion = params.get("emotion", "")
        if not emotion:
            raise ValueError("set_emotion needs an 'emotion'.")
        await self._require_session().set_emotion(emotion)
        return {}

    # -- ML gesture model ----------------------------------------------------------------
    #
    # The model *library* (config.json's "ml" section) is edited like every other config
    # section, through set_config -- these methods only do what the GUI cannot: look at
    # the filesystem and checkpoints on the engine host, and drive a live session.

    async def _m_list_ml_models(self, params: dict) -> dict:
        from ..ml import registry

        # Filesystem scan: off the loop so a slow/network drive can't stall the server.
        return await asyncio.to_thread(registry.list_models, self.cfg)

    async def _m_inspect_ml_model(self, params: dict) -> dict:
        from ..ml import registry

        path = params.get("path") or self.cfg.speech.gesture.checkpoint_path
        if not path:
            raise ValueError("inspect_ml_model needs a 'path' (or a configured checkpoint).")
        return await asyncio.to_thread(registry.inspect_checkpoint, path)

    async def _m_ml_status(self, params: dict) -> dict:
        from ..ml import registry

        # "probe" imports torch to answer the CUDA question; without it the poll stays
        # cheap and reports cuda_available: null ("not asked").
        status = await asyncio.to_thread(
            registry.runtime_status, self.cfg, bool(params.get("probe"))
        )
        if self._session is None:
            status.update({
                "session": False, "controller": None, "pose_capable": False,
                "gesture_loaded": False, "loaded_checkpoint": None,
                "preview_active": False, "preview_playing": "",
            })
        else:
            status.update(self._session.ml_status())
        return status

    async def _m_ml_reload_model(self, params: dict) -> dict:
        """Apply changed gesture settings (checkpoint/device/enabled) to the running
        session without restarting it. ``force`` reloads the same path again, which is
        what you want after re-training into it."""
        return await self._require_session().reload_gesture_model(bool(params.get("force")))

    async def _m_ml_preview(self, params: dict) -> dict:
        gesture = self.cfg.speech.gesture
        checkpoint = params.get("checkpoint") or gesture.checkpoint_path
        wav = params.get("wav") or self.cfg.ml.preview_wav
        if not checkpoint:
            raise ValueError("ml_preview needs a 'checkpoint' (or a configured one).")
        if not wav:
            raise ValueError("ml_preview needs a 'wav' to play.")
        return await self._require_session().ml_preview(
            checkpoint=checkpoint,
            wav=wav,
            control_hz=float(params.get("control_hz", gesture.control_hz)),
            intensity=float(params.get("intensity", gesture.intensity)),
            device=params.get("device") or gesture.device,
        )

    async def _m_ml_preview_stop(self, params: dict) -> dict:
        # Deliberately tolerant: this is a "make it stop" button, so a stale click after
        # playback already ended is a no-op rather than an error.
        stopped = self._session is not None and self._session.ml_preview_stop()
        return {"stopped": stopped}

    async def _m_list_ml_clips(self, params: dict) -> dict:
        from ..ml import registry

        manifest = params.get("manifest") or self.cfg.ml.dataset_manifest
        return await asyncio.to_thread(registry.list_clips, manifest)

    async def _m_ml_replay_clip(self, params: dict) -> dict:
        clip_path = params.get("path")
        if not clip_path:
            raise ValueError("ml_replay_clip needs a clip 'path' (see list_ml_clips).")
        return await self._require_session().ml_replay_clip(
            clip_path=clip_path,
            speed=float(params.get("speed", 1.0)),
            play_audio=bool(params.get("play_audio", True)),
        )

    async def _m_get_state(self, params: dict) -> dict:
        if self._session is None:
            return {"session": False, "state": "idle"}
        return self._session.state()

    # -- helpers -----------------------------------------------------------------------

    def _ensure_session(self) -> ServerSession:
        if self._session is None:
            self._session = ServerSession(self.cfg, self._loop)
        return self._session

    def _require_session(self) -> ServerSession:
        if self._session is None or not self._session.state().get("session"):
            raise RuntimeError("no active session; call session_start first.")
        return self._session

    # -- run ---------------------------------------------------------------------------

    async def run(self, host: str, port: int) -> None:
        self._loop = asyncio.get_running_loop()
        for topic in _FORWARDED_TOPICS:
            self._unsubs.append(events.subscribe(topic, self._on_event))
        broadcaster = asyncio.create_task(self._broadcaster())
        print(f"[serve] control server listening on ws://{host}:{port}")
        print(f"[serve] default controller: {self.default_controller}. Ctrl-C to stop.")
        try:
            async with websockets.serve(self._handler, host, port, max_size=4 * 1024 * 1024):
                await asyncio.Future()  # run until cancelled
        finally:
            broadcaster.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await broadcaster
            for unsub in self._unsubs:
                unsub()
            if self._session is not None:
                with contextlib.suppress(Exception):
                    await self._session.stop()


def _list_ollama_blocking(cfg: Config) -> list[str]:
    """Open the SSH tunnel, list remote Ollama models, close it. Runs in a worker thread."""
    from ..net.ssh_tunnel import open_ollama_tunnel
    from ..llm.ollama import list_ollama_models

    with open_ollama_tunnel(cfg.ollama_ssh) as bound_port:
        base_url = f"http://127.0.0.1:{bound_port}"
        return asyncio.run(list_ollama_models(base_url))


async def serve(host: str = "127.0.0.1", port: int = 8765,
                default_controller: str = "virtual",
                no_gesture_model: bool = False,
                scripted_mouth: bool = False) -> None:
    """Load config and run the control server until cancelled."""
    from ..config import load_config

    try:
        cfg = load_config()
    except FileNotFoundError:
        # The GUI's whole point is to create/repair config.json, so a missing file is
        # not fatal here: start from defaults and let set_config write it.
        cfg = Config.from_dict({}, path=config_path())
        print(f"[serve] no config.json yet  starting from defaults ({config_path()}).")

    if no_gesture_model:
        cfg.speech.gesture.enabled = False
    if scripted_mouth:
        cfg.speech.gesture.scripted_mouth = True

    server = ControlServer(cfg, default_controller=default_controller)
    await server.run(host, port)
