"""Run the installed engine and desktop, or a console example, from any directory."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

from setup import python_in, seed_config

ROOT = Path(__file__).resolve().parents[1]


def available_port(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def stop(process: subprocess.Popen | None) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--console", action="store_true")
    mode.add_argument("--engine-only", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--venv", type=Path, default=ROOT / ".venv")
    parser.add_argument("--text", default="Hello [Nod] (Happy) from OhBot.")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    python = python_in(args.venv.expanduser().resolve())
    if not python.exists():
        parser.error("Environment missing. Run Python 3.12 scripts/setup.py first.")
    check = [str(python), str(ROOT / "scripts/check_setup.py")]
    if not args.console:
        check.append("--desktop")
    if subprocess.run(check, cwd=ROOT).returncode:
        return 1
    seed_config(ROOT)
    if args.console:
        return subprocess.call([str(python), "-m", "obot", "--console", "--text", args.text], cwd=ROOT)
    dotnet = shutil.which("dotnet")
    if not dotnet:
        candidate = Path.home() / ".dotnet" / ("dotnet.exe" if os.name == "nt" else "dotnet")
        if candidate.is_file():
            dotnet = str(candidate)
    if not args.engine_only:
        if not dotnet:
            parser.error("Install .NET 10 SDK for the desktop, or use --engine-only / --console.")
        sdk = subprocess.run([dotnet, "--list-sdks"], capture_output=True, text=True)
        if sdk.returncode or not any(line.startswith("10.") for line in sdk.stdout.splitlines()):
            parser.error(".NET 10 SDK is required to build the desktop. The runtime alone is insufficient.")
    if not available_port(args.port):
        parser.error(f"Port {args.port} is already in use. Use --port {args.port + 1 if args.port < 65535 else 8765}, or attach through the GUI. No existing process was stopped.")
    env = dict(os.environ)
    env["OBOT_SETTINGS_DIR"] = str(ROOT / ".obot")
    preferences = ROOT / ".obot/settings.json"
    preferences.parent.mkdir(exist_ok=True)
    if not preferences.exists():
        import json
        preferences.write_text(json.dumps({"selectedPythonPath": str(python), "dashboardBackend": "scripted", "dashboardController": "virtual"}, indent=2), encoding="utf-8")
    engine = gui = None
    previous = signal.getsignal(signal.SIGTERM)
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    try:
        engine = subprocess.Popen([str(python), "-m", "obot", "--serve", "--host", "127.0.0.1", "--port", str(args.port)], cwd=ROOT, env=env)
        deadline = time.monotonic() + 30
        while True:
            if engine.poll() is not None:
                print("Engine exited during startup. See the error above.", file=sys.stderr)
                return engine.returncode or 1
            try:
                with socket.create_connection(("127.0.0.1", args.port), timeout=0.5):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    print("Engine did not open its port within 30 seconds.", file=sys.stderr)
                    return 1
                time.sleep(0.2)
        print(f"Engine ready: ws://127.0.0.1:{args.port}. Ctrl+C stops this launch.", flush=True)
        if args.engine_only:
            return engine.wait()
        gui = subprocess.Popen([dotnet, "run", "--project", str(ROOT / "gui/ObotControl.App/ObotControl.App.csproj"), "--", "--host", "127.0.0.1", "--port", str(args.port), "--attach"], cwd=ROOT, env=env)
        result = gui.wait()
        if result:
            print("Desktop launch failed. Keep testing the engine with --engine-only. See docs/installation.md for desktop troubleshooting.", file=sys.stderr)
        return result if result >= 0 else 1
    except KeyboardInterrupt:
        return 0
    finally:
        stop(gui)
        stop(engine)
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
