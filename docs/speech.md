# Speech Engine

`ohbot.say()` is gone. Speech now runs through `obot.speech.SpeechEngine`.

## Voices

Pick one with `speech.tts.engine`, or leave it on `"auto"` to chain through the best available:

- **Edge** (`edge`): Microsoft's neural voices via `edge-tts`. Online, free, no API key, and the most natural-sounding of the free options (Azure quality: `en-GB-SoniaNeural`, `en-US-AriaNeural`, ...). Unofficial endpoint, needs internet.
- **Kokoro** (`kokoro`): a small open neural model running fully offline via ONNX. The best local voice, noticeably better than Piper, and faster than real time on CPU. Model (~330 MB) and voices auto-download to `ohbotData/kokoro/` the first time you use it; bundles espeak-ng, so there's nothing to install system-side. British voices `bf_emma`/`bf_alice`, pace via `speed`.
- **gTTS** (`gtts`): Google Translate TTS. Online, free, no key, decent quality. The "voice" here is really the accent, set via `tld` (`co.uk`, `com`, `com.au`, ...).
- **Gemini** (`gemini`): very natural, but needs `gemini_api_key`, and the free tier only gives you about 3 requests a minute.
- **Piper** (`piper`): offline neural TTS, a solid fallback. Voice `en_GB-cori-high`, model auto-downloads to `ohbotData/piper/`. Pace via `length_scale`.
- **Basic local** (`local`): SAPI/espeak. Robotic, but dependency-free, and always there as a last resort.

The online voices (edge/gtts) come back as MP3 and get decoded to PCM through `miniaudio`. `"auto"` chains edge → kokoro → piper → local, so you get near-Azure quality when you're online and a solid offline voice when you're not; it basically never fully fails. A voice that's currently failing gets benched for `failure_cooldown_s` so it stops adding a timeout to every sentence.

## Features

- **Fast output.** The next sentence starts synthesizing while the current one is still playing, so the round-trip to the TTS engine hides behind playback instead of causing a stutter.
- **Interruption at word boundaries.** Barge-in and SPACE don't cut the audio off mid-phoneme. Playback finishes the word it's currently voicing (plus a small fade) and then goes quiet. Any remaining sentences get dropped, and the LLM is told on its next turn what was actually said and what wasn't.
- **Lip sync.** The mouth moves based on the real audio: an RMS envelope gets gated, curved and smoothed into lip positions. Every parameter (`gate`, `gamma`, `attack`, `release`, gains, fps, sync offset) lives in `config.json` under `speech.mouth`, and can be tuned live with sliders in the simulator.
- **Timed actions mid-sentence.** `[Nod]` written between two words fires exactly when that word gets spoken (character position mapped to a word timeline, mapped to the playback clock), not at some guessed fraction of the sentence.

## Behavior modules

`obot.robot.behaviors.BehaviorManager` runs ambient gestures depending on what the robot is doing (`idle` / `listening` / `speaking`):

| Module | When | What |
|---|---|---|
| `auto_blink` | always | periodic blinks, occasional double blink |
| `listening_nod` | while the user talks | small attentive nods ("mm-hm") |
| `speaking_sway` | while the bot talks | subtle head/eye drift so it never freezes |
| `idle_wander` | idle | eyes (sometimes head) wander and linger |

Each module has `enabled`, `min_interval_s`, `max_interval_s`, `intensity` in `config.json → behaviors`. Adding a new module is one entry in `default_modules()`.
