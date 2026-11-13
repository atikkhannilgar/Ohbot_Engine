# Speech Engine

`ohbot.say()` is gone. Speech now runs through `obot.speech.SpeechEngine`.

## Voices

Select a backend with `speech.tts.engine`, or use `"auto"` for the implemented fallback order: Edge, Kokoro, Piper, then local speech.

- **Edge** (`edge`): online speech through `edge-tts`.
- **Kokoro** (`kokoro`): local ONNX inference after model and voice files are available.
- **gTTS** (`gtts`): online speech; language and accent options are configured separately.
- **Gemini** (`gemini`): provider speech using the configured API key, model and voice.
- **Piper** (`piper`): local inference with the configured voice model.
- **Local** (`local`): macOS `say`, Windows SAPI, or `pyttsx3` on Linux/Raspberry Pi, subject to installed voices and dependencies.

Backend quality, availability and timing are not benchmarked by the revision tests. Automatic fallback can change the active voice; if synthesis fails, inspect logs for simulated pacing. For a study, choose an available backend/voice explicitly and record the backend that actually produced each condition. Simulated pacing does not constitute successful speech output.

## Timing and interruption

The engine prepares sentence audio before playback, with at most two synthesis calls active. It estimates the active speech interval from audio levels and allocates word durations using word-length weights. Character offsets from tags select positions on this approximate timeline. This is a heuristic, not forced alignment or measured word-onset accuracy.

Lip movement follows a gated and smoothed RMS audio envelope. Parameters under `speech.mouth` control that mapping. Named actions are dispatched against the playback clock near estimated word positions; their acoustic and physical alignment has not been measured.

An interruption request can stop playback near an estimated word end, suppress later markers and skip remaining sentences. This does not guarantee a phoneme-perfect cutoff and does not necessarily cancel an already dispatched movement. Speech interruption is separate from motor control and is not a physical emergency stop. The response stream drains before the next turn; the audio that triggered an interruption is discarded, so recognition needs a fresh speech onset.

See [validation](validation.md) for synthetic timing and interruption checks and their limits, and [virtual studies](virtual_studies.md) for recording actual audible/visible output.

## Behavior modules

`obot.robot.behaviors.BehaviorManager` runs ambient gestures depending on what the robot is doing (`idle` / `listening` / `speaking`):

| Module | When | What |
|---|---|---|
| `auto_blink` | always | periodic blinks, occasional double blink |
| `listening_nod` | while the user talks | small attentive nods ("mm-hm") |
| `speaking_sway` | while the bot talks | subtle head/eye drift so it never freezes |
| `idle_wander` | idle | eyes (sometimes head) wander and linger |

Each module has `enabled`, `min_interval_s`, `max_interval_s`, `intensity` in `config.json → behaviors`. Adding a new module is one entry in `default_modules()`.
