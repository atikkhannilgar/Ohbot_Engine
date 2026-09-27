# OhBot Control: desktop GUI

A cross-platform desktop GUI for the whole OhBot workflow (setup, config, live
conversation), talking to the Python engine over the local WebSocket control server
(`python -m obot --serve`). **First-time install and start:** follow the root
[README.md](../README.md), then [../docs/installation.md](../docs/installation.md).
This file describes the GUI pages after the engine is running.

All the intelligence stays in Python. The GUI never re-implements the pipeline, it just
calls RPC methods and renders the events pushed back. It's built with **Avalonia**, so one
codebase runs natively on **Windows, Linux and the Raspberry Pi**.

| Project | What |
|---|---|
| `ObotControl.Core` | UI-framework-free brain: protocol client (`EngineClient`), typed API (`EngineApi`), config/event DTOs, engine-process launcher, shared help text, and all MVVM view-models (CommunityToolkit.Mvvm). |
| `ObotControl.App` | The Avalonia desktop app, thin XAML views over Core. `Styles/Tokens.axaml` holds every colour, font size and radius; `Styles/Controls.axaml` turns those into reusable classes (`card`, `inset`, `pill`, `section`, `hint`, `label`, `value`, and the `primary`/`ghost`/`danger`/`icon` button variants). Views reference tokens by name and never hardcode a hex value, so the app can be re-themed from one file. |
| `ObotControl.Core.Tests` | xunit: protocol/config round-trips + a live end-to-end test that drives the real engine. |

## Pages

- **Dashboard**: pick backend/model/controller, Start, type or talk, big **Interrupt**
  button, mic-mode toggle, live state indicator and active-TTS badge. The conversation is
  rendered as chat bubbles (user right, bot left, `[Action]`/`(Emotion)` markers as inline
  chips, interrupted sentences struck through). **Enter** sends a typed turn; Shift+Enter
  inserts a newline.
- **Setup**: step 0 provisions the Python environment itself (see below), then API key,
  serial port, remote-Ollama SSH, microphone (with a live level test), STT engine, and TTS
  voices with per-engine **Test** buttons. Save/Reload.
- **Configuration**: TTS engine + per-engine voice settings, **mouth-tuning sliders that
  apply live while the robot talks**, servo motion limits, ambient behaviors. Save/Revert/Reload.
- **Manual control**: jog each of the seven motors with a slider and watch its live
  position, for testing/calibrating servos outside a conversation. **Enable** freezes every
  joint at its current pose (no jump), then dragging a slider overrides that motor in the
  engine's mixer while ambient behaviors keep running on the rest. **Release** hands
  everything back to automatic control. Needs a running session (any backend/controller).
- **ML Control**: everything about the AI gesture model  the BEAT2-trained checkpoint that
  drives head/eyes/lids/lips straight from the speech waveform instead of the scripted
  loudness-envelope mouth track. Because the ML extras (torch and friends) are a large
  optional download, the page starts with a **dependency checklist** whenever something is
  missing: it names each requirement, shows which interpreter the engine is running on, and
  installs `requirements/ml.txt` into it at the press of a button, streaming pip's output to
  the Logs tab. torch is imported lazily, so a running session picks it up with no restart.
  The **model library** lists the checkpoints named in
  `config.json` plus everything found under `mlBehaviour/runs/` and `src/obot/ml/models/` on
  the engine host: pick which one drives speech, register a new one by path (with a name and
  notes), or **Inspect** one to see how many axes it drives, its mel/conv/GRU sizes,
  parameter count, epoch reached and best validation loss. Below that, the inference
  settings (device, control rate, **gesture intensity  applies live while the robot talks**,
  and "keep the lips on the scripted track"), a torch/CUDA runtime check, and **Preview**:
  play any wav through the selected checkpoint on the live robot, or replay a recorded BEAT2
  training clip as ground truth to compare against. Saving also loads the checkpoint into a
  running session, so swapping models doesn't need a session restart.
- **Logs**: engine stdout + structured log/error events, with level filters.

The **face preview is docked on the right and visible on every page**. It draws the robot
with a pseudo-3D look  the head yaws and nods with parallax and shading, the eyes are
glossy spheres under sliding lids, the mouth is two brushed-metal lip plates  all driven
live from the engine's joint stream, so it shows the commanded positions. It does not measure physical servo motion.
A **? Help** button (and hover tooltips on every control) explains what everything does.
Tooltips wait 900 ms before appearing and are dismissed as soon as the pointer drifts
more than ~28 px from where it opened, so they help when you rest on a control without
chasing you across the window (`Views/ToolTipBehavior.cs`).

Starting a session takes roughly 15 seconds (backend handshake, TTS model warm-up,
microphone ambient calibration), so **Start** shows a progress panel with an elapsed
counter and what is happening, rather than just greying itself out.

## Prerequisites

- **.NET 10 SDK** (`dotnet --version` ≥ 10). On Ubuntu, install it from Microsoft's
  package feed or with the official install script:
  `curl -sSL https://dot.net/v1/dotnet-install.sh | bash /dev/stdin --channel 10.0`.
- **macOS**: follow `../docs/installation.md`. A local app bundle can be built with
  `python3.12 scripts/package_macos.py` from the repository root.
- **Windows**: nothing else. The Setup tab's "0. Python environment" step provisions
  Python itself (see below).
