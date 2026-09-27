from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..config import OllamaSSHConfig


class SSHTunnelError(RuntimeError):
    """Raised when the SSH tunnel cannot be established."""


@contextmanager
def open_ollama_tunnel(cfg: OllamaSSHConfig) -> Iterator[int]:
    """Open an SSH port forward to a remote Ollama and yield the bound local port.

    When ``ollama_ssh.host`` is empty, skip SSH and yield the local Ollama port
    (``remote_ollama_port``, default 11434) so a machine-local ``ollama serve`` works
    without a tunnel.
    """

    # Local Ollama on this machine — no SSH required.
    if not (cfg.host or "").strip():
        yield int(cfg.remote_ollama_port or 11434)
        return

    # Validate the required fields up front so the user gets a clear message
    # instead of a paramiko stack trace when something is missing.
    if not cfg.user:
        raise SSHTunnelError("ollama_ssh.user is empty, fill it in config.json.")
    if not cfg.key_path:
        raise SSHTunnelError("ollama_ssh.key_path is empty, fill it in config.json.")

    key_path = Path(cfg.key_path).expanduser()
    if not key_path.exists():
        raise SSHTunnelError(f"SSH key file not found: {key_path}")

    try:
        from sshtunnel import BaseSSHTunnelForwarderError, SSHTunnelForwarder
    except ImportError as exc:
        raise SSHTunnelError(
            "sshtunnel is not installed. Run: python -m pip install -e '.[ssh]'"
        ) from exc

    forwarder = SSHTunnelForwarder(
        (cfg.host, cfg.port),
        ssh_username=cfg.user,
        ssh_pkey=str(key_path),
        remote_bind_address=(cfg.remote_ollama_host, cfg.remote_ollama_port),
        # Bind to port 0 so the OS picks a free local port. The chosen port is read
        # back from forwarder.local_bind_port and handed to the HTTP client.
        local_bind_address=("127.0.0.1", 0),
    )

    try:
        forwarder.start()
    except BaseSSHTunnelForwarderError as exc:
        raise SSHTunnelError(f"could not reach {cfg.host}:{cfg.port}  {exc}") from exc
    except Exception as exc:
        raise SSHTunnelError(f"failed to open SSH tunnel: {exc}") from exc

    try:
        yield int(forwarder.local_bind_port)
    finally:
        forwarder.stop()
