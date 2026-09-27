"""Check first-run settings and launcher behavior without a robot or model account."""
from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from setup import seed_config
from run import available_port


class InstallationTests(unittest.TestCase):
    def test_new_config_disables_optional_model_and_uses_local_voice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.example.json").write_bytes((ROOT / "config.example.json").read_bytes())
            self.assertTrue(seed_config(root))
            data = json.loads((root / "config.json").read_text())
            self.assertFalse(data["speech"]["gesture"]["enabled"])
            self.assertEqual(data["speech"]["tts"]["engine"], "local")
            self.assertEqual(data["gemini_api_key"], "")

    def test_existing_private_config_is_preserved_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = b'{"custom_setting": "keep", "speech": {"gesture": {"enabled": true}}}\n'
            target = root / "config.json"
            target.write_bytes(content)
            self.assertFalse(seed_config(root))
            self.assertEqual(target.read_bytes(), content)

    def test_busy_port_remains_owned_by_existing_listener(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            self.assertFalse(available_port(port))
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                peer, _ = listener.accept()
                peer.close()

    def test_setup_refuses_an_existing_non_environment_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "keep.txt"
            marker.write_text("user data")
            result = subprocess.run([sys.executable, str(ROOT / "scripts/setup.py"), "--venv", directory], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("nothing was deleted", result.stderr)
            self.assertEqual(marker.read_text(), "user data")


if __name__ == "__main__":
    unittest.main()
