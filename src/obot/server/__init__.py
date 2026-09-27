"""Local WebSocket control server that exposes the engine to a GUI.

Run it with ``python -m obot --serve``. See :mod:`obot.server.server` for the
protocol and :mod:`obot.server.session` for the RPC-driven conversation session.
"""

from .server import ControlServer, serve

__all__ = ["ControlServer", "serve"]
