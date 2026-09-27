"""Create a local Python environment and install an OhBot setup profile."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def python_in(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def seed_config(root: Path) -> bool:
    """Create first-run settings; never overwrite an existing private config."""
    target = root / "config.json"
    if target.exists():
        return False
    config = json.loads((root / "config.example.json").read_text(encoding="utf-8"))
    config["speech"]["gesture"]["enabled"] = False
    config["speech"]["tts"]["engine"] = "local"
    config["speech"]["tts"]["local"]["voice"] = ""
    config["audio"]["stt_engine"] = "google"
    config["ohbot_port"] = "COM7" if os.name == "nt" else "/dev/ttyACM0"
    try:
        with target.open("x", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2)
            handle.write("\n")
    except FileExistsError:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["console", "desktop", "voice", "full", "ml"], default="desktop")
    parser.add_argument("--venv", type=Path, default=ROOT / ".venv")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error("Use Python 3.12: python3.12 scripts/setup.py (Windows: py -3.12 scripts/setup.py).")
    directory = args.venv.expanduser().resolve()
    python = python_in(directory)
    if directory.exists():
        if not (directory / "pyvenv.cfg").is_file() or not python.exists():
            parser.error(f"{directory} is not a usable virtual environment. Choose a new --venv path; nothing was deleted.")
        subprocess.run([str(python), "-c", "import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)"], check=True)
    else:
        print(f"Creating {directory}", flush=True)
        venv.EnvBuilder(with_pip=True).create(directory)
    extras = {"console": "", "desktop": "[desktop]", "voice": "[desktop,voice]", "full": "[desktop]", "ml": "[desktop,ml]"}
    subprocess.run([str(python), "-m", "pip", "install", "-e", f".{extras[args.profile]}"], cwd=ROOT, check=True)
    if args.profile == "full":
        requirements = "windows.txt" if os.name == "nt" else "macos.txt" if sys.platform == "darwin" else "linux.txt"
        subprocess.run([str(python), "-m", "pip", "install", "-r", f"requirements/{requirements}"], cwd=ROOT, check=True)
    created = seed_config(ROOT)
    print("Created config.json with optional movement learning off." if created else "Kept existing config.json.")
    check = [str(python), str(ROOT / "scripts/check_setup.py")]
    if args.profile != "console":
        check.append("--desktop")
    subprocess.run(check, cwd=ROOT, check=True)
    if sys.platform == "darwin" and args.profile != "console":
        print("Setup complete. Build the desktop: python3.12 scripts/package_macos.py")
        print("Then open dist/OhBot Control.app in Finder and click Launch engine.")
    else:
        print("Setup complete. Run: python3.12 scripts/run.py" if os.name != "nt" else "Setup complete. Run: py -3.12 scripts/run.py")
    if args.profile in ("console", "desktop", "ml") and sys.platform != "darwin":
        print("For audible speech, add: python3.12 scripts/setup.py --profile voice" if os.name != "nt" else "For audible speech, add: py -3.12 scripts/setup.py --profile voice")
    if args.profile == "console":
        print("Use --console for this profile; desktop mode needs the desktop profile.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Setup stopped (exit {exc.returncode}). Fix the error above, then rerun setup; existing settings are retained.", file=sys.stderr)
        raise SystemExit(exc.returncode)
