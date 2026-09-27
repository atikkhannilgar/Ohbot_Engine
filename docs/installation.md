# Installation and first run

Use Python 3.12. Building or launching the desktop requires the .NET 10 SDK on your
PATH (`dotnet --version` should report 10.x). The initial setup does not need a robot,
a model account, Docker, or a movement-model checkpoint. Run commands from the
repository folder.

**Fastest path on any OS:** `scripts/setup.py`, then `scripts/run.py` (see the root
[README.md](../README.md)). Details per platform follow.

## macOS

```sh
python3.12 scripts/setup.py
# Either:
.venv/bin/python scripts/run.py
# Or build a local app bundle:
python3.12 scripts/package_macos.py
```

If `dotnet` is not found after installing the SDK, add it for that shell:
`export PATH="$HOME/.dotnet:$PATH"`.

If you built the bundle, open `dist/OhBot Control.app` in Finder. Keep it inside
this repository: it locates the Python engine and `.venv` by walking up from the
app folder. Click **Launch engine**, choose **scripted** and **virtual**, and press
**Start**. Type `Hello [Nod] (Happy) from OhBot.` The conversation view shows the
reply and labels; the face shows commanded positions. The microphone starts muted.

The local voice uses macOS's installed speech service through `/usr/bin/say`.
It writes an explicit WAV file for the engine, avoiding the file-format mismatch
observed with the original pyttsx3 path. No PyObjC installation is needed for this
voice. Select an installed voice in **Setup** if you want a different one.

The bundle built here contains its own .NET runtime. It is a local source build,
not a signed distribution or an app that can be moved away from the repository.
After moving the whole repository, rerun setup and the bundle builder.

## Windows and Linux

Windows:

```powershell
py -3.12 scripts/setup.py --profile voice
py -3.12 scripts/run.py
```

Linux:

```sh
sudo apt install libportaudio2 espeak-ng
python3.12 scripts/setup.py --profile voice
python3.12 scripts/run.py
```

The Linux system-library command applies to Debian/Ubuntu. Other distributions
use their own package managers. This revision was exercised on macOS; the
Windows/Linux instructions and hardware operation need checks on those systems.

## Setup profiles

| Profile | Installs |
|---|---|
| `console` | Engine and NumPy; text/action output only. |
| `desktop` (default) | Console plus server, HTTP model access and microphone API dependencies. macOS also has its built-in local voice. |
| `voice` | Desktop plus the local voice dependencies needed on Windows/Linux. |
| `full` | Desktop plus the platform file's optional recognizers, neural voices, SSH and robot drivers. Downloads are larger. |
| `ml` | Desktop plus movement-training/inference libraries. A dataset/checkpoint is still needed. |

Existing `config.json` is preserved. A new config starts with movement learning
off, a local voice and an empty model key. The supplied `config.example.json`
also disables background movements and contains no saved model or sample-audio path. Add only what you need:

```sh
.venv/bin/python -m pip install -e '.[ssh]'
.venv/bin/python -m pip install -e '.[hardware]'
.venv/bin/python -m pip install -r requirements/ml.txt
```

`.[hardware]` installs `ohbot` and `pyserial` (the `serial` module) on macOS, Windows and
Linux. Without it, starting a **hardware** session fails with `No module named serial`.
Set `ohbot_port` to the host USB serial device: macOS `/dev/cu.usbmodem…`, Linux
`/dev/ttyACM0` or `/dev/ttyUSB0` (user usually needs the `dialout` group), Windows `COMx`.

On Windows replace `.venv/bin/python` with `.venv\Scripts\python.exe`. Raspberry
Pi hardware deployment uses `requirements/pi.txt`. Gemini needs your own key;
local Ollama needs a running local server. Remote Ollama additionally needs SSH
settings. These live model connections were not exercised in the installation
check. Neural voices remain in the full platform requirements.

## Checks and server-only operation

```sh
.venv/bin/python scripts/check_setup.py --desktop
.venv/bin/python scripts/run.py --console
.venv/bin/python tests/test_server_smoke.py
.venv/bin/python -m unittest discover -s tests -p test_installation.py -v
dotnet test gui/ObotControl.Core.Tests/ObotControl.Core.Tests.csproj
```

The setup check imports the required modules, checks the installed source path,
and runs `pip check`. The console example should print a nod and a Happy request.
The server smoke test should end with `ALL CHECKS PASSED`; it uses a scripted
virtual session. These are software checks, not measurements of robot movement.

To start only the server, run `python3.12 scripts/run.py --engine-only`. Ctrl+C
stops the child started by this command. If port 8765 is occupied, choose another
with `--port 8766`, or attach manually to an existing engine through the desktop.
The launcher never kills the process occupying a port or stops Docker containers.

## Troubleshooting

- **Missing NumPy or server modules:** rerun `scripts/setup.py` with Python 3.12.
  The package now declares NumPy, and the desktop profile includes WebSockets.
- **A partially installed environment looks ready:** the GUI now verifies its
  desktop imports and source path before enabling launch. Use the setup checker
  above to see the failing import.
- **Vosk installation on macOS:** the full Mac requirements select 0.3.44, the
  compatible version found during resolution. The desktop profile does not need
  Vosk. Other platforms retain their existing `>=0.3.45` requirement.
- **RenderTimer error `-6661`:** the source launch from the automated shell failed
  with this error in our check. Opening the freshly built app bundle through the
  native desktop succeeded. Use that path on Mac. The underlying shell rendering
  failure has not been diagnosed.
- **No voice or empty audio in a non-desktop session:** inspect the Logs tab for
  the selected speech backend and any simulated-timing message. The native Mac
  app produced local speech in our check, while the automated shell's standalone
  native-voice checks returned empty audio. For a direct check in your logged-in
  Mac terminal, run `.venv/bin/python checks/check_macos_voice.py`.

The launcher keeps its preferences in `.obot/settings.json`. This separates the
checkout's selected interpreter from other OhBot installations. For a direct
`dotnet run`, set `OBOT_SETTINGS_DIR` to that folder if you want the same settings.
The macOS bundle builder records that location automatically.
