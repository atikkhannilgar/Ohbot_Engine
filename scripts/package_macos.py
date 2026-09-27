"""Build a local macOS app bundle after scripts/setup.py has completed."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if sys.platform != "darwin":
        print("This command builds the macOS desktop bundle.", file=sys.stderr)
        return 1
    dotnet = shutil.which("dotnet") or str(Path.home() / ".dotnet/dotnet")
    if not Path(dotnet).exists():
        print("Install the .NET 10 SDK first.", file=sys.stderr)
        return 1
    rid = "osx-arm64" if platform.machine() == "arm64" else "osx-x64"
    bundle = ROOT / "dist/OhBot Control.app"
    executable_dir = bundle / "Contents/MacOS"
    executable_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([dotnet, "publish", str(ROOT / "gui/ObotControl.App/ObotControl.App.csproj"),
                    "-c", "Release", "-r", rid, "--self-contained", "true", "-o", str(executable_dir)], cwd=ROOT, check=True)
    (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": "org.ohbot.behaviourengine.localbuild",
        "CFBundleName": "OhBot Control",
        "CFBundleDisplayName": "OhBot Control",
        "CFBundleExecutable": "ObotControl.App",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1.0.0",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": "Use the selected microphone for OhBot conversation input.",
        "LSEnvironment": {"OBOT_SETTINGS_DIR": str(ROOT / ".obot")},
    }))
    print(f"Built {bundle}")
    print("Open this bundle in Finder. Keep it inside this repository; the Python engine is beside dist/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
