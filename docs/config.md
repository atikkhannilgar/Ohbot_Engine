# Configuration Reference

Copy `config.example.json` to `config.json` and fill in the keys you need. `config.json` is gitignored.

## Fields

| Field | Meaning |
|---|---|
| `gemini_api_key` | API key from Google AI Studio. Only needed for the Gemini backend. |
| `ollama_ssh.host` | Hostname or IP of the SSH server running Ollama. **Leave empty to use Ollama on this machine** (`http://127.0.0.1:11434`). |
| `ollama_ssh.port` | SSH port, default `22` (ignored for local Ollama). |
| `ollama_ssh.user` | SSH username (required only when `host` is set). |
| `ollama_ssh.key_path` | Path to the private key file (OpenSSH format; required only when `host` is set). |
| `ollama_ssh.remote_ollama_host` | Where Ollama listens on the remote side (or locally). Usually `localhost`. |
| `ollama_ssh.remote_ollama_port` | Ollama port, default `11434`. |
| `audio.input_device_index` | Saved microphone device index. Maintained by the mic picker. `null` (or GUI **System default**) uses the OS / PortAudio default input when the mic is opened — not the first name in the device list. |
| `audio.stt_engine` | Last STT engine picked: `vosk` or `google`. Maintained automatically. |
| `audio.vosk_model_path` | Path to an unzipped Vosk model directory. Required only for offline STT. |
| `recent_gemini_models` | MRU list of Gemini models (last 3). Maintained automatically. |
| `recent_ollama_models` | Same idea for Ollama. Maintained automatically. |
| `ohbot_port` | Serial device for the physical OhBot. Examples: macOS `/dev/cu.usbmodem…`, Linux `/dev/ttyACM0` or `/dev/ttyUSB0`, Windows `COM3`. Used by the hardware controller. |
| `speech.tts.engine` | `"auto"` (edge → kokoro → piper → local), or pin one: `"edge"`, `"kokoro"`, `"gtts"`, `"gemini"`, `"piper"`, `"local"`. |
| `speech.tts.edge.*` | Edge neural voice: `voice` (e.g. `en-GB-SoniaNeural`), `rate`/`volume`/`pitch` prosody strings. |
| `speech.tts.kokoro.*` | Offline neural voice: `voice` (e.g. `bf_emma`), `speed`, `lang`; model auto-downloads. |
| `speech.tts.gtts.*` | Google Translate TTS: `lang` (`en`), `tld` accent (`co.uk`), `slow`. |
| `speech.tts.gemini.*` | TTS model, prebuilt voice name (`Kore`, `Puck`, `Leda`, ...), optional `style` instruction. |
| `speech.tts.piper.*` | Offline neural voice: `voice` name (auto-downloaded), or explicit `model_path`; `length_scale` = pace. |
| `speech.tts.local.*` | Basic voice substring (`zira`), speaking rate (wpm), volume. |
| `speech.gesture.enabled` | `true` to drive head/eyes/lids/lips from the BEAT2-trained audio model; `false` uses the scripted mouth track only. |
| `speech.gesture.checkpoint_path` | Path to a `train.py` checkpoint, e.g. `mlBehaviour/runs/my_experiment/best_model.pt`. |
| `speech.gesture.control_hz` | Must match the `--control-hz` used during training (default `20.0`). |
| `speech.gesture.device` | torch device: `"cpu"` or `"cuda"`. |
| `speech.gesture.intensity` | Scales predicted movement around rest: `1.0` = model output, `>1` exaggerates, `<1` dampens. |
| `speech.gesture.scripted_mouth` | `true` = ML model drives head/eyes/lids but lips use the scripted RMS-envelope mouth track. |
| `speech.mouth.*` | Lip-sync tuning: `gate`, `gamma`, `attack`, `release`, `top_gain`, `bottom_gain`, `fps`, `sync_offset_s`. Tune live in the simulator. |
| `speech.output_device_index` | sounddevice output device for TTS playback. `null` = default speakers. |
| `motion.*` | Servo mixer: tick rate, slew-rate limits (head vs lips), write threshold. |
| `behaviors.*` | Ambient behavior modules (see [speech docs](speech.md)). |
| `ml.models` | Named gesture-model checkpoints: `[{ "name", "path", "notes" }]`. Managed by the GUI's ML Control page; `speech.gesture.checkpoint_path` picks which one is used. |
| `ml.scan_dirs` | Extra folders searched for `*.pt` checkpoints, on top of `src/obot/ml/models` and `mlBehaviour/runs`. |
| `ml.preview_wav` | Audio file the ML Control page's Preview button plays through the model. Empty in the review settings; supply your own audio. |
| `ml.dataset_manifest` | `manifest.csv` from `beat2_to_ohbot.py convert`, for ground-truth clip replay. Blank = `mlBehaviour/ohbot_data/manifest.csv`. |

All of `speech`, `motion`, `behaviors` and `ml` are optional; missing keys use built-in defaults.

Paths in `speech.gesture.checkpoint_path`, `ml.models[].path`, `ml.preview_wav` and
`ml.dataset_manifest` may be absolute or repo-root-relative. Relative ones resolve against
the checkout, not the working directory, so the same `config.json` works however the engine
was launched (`ml/registry.py`).

## Review package defaults

The example and reference settings disable background movements and the optional movement model. No checkpoints or sample audio are bundled. Add your own checkpoint, audio and model-library entries when using the learning and preview tools. Setup preserves existing private settings and selects the local speech backend for a new config.
