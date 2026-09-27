"""A tiny, thread-safe publish/subscribe bus for engine observability.

The engine has always narrated itself with ``print()``. That stays  but the
control server (``python -m obot --serve``) also needs the *data* behind those
lines so it can push structured events to a GUI over the WebSocket. Rather than
thread a bus object through every controller, behavior and speech call site,
there is one process-wide default bus and module-level :func:`emit` /
:func:`subscribe` helpers.

Design notes:

* **Emit is cheap when nobody listens.** :func:`emit` (and :func:`has_subscribers`)
  short-circuit on an empty subscriber list, so the console flow pays almost
  nothing. The hot mixer loop still guards its per-tick payload with
  :func:`has_subscribers` so it does not even build the dict when unobserved.
* **Any thread may emit.** The mixer thread, the mic capture thread and the
  asyncio loop all call :func:`emit`. Callbacks therefore run on *whatever*
  thread emitted; a subscriber that needs to touch an event loop (the server)
  is responsible for hopping back on with ``loop.call_soon_threadsafe``.
* **A failing subscriber can never break the engine.** Callback exceptions are
  swallowed (and printed once) so a broken GUI cannot take down the robot.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

# A subscriber is called as cb(topic, data).
Subscriber = Callable[[str, Any], None]

# Canonical topic names, shared by the engine (emitters) and the server (forwarder)
# so the two never drift on a stringly-typed key.
STATE = "state"          # {"state": "idle"|"listening"|"speaking"}
TRANSCRIPT = "transcript"  # {"role": "user", "text": str}
SPEECH = "speech"        # {"text": str, "event": "spoken"|"cutoff", "engine": str|None}
ACTION = "action"        # {"name": str}
EMOTION = "emotion"      # {"name": str}
JOINTS = "joints"        # {"HeadNod": float, ...} positions 0..10
MICLEVEL = "miclevel"    # {"level": float, "peak": float}
LOG = "log"              # {"level": "info"|"warn"|"error", "message": str}
ERROR = "error"          # {"message": str, "where": str}


class EventBus:
    """Topic-keyed fan-out. See the module docstring for the threading contract."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[str, list[Subscriber]] = {}

    def subscribe(self, topic: str, callback: Subscriber) -> Callable[[], None]:
        """Register ``callback`` for ``topic``; returns an unsubscribe function."""
        with self._lock:
            self._subscribers.setdefault(topic, []).append(callback)

        def _unsubscribe() -> None:
            with self._lock:
                subs = self._subscribers.get(topic)
                if subs and callback in subs:
                    subs.remove(callback)

        return _unsubscribe

    def has_subscribers(self, topic: str) -> bool:
        """True if anyone is listening on ``topic`` (used to gate hot-path emits)."""
        with self._lock:
            return bool(self._subscribers.get(topic))

    def emit(self, topic: str, data: Any = None) -> None:
        """Deliver ``data`` to every subscriber of ``topic``. Never raises."""
        with self._lock:
            subs = list(self._subscribers.get(topic, ()))
        for cb in subs:
            try:
                cb(topic, data)
            except Exception as exc:  # noqa: BLE001 - a subscriber must not kill the engine
                print(f"[events] subscriber for '{topic}' raised: {exc}")


# Process-wide default bus and the module-level helpers most call sites use.
_BUS = EventBus()


def subscribe(topic: str, callback: Subscriber) -> Callable[[], None]:
    return _BUS.subscribe(topic, callback)


def has_subscribers(topic: str) -> bool:
    return _BUS.has_subscribers(topic)


def emit(topic: str, data: Any = None) -> None:
    _BUS.emit(topic, data)


def default_bus() -> EventBus:
    return _BUS
