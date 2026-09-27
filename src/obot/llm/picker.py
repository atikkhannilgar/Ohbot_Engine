from __future__ import annotations

from .gemini import list_gemini_models
from .ollama import list_ollama_models


async def pick_gemini_model(api_key: str, recents: list[str]) -> str:
    models = await list_gemini_models(api_key)
    return _prompt_pick("Gemini", models, recents)


async def pick_ollama_model(base_url: str, recents: list[str]) -> str:
    models = await list_ollama_models(base_url)
    if not models:
        raise RuntimeError(
            "No models found on the Ollama server. Pull one with `ollama pull <model>` on the remote machine."
        )
    return _prompt_pick("Ollama", models, recents)


def _prompt_pick(label: str, all_models: list[str], recents: list[str]) -> str:
    # Recently used models are shown first and tagged (recent). A recent entry only
    # appears if the server still reports it as available; stale ones are dropped.
    available = set(all_models)
    ordered_recents = [m for m in recents if m in available]
    rest = [m for m in all_models if m not in ordered_recents]
    display = ordered_recents + rest

    print(f"\nAvailable {label} models:")
    for i, name in enumerate(display, start=1):
        tag = "  (recent)" if name in ordered_recents else ""
        print(f"  [{i}] {name}{tag}")

    while True:
        raw = input(f"Pick a {label} model (1-{len(display)}): ").strip()
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(display):
                return display[idx - 1]
        if raw in available:
            return raw
        print(f"Please enter a number 1-{len(display)} or a model name from the list.")
