# HRI studies with the virtual OhBot

Researchers can use the desktop's virtual OhBot for screen-based interaction studies without owning the physical robot. Participants can type, or use a configured speech-recognition path, hear responses and observe commanded facial/head movements. The same execution layer supports different speech backends, response models and expression strategies. These are proposed study workflows; this revision does not report a participant evaluation.

## Prepare the virtual session

1. Follow [installation](installation.md) with the desktop profile and any dependencies required by your selected speech backend.
2. Start the desktop and choose `scripted`, `virtual` and `muted` for an initial typed trial. Select an installed or available speech backend and voice.
3. Use the behavior settings in `examples/config.reference.json` to disable learned and background movement. Release manual joint overrides. Select a voice available on your system; the reference file's example voice is not portable to every platform.
4. Send `(Happy) Let us try [Nod] the next step.` Verify the displayed text, audible speech and visible movement. Confirm in logs that real synthesis succeeded; console output or simulated pacing does not validate audio.
5. Keep the participant display, audio level, microphone configuration and response settings consistent across conditions. Randomize/counterbalance condition order as appropriate to the study design.

`virtual` uses the desktop preview; `sim` opens the separate Tk representation. `console` prints events without speech or a participant-facing face. The command-line recorder's virtual controller does not open the desktop preview, so it is not a replacement for launching the participant-facing UI.

## Example comparisons

| Comparison | Change | Hold fixed or record |
| --- | --- | --- |
| Gesture presence | Script A: `Let us try [Nod] the next step.` Script B: `Let us try the next step.` | Speech text, backend, voice, expression, embodiment, and other movement sources. Reset expression state before each condition. |
| Speech model or voice | Select a different supported speech backend or voice. | Scripted text and tags, expression and embodiment. Record actual backend/voice and failures or fallback. Different speech duration also changes heuristic gesture timing. |
| LLM | Change the selected response model. | User inputs, exact system prompt, speech backend/voice and embodiment. Control conversation-history resets and record generation settings, raw responses and tags. Generated text and behavior may both change. |
| Expression strategy | Use `(Neutral)` versus `(Happy)` with identical speech, or alter a pose definition. | Dialogue, voice, gesture tags, other movement sources and embodiment. Expressions persist until changed; explicitly reset between trials. |

Possible outcomes include perceived speech naturalness, expression appropriateness, interaction quality or task responses. Record the exact stimuli and settings that produced each trial. Comparisons involving several simultaneous changes do not isolate a single causal factor.

## External emotion models

The software has supported expression tags and pose definitions, not a built-in selector for arbitrary emotion models. Pose offsets are defined in `src/obot/robot/emotions.py`. An external classifier or other emotion model needs an adapter that maps its output to the supported expression vocabulary and submits it with response text through the existing pipeline/interface. For example, an adapter could map a model's positive-affect category to `(Happy)` and an uncertain result to `(Neutral)`, followed by the same spoken sentence. Define and record that mapping and any thresholds before the study; these example mappings are not validated emotion semantics.

Standalone tags with no sentence are discarded by the text parser. Unknown expressions leave the current pose unchanged. When adding a new named pose or action, update the registration/lookup and the system prompt as needed. Whispering and Shouting tags change facial poses, not speech volume or prosody.

## Adding a custom action

```python
from obot.robot.actions import default_action_registry

registry = default_action_registry()

@registry.register("Acknowledge")
async def acknowledge(controller):
    await controller.nod()
    await controller.blink()
```

Pass `registry` to `RobotPipeline(..., action_registry=registry)` to enable `[Acknowledge]`. Add the name to `system_prompt.txt` if an LLM should request it. See [the model guide](model_compatibility.md) for the distinction between scripted response text and a user message to an LLM.

## Record and interpret outcomes

Keep the software revision, model identifier/digest, prompt, configuration, speech backend/voice, generated text/tags, condition order and study responses. `scripts/capture_demo.py` records typed scripted or model sessions and software events; it does not record desktop, microphone or participant responses. Pair it with an appropriate screen/audio recording when visible or audible output matters, subject to participant consent and provider data-processing requirements.

The virtual face displays requested joint positions, not physical dynamics or measured hardware feedback. Study findings concern that screen-based embodiment. Physical transfer, acoustic synchronization and physical stop latency need separate evaluation. Speech interruption is not a motor emergency stop.
