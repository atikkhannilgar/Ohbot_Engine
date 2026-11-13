# Response modes, prompt and model compatibility

Scripted mode executes the supplied annotated response. LLM mode treats the typed or transcribed input as a user message and executes the model's newly generated response. A tag in an LLM user message is not a guaranteed robot command; only tags in the generated response are parsed for execution.

## Available model evidence

| Model/provider | Evidence | Limit |
| --- | --- | --- |
| `qwen3.5:9b` through Ollama | Identifier shown in the supplied GUI/physical demonstration. | Qualitative demonstration, not a repeated tag-compliance benchmark. |
| `qwen3.5:1.8b` through Ollama | R1 reported a successful virtual trial with gestures and expressions. | Reviewer observation, not a new author-run test. |
| `llama3.2` through Ollama | R1 reported expressions without gestures. | Raw replies are unavailable; missing action tags are a hypothesis, not a confirmed diagnosis. |
| Gemini | Implemented dialogue provider. | No exact dialogue model or new live provider run is established by this revision's checks. |

No minimum model size, validated model-family requirement or complete supported-model list has been established. Record the exact identifier, local model digest where available, generation settings and prompt. Review generated responses before participant use. Hardware-free checks do not establish model compatibility.

## Exact supplied system prompt

The client reads the root [system_prompt.txt](../system_prompt.txt). The text below reproduces the supplied prompt unchanged. Its hash is recorded in [the validation manifest](../revision_support/validation_manifest.json). If you edit the prompt for an experiment, retain your exact version and update any documentation copies.

```text
You are an OhBot robot taking part in a researcher-supervised conversation.
Use short, clear spoken English. Answer the user honestly and stay on topic.

The program speaks your words and interprets the following control labels.
Use square brackets for supported actions: [Nod], [Blink], [LookLeft], [LookRight], [ShakeHead], [Wink].
Use round brackets for expression poses: (Neutral), (Happy), (Sad), (Confused), (Angry), (Exhausted), (Whispering), (Shouting).
Place an action label immediately before the words it should accompany.
An expression label changes the pose until another expression is selected.
These labels request predefined behaviors; do not invent label names or motor coordinates.
Use labels sparingly when they fit the reply. Use ordinary punctuation for sentences.
Do not add Markdown, headings, stage directions, or other bracketed text.
Example output: (Happy) Let us try [Nod] the next step.
If told that playback was interrupted, respond to the next user turn without assuming all generated words were heard.
```

The prompt asks for labels sparingly when appropriate; a valid reply can contain no gesture. Forcing gestures into every reply would change the experimental prompting strategy, so the revision does not silently alter that behavior.

## If expressions appear but gestures do not

1. Inspect the raw model response. Is a supported action tag such as `[Nod]` present? An expression such as `(Happy)` does not imply a head gesture. Square brackets request actions; round brackets request expression poses.
2. Inspect parsed action events. Unknown action names are logged and skipped. A tag-only response without spoken text is discarded. Use a scripted tagged sentence to distinguish model omission from execution behavior.
3. Release manual joint overrides and disable learned/background movement while isolating a named action. Predicted joint positions and manual targets can take priority over an action.
4. Confirm the selected controller and actual speech output. Record model, prompt, raw response, parsed tags, configuration and visible/audible results.

The recorder preserves raw reply chunks and parsed events for typed sessions; see the root README for commands. It does not capture the desktop UI. Use scripted responses when fixed text and behavior annotations are required across conditions.
