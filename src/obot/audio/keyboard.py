from __future__ import annotations

import sys
import threading
from typing import Callable

# Cross-platform single-key reader. Windows has msvcrt; POSIX needs raw termios mode.
# Imported lazily/guarded so the module loads on either platform.
try:
    import msvcrt  # type: ignore

    _HAVE_MSVCRT = True
except ImportError:  # pragma: no cover - exercised only on POSIX
    _HAVE_MSVCRT = False

if not _HAVE_MSVCRT:  # pragma: no cover - exercised only on POSIX
    try:
        import termios
        import tty

        _HAVE_TERMIOS = True
    except ImportError:
        _HAVE_TERMIOS = False


KeyCallback = Callable[[str], None]


class KeyListener:
    """Background thread that delivers each key press to a callback, one char at a time.

    The demo composes the behaviour: e.g. Space while the bot speaks raises an
    interrupt, ``m`` toggles mute. Keeping this generic means the mic path and the key
    path stay independent, and the same listener powers push-to-talk later.

    If the process has no usable TTY (piped stdin, certain IDE consoles) the listener
    quietly does nothing so the rest of the app still runs.
    """

    def __init__(self, on_key: KeyCallback) -> None:
        self._on_key = on_key
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        if _HAVE_MSVCRT:
            return True
        if not _HAVE_TERMIOS:
            return False
        try:
            return sys.stdin.isatty()
        except (ValueError, OSError):
            return False

    def start(self) -> None:
        if self._thread is not None or not self.available:
            return
        # Cleared so a listener stopped for console mode can be started again.
        self._stop.clear()
        target = self._run_windows if _HAVE_MSVCRT else self._run_posix
        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.3)
        # Reset so start() can spin up a fresh thread (toggling out of console mode).
        self._thread = None

    def _emit(self, ch: str) -> None:
        if ch:
            try:
                self._on_key(ch)
            except Exception:
                # A misbehaving callback must never kill the listener thread.
                pass

    def _run_windows(self) -> None:
        while not self._stop.is_set():
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                self._emit(ch)
            else:
                # No blocking getwch() so the stop flag is checked promptly.
                self._stop.wait(0.03)

    def _run_posix(self) -> None:  # pragma: no cover - exercised only on POSIX
        import select

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while not self._stop.is_set():
                ready, _, _ = select.select([sys.stdin], [], [], 0.05)
                if ready:
                    self._emit(sys.stdin.read(1))
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
