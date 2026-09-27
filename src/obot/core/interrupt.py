from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

InterruptReason = Literal["voice", "keyboard"]


@dataclass(frozen=True)
class InterruptSignal:
    """Describes a single interruption: who/what raised it."""

    reason: InterruptReason


class InterruptController:
    """A one-shot, thread-safe interrupt flag for a single speaking turn.

    The bot's speech loop ``await``s / polls this controller, while the microphone
    barge-in monitor and the keyboard watcher live on *other* threads and trip it via
    :meth:`trigger`. Because those callers are not on the event loop, ``trigger`` hops
    back onto the loop with ``call_soon_threadsafe`` so the underlying
    :class:`asyncio.Event` is only ever touched from the loop thread.

    Reuse across turns is supported: call :meth:`clear` before the next turn.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self._loop = loop or asyncio.get_event_loop()
        self._event = asyncio.Event()
        self._signal: InterruptSignal | None = None

    @property
    def signal(self) -> InterruptSignal | None:
        return self._signal

    def trigger(self, reason: InterruptReason) -> None:
        """Raise the interrupt. Safe to call from any thread."""

        def _set() -> None:
            # First trigger wins; later ones during the same turn are ignored so the
            # recorded reason reflects whatever actually cut the bot off first.
            if not self._event.is_set():
                self._signal = InterruptSignal(reason=reason)
                self._event.set()

        try:
            self._loop.call_soon_threadsafe(_set)
        except RuntimeError:
            # Loop already closed (shutdown race)  nothing left to interrupt.
            pass

    def is_set(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> InterruptSignal:
        await self._event.wait()
        assert self._signal is not None
        return self._signal

    def clear(self) -> None:
        self._event.clear()
        self._signal = None
