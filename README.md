# OhBot Behaviour Engine

This engine connects Gemini or Ollama responses to OhBot speech, named gestures, and expression poses. The desktop application selects the response source and controls the conversation. Scripted replies and screen preview support preparation before a robot session.

This draft declares version 1.0.0. It combines the installation improvements with the paper's recorder, reference settings and regression fixes. License and maintenance details are pending author completion; this draft has not been submitted or published.

## First run (macOS, Windows, Linux)

You need **Python 3.12** and the **.NET 10 SDK** on your PATH. Open a terminal in this folder (the repository root).

**1. Install the engine**

```sh
# macOS (built-in speech is in the default desktop profile)
python3.12 scripts/setup.py

# Linux (local voice extras, same as the installation guide)
python3.12 scripts/setup.py --profile voice

# Windows
py -3.12 scripts/setup.py --profile voice
```

On Debian/Ubuntu also install audio libraries once: `sudo apt install libportaudio2 espeak-ng`.

**2. Start the desktop + engine**

```sh
# macOS / Linux  (if `dotnet` is missing, try: export PATH="$HOME/.dotnet:$PATH")
.venv/bin/python scripts/run.py

# Windows
.venv\Scripts\python.exe scripts\run.py
```

**3. In the app**

1. Wait until it connects (or click **Launch engine** / **Attach**).
2. Dashboard: backend **scripted**, controller **virtual**, mic **muted**.
3. Press **Start**.
4. Type `Hello [Nod] (Happy) from OhBot.` and send.

You should see the reply, a nod, Happy, and the face preview move. No robot, API key, or training model is required for this path. Setup creates `.venv` and a private `config.json` only when missing; the initial config disables background movement and the optional audio movement model.

**Optional — macOS app bundle** (instead of `scripts/run.py`):

```sh
python3.12 scripts/package_macos.py
```

Open `dist/OhBot Control.app` in Finder; keep it inside this repository. Same scripted / virtual / muted steps as above.

Full profiles, troubleshooting, Docker and platform notes: [docs/installation.md](docs/installation.md). GUI pages and mic modes: [gui/README.md](gui/README.md).

## Small console example

For a console-only installation, run `python3.12 scripts/setup.py --profile console`. Otherwise use the desktop setup above. Run the following with the installed environment:

```sh
.venv/bin/python scripts/run.py --console
.venv/bin/python -m unittest discover -s tests -p test_regressions.py -v
.venv/bin/python -m unittest discover -s tests -p test_installation.py -v
.venv/bin/python checks/reproduce_full_demo.py . checks/reproduced
.venv/bin/python checks/example_custom_action.py
.venv/bin/python scripts/capture_demo.py --output checks/my-scripted-run.json
```

On Windows replace `.venv/bin/python` with `.venv\Scripts\python.exe`. Expected results: the sentence, Happy request and nod; 15 regression tests and four installation tests passing; 20 sentences, 12 action messages and eight expression messages from the nine-scene script; and a completed two-turn record with `live_model: false`. Durations vary. These outputs describe software commands, not measured motor movement.

The desktop profile also supports:

```sh
.venv/bin/python scripts/check_setup.py --desktop
.venv/bin/python tests/test_server_smoke.py
dotnet test gui/ObotControl.Core.Tests/ObotControl.Core.Tests.csproj
```

Expected output: valid desktop imports and `pip check`, `ALL CHECKS PASSED` from the server smoke test, and 33 passing C# tests. The server test uses a scripted virtual session. Recorded versions, commands and results are in `checks/verification.json` and `SOFTWARE-VERSIONS.md`.

## Connect a model or robot

Gemini needs an API key. Ollama can run on this computer with an empty SSH host, or on a remote server with configured SSH access. Select an exact model available to your account or server. Keep credentials in private `config.json`; do not redistribute it. Optional SSH and robot dependencies are separate setup choices in the installation guide.

The desktop selects the provider, voice, microphone mode and controller. Use **virtual** for the on-screen preview, **sim** for the separate Tk face window, or **hardware** for the robot. The same engine and Avalonia desktop target **macOS, Windows and Linux** (see [docs/installation.md](docs/installation.md)). Hardware mode needs an OhBot, a USB/serial connection, and the optional driver stack:

```sh
.venv/bin/python -m pip install -e '.[hardware]'
```

On Windows use `.venv\Scripts\python.exe -m pip install -e ".[hardware]"`. Set the serial port under Setup (or `ohbot_port` in private `config.json`): macOS `/dev/cu.usbmodem…`, Linux `/dev/ttyACM0` or `/dev/ttyUSB0`, Windows `COM3` (device manager). The project uses OhBot 2.2; recorded checks in this draft did not use a connected robot as a formal verification claim. See `gui/README.md` and `docs/` for controls. Open-eye LidBlink rest for this build is commanded at **7** on the 0..10 scale (see `gui/README.md`).

Mic modes after **Start**: **vad** listens between turns; **ptt** waits for Talk/hotkey; **muted** closes the capture device (not only ignores audio). Pick a microphone in Setup first.

`examples/config.reference.json` disables background movements and the optional movement model. Start without manual overrides. Enable other movement sources separately: model positions and manual targets can override a gesture on a joint.

## Record a live model example

The recorder saves typed inputs, the exact prompt, raw replies, extracted labels, settings, and events on one elapsed-time clock. It uses the engine clients and controllers. It does not record the microphone, desktop UI, or audio/video. Virtual mode here records joint events without opening the desktop preview.

```sh
python scripts/capture_demo.py --provider gemini --model YOUR_EXACT_MODEL --config config.json --controller virtual --output live-demo.json
python scripts/capture_demo.py --provider ollama --model YOUR_EXACT_MODEL --config config.json --controller virtual --output live-demo.json
```

Choose the configured provider and a known speech backend/voice. `--controller hardware` sends motor commands; use it on the prepared robot setup. `--stop-after 1.0` requests interruption after one second per turn. Pair JSON with a screen/audio recording or robot video to establish visible or audible output. Inspect label validity and appropriateness. No live-model recording is included.

## Extension, files and optional training

`checks/example_custom_action.py` adds Acknowledge as a nod followed by a blink. `docs/server.md` describes commands and events for other interfaces. The prompt lists supported labels; expression names describe poses, not measured perception.

`src/obot` contains the engine; `gui` the desktop; `mlBehaviour` training/conversion; `docs` guides; `tests` and `checks` tests and records; `examples` reference inputs/settings. BEAT2 data, saved models, presentations and sample audio are excluded pending redistribution review. They are unnecessary for the label-based example. Optional training requires separately obtained data and your own checkpoint; see `mlBehaviour/README.md`.

## Study use

Retain exact software/model identifiers, prompts, settings and output. Pin the speech option when voice consistency matters; fallback can change the voice or replace audio with simulated pacing. Preview shows commanded positions without physical feedback. Interruption records distinguish completed and incomplete utterances, but do not identify the exact audible cutoff.

Use supervised physical operation and a stop procedure. Explain transmission of participant text/audio to providers in consent. Motor limits are not a physical safety evaluation.

