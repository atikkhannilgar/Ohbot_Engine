"""Use installed macOS voices without a Python Objective-C bridge."""
from __future__ import annotations

import re
import subprocess


def voice_names() -> list[str]:
    try:
        result = subprocess.run(["/usr/bin/say", "-v", "?"], capture_output=True, text=True, check=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    names = []
    for line in result.stdout.splitlines():
        match = re.match(r"^(.*?)\s{2,}[a-zA-Z]{2,3}[_-][a-zA-Z_]+\s", line)
        if match:
            names.append(match.group(1).strip())
    return names


class MacSayBackend:
    def __init__(self, settings) -> None:
        self.settings = settings
        requested = settings.voice.strip().casefold()
        self.voice = next((name for name in voice_names() if requested and requested in name.casefold()), None)

    def synth_to_file(self, text: str, path: str) -> None:
        command = ["/usr/bin/say", "-o", path, "--file-format=WAVE", "--data-format=LEI16@22050",
                   "-r", str(max(1, int(self.settings.rate_wpm)))]
        if self.voice:
            command += ["-v", self.voice]
        # Text goes through stdin, never through a shell or command-line options.
        subprocess.run(command, input=text, text=True, capture_output=True, check=True, timeout=60)