- **Linux (Ubuntu 24.04+)**: the same automatic provisioning works  it prefers an
  existing venv or a system Python 3.12, and otherwise downloads a private
  python-build-standalone 3.12 (no root, no PATH changes), which is also what makes
  Ubuntu 25+ work even though its system Python is newer than 3.12. Two system
  libraries are needed once for audio: `sudo apt install libportaudio2 espeak-ng`.
  For the physical robot, add yourself to the serial group:
  `sudo usermod -aG dialout $USER` (log out and back in).
- No extra native tooling needed. Avalonia restores from NuGet and builds with plain `dotnet`.

## Build & run

Start with `python3.12 scripts/setup.py` from the repository root (`py -3.12` on
Windows). Automatic GUI setup now installs the small `requirements/desktop.txt`
profile. Add a voice with the `voice` setup profile; use the installation guide
for hardware, SSH, neural voices and movement learning.


```bash
cd gui
dotnet test ObotControl.Core.Tests/ObotControl.Core.Tests.csproj   # 33 tests, incl. a live engine round-trip
dotnet run  --project ObotControl.App/ObotControl.App.csproj        # launch the GUI
# whole solution: dotnet build ObotControl.slnx
```

Optional launch flags (also used by `../docker/start.sh`):

```bash
dotnet run --project ObotControl.App/ObotControl.App.csproj -- --host 127.0.0.1 --port 8765 --attach
```

| Flag / env | Meaning |
|---|---|
| `--host` / `OBOT_HOST` | Control-server address (default `127.0.0.1`) |
| `--port` / `OBOT_PORT` | Control-server port (default `8765`) |
| `--attach` / `OBOT_AUTO_ATTACH=1` | Connect immediately on startup |
## Using it

1. First run: the **Setup** tab opens automatically with **"0. Python environment"** at
   the top. It prefers whatever's already on your machine (an existing `OhBots`/`.venv`
   venv, or a system Python 3.12) and only downloads a private Python if nothing
   usable is found  the python.org installer on Windows, a python-build-standalone
   tarball on Linux. No admin prompt, no terminal, and it doesn't touch PATH or any
   existing install. Once it reports Ready, **Launch engine** (spawns
   `python -m obot --serve` from the repo root and connects) lights up, or you can
   **Attach** to a server you started yourself (host/port fields).

   If something's already listening on that port (say, an engine left running from an
   earlier session), Launch engine just connects to it instead of failing. You'll see a
   note about it in the Logs tab rather than an error.
2. **Setup**: Refresh devices. Leave the mic on **System default** (OS input) or pick a
   specific microphone — a concrete pick is saved immediately so the next session uses it.
   Test the mic, pick TTS voices (Test buttons), Save. Settings are the same `config.json`
   the terminal app uses, so the two stay in sync.
3. **Configuration**: drag the mouth-tuning sliders while the robot talks (applies live).
4. **Dashboard**: pick backend/model/controller, **Start**, then talk or type.
5. **ML Control** (optional): if the ML dependencies aren't installed yet, the page opens
   with a checklist of what's missing and an **Install ML requirements** button that runs
   pip into the engine's own environment  no terminal needed (a few hundred MB, several
   minutes). After that, Rescan finds your trained checkpoints, **Use** + **Save** puts one
   in charge of the motion, and **Preview** plays a clip through it on the live robot so you
   can see what it does before it shows up mid-conversation.

### Talking to it (microphone)

Start a session, then choose a **mic mode**:

- **vad**: open mic, just talk. It answers, and talking over the bot interrupts it.
  After the spoken reply finishes, VAD keeps listening for the next turn (the mic is
  only held closed during actual TTS playback and a short settle, not for the whole
  LLM stream). Your words show up live under the transcript (word-by-word with the
  offline **Vosk** STT engine; a "🎤 listening…" indicator + final text with Google STT).
- **ptt**: push-to-talk. The mic stays parked until you click **🎤 Talk** or press the
  **hotkey** (default Space; click *Set…* to rebind). One press captures one phrase. Typing in
  the message box never triggers the hotkey.
- **muted**: mic off. The engine stops the capture thread and releases the device (the
  Logs tab shows `microphone closed`). Switching back to **vad** or **ptt** opens it again.

When you open the mic, the **Logs** tab shows `microphone open on '<device>', listening`,
and any speech-to-text failure is logged there too, so if nothing is recognised you can
see which device opened and why. **System default** (or unset `input_device_index`) follows
the OS input device; it is not the first name in the Setup list. Pick a specific microphone
under **Setup** only when you need to override that.

The `virtual` controller runs the full motor mixer and real TTS with no window (the GUI
draws the face); `sim` opens the engine-side tkinter window; `console` is motion/audio-free.
Hardware needs `pip install -e '.[hardware]'` (Ohbot driver + pyserial) on **macOS, Windows
or Linux**, plus the correct serial port in Setup / `config.json` (examples: macOS
`/dev/cu.usbmodem…`, Linux `/dev/ttyACM0` or `/dev/ttyUSB0`, Windows `COMx`).

The face preview draws commanded joint positions on the 0..10 servo scale. Open-eye
LidBlink rest on this build is **7** (Neutral and most expressions); the preview shows
that value as 7/10 open, matching the hardware command, not a remapped "7 = fully lifted".
Exhausted droops the lids a little from that rest.
