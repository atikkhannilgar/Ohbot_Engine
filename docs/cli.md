# Command-line Reference

Three entry points, each runnable with `python -m <module> --help`.

## `python -m obot`: the full chat pipeline

```bash
python -m obot [--text "..."] [--chunk-size N] [--console] [--sim] [--no-gesture-model] [--scripted-mouth]
```

| Flag | Default | What it does |
|---|---|---|
| `--text "..."` | - | Skip the interactive backend picker and voice session entirely: run the scripted demo once with this exact text, then exit. No API key, config.json, or microphone needed. |
| `--chunk-size N` | `24` | Characters per chunk fed to the `StreamProcessor` by the scripted LLM source (only relevant with `--text`) smaller values exercise streaming/token-boundary edge cases harder. |
| `--console` | off | Force `ConsoleObotController`: prints what the robot *would* do, needs no `ohbot` library, servos, or audio device. |
| `--sim` | off | Use the digital OhBot (simulator window) instead of real hardware. See [Running without the robot](#running-without-the-robot). |
| `--no-gesture-model` | off | Force the AI gesture model off for this run, overriding `config.json`'s `speech.gesture.enabled`. The scripted RMS-envelope mouth/motion track is used instead. |
| `--scripted-mouth` | off | Use the AI gesture model for head/eyes/lids movement but keep the scripted RMS-envelope mouth track for TOPLIP/BOTTOMLIP. Overrides `config.json`'s `speech.gesture.scripted_mouth` for this run. |

With no flags, `python -m obot` prompts for a backend (Gemini / remote Ollama / scripted demo / example script) and starts the full voice session. See [Session controls](#session-controls) and [Microphone input](#microphone-input).

## `python -m obot.sim`: standalone speech/motion test bench

```bash
python -m obot.sim [--text "..."] [--no-tuning]
```

| Flag | Default | What it does |
|---|---|---|
| `--text "..."` | | Speak this once at startup (tags like `[Nod]`/`(Happy)`/`!Delay500` work), then drop into the interactive prompt. |
| `--no-tuning` | off | Hide the mouth-tuning sliders and "Save to config.json" button in the simulator window. |

No LLM backend involved, type sentences directly at the prompt.

## `python -m obot.ml`: AI gesture model runner

Drives the Ohbot straight from the BEAT2-trained audio model, independent of the chat pipeline. See [mlBehaviour/README.md](../mlBehaviour/README.md) for the training side.

```bash
python -m obot.ml <checkpoint> <wav> [--control-hz HZ] [--device cpu|cuda] [--intensity N] [--console] [--sim]
```

| Flag | Default | What it does |
|---|---|---|
| `checkpoint` (positional) | | Path to a `train.py` checkpoint, e.g. `mlBehaviour/runs/my_experiment/best_model.pt`. |
| `wav` (positional) | | Audio file to play and gesture along to. |
| `--control-hz` | `20.0` | Must match the `--control-hz` the checkpoint was trained with (`beat2_to_ohbot.py`). |
| `--device` | `cpu` | torch device for inference: `cpu` or `cuda`. |
| `--intensity` | `1.0` | Scales predicted movement around rest position: `>1` exaggerates the gestures, `<1` dampens them. |
| `--console` | off | Force the hardware-free console controller. |
| `--sim` | off | Use the digital OhBot simulator window. |

Needs `pip install -r requirements/ml.txt` (adds torch/scipy/soundfile on top of the base app).

---

## Backends

Pick one at startup:

1. **Online (Gemini)**: Connects to Google's Generative Language API using an API key. Every model the key has access to is listed live, so you can pick whichever Gemini model you want per session.

2. **Remote Ollama (over SSH)**: Talks to an Ollama server on another machine. The code opens an SSH port-forward using your private key, then speaks plain HTTP through the tunnel as if Ollama were local. The model list comes from the remote `/api/tags`.

3. **Scripted demo**: Replays a fixed string, no API or config needed. Good for sanity-checking the parser.

4. **Example script**: Full capability demo from `example_script.txt`.

---

## Running without the robot

**IMPORTANT**: The following simuation options are depricated. It is recomended to run the fengine with --serve and use the GUI for the sim visualization. The GUI will also allow you to run the engine with the robot hardware if you have it connected.

Two hardware-free options:

**1. The digital OhBot (recommended):**

```bash
python -m obot --sim            # full pipeline against the simulator window
python -m obot.sim              # standalone speech/motion test bench
python -m obot.sim --text "Hello [Nod] world! (Happy) Great to see you."
```

The window renders head pose, eyes, lids and lips exactly as the mixer would drive the servos, plays the real TTS audio through your speakers, and shows live joint values. The side panel has **mouth tuning sliders** and a **Save to config.json** button, so you can dial in the lip sync there and the hardware will use the same values.

**2. Console only** (no window, no audio):

```bash
python -m obot --console
```

---

## Microphone input

For the Gemini and Ollama backends you talk to the bot with the host machine's microphone. Capture uses [sounddevice](https://python-sounddevice.readthedocs.io/).

### Startup picks (after model selection)

**1. Microphone**: The list shows only real physical devices. After you pick:
- A **live level meter** records ~3 seconds so you can see if the mic is responding.
- It **plays the recording back** so you can hear whether it sounds correct.
- Answer `Y` to confirm or anything else to re-pick.

Your choice is saved to `config.json` and offered as the default next time.

**2. Speech-to-text engine**

| Engine | Mode | Notes |
|---|---|---|
| **Vosk** | Offline | Runs on the Pi with no internet. Needs a model file (see below). |
| **Google** | Online | Higher accuracy, no model file, requires internet. |

### Vosk offline model setup

Two options.

Option 1: run `sprc download vosk` to download and set up a model automatically (recommended).

Option 2: set up a model yourself manually:

1. Download a model from [alphacephei.com/vosk/models](https://alphacephei.com/vosk/models).
   - `vosk-model-small-en-us-0.15` (~40 MB): fast, good for the Pi.
   - `vosk-model-en-us-0.22` (~1.8 GB): more accurate, heavier.
2. Unzip it. You get a folder like `vosk-model-small-en-us-0.15/` whose contents are `am/`, `conf/`, `graph/`, `ivector/`, `README`.
3. Point `audio.vosk_model_path` in `config.json` at **that folder**.

```json
"audio": {
  "vosk_model_path": "C:/path/to/vosk-model-small-en-us-0.15"
}
```

---

## Session controls

| Key | Action |
|---|---|
| `SPACE` | Interrupt the bot while it is speaking |
| `m` | Mute / unmute the microphone |
| `p` | Push-to-talk: capture a single utterance then wait |
| `o` | Open mic (back to continuous auto-VAD) |
| `c` | Switch to **console mode**: type messages instead of speaking |
| `q` / `Esc` | Quit |

### Console mode

Press `c` during a session to switch to typed input (mic mutes, key shortcuts pause, a `[console] >` prompt appears). Type a message and Enter to send. Press Enter on an **empty line** or type `:voice` to go back to the microphone. `:quit` exits.

### Interrupting the bot

While the bot is speaking, cut it off two ways:

- **Start talking**: voice barge-in detects sustained loudness and fires immediately.
- **Press `SPACE`**: always reliable, no echo risk.

Speech stops at the current **sentence boundary**, all remaining sentences are dropped, and the bot is told on its next turn what it actually said aloud and what it had been about to say.

---

## System prompt syntax

Edit `system_prompt.txt` to change the bot's persona. The parser recognises three kinds of inline markers:

- **`[Action]`** (square brackets): trigger robot motions. Built-in: `Nod`, `Blink`, `Wink`, `LookLeft`, `LookRight`, `ShakeHead`. Case-insensitive.
- **`(Emotion)`** (round brackets): set the displayed emotion. Built-in: `Happy`, `Sad`, `Confused`, `Angry`, `Exhausted`, `Whispering`, `Shouting`. Stays set until overwritten.
- **`!DelayX`**: insert a pause of `X` milliseconds after the current sentence ends, before the next begins.

Everything else is treated as spoken text, split into sentences on `.`, `!`, and `?`.
