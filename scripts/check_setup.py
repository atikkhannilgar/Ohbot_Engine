"""Check imports and package compatibility without starting a robot or microphone."""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import platform
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    modules = ["numpy", "obot", "obot.__main__"]
    if args.desktop:
        modules += ["websockets", "httpx", "sounddevice", "speech_recognition", "obot.server.server"]
    checks = []
    for name in modules:
        try:
            importlib.import_module(name)
            checks.append({"module": name, "ok": True})
        except Exception as exc:
            checks.append({"module": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    pip = subprocess.run([sys.executable, "-m", "pip", "check"], text=True, capture_output=True)
    expected = Path(__file__).resolve().parents[1] / "src/obot/__init__.py"
    loaded = sys.modules.get("obot")
    correct_source = loaded is not None and Path(loaded.__file__).resolve() == expected.resolve()
    report = {"python": platform.python_version(), "executable": sys.executable,
              "platform": platform.platform(), "checks": checks,
              "correct_source": correct_source, "pip_check_ok": pip.returncode == 0,
              "pip_check": (pip.stdout + pip.stderr).strip()}
    report["ok"] = all(c["ok"] for c in checks) and correct_source and pip.returncode == 0
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Python {report['python']} — {sys.executable}")
        for check in checks:
            print(f"{'OK' if check['ok'] else 'MISSING'} {check['module']} {check.get('error', '')}")
        print(f"{'OK' if correct_source else 'WRONG SOURCE'} project installation")
        print(report["pip_check"])
        if not report["ok"]:
            print("Rerun scripts/setup.py with Python 3.12. On Linux, a PortAudio error needs libportaudio2.")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
