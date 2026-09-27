from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeAlias

from .controller import ObotController

ActionHandler: TypeAlias = Callable[[ObotController], Awaitable[None] | None]


class ActionRegistry:
    """Maps action tags to robot motion functions. Lookup is case-insensitive."""

    # Case insensitive lookup matters because the LLM often writes [Nod] (PascalCase)
    # while older scripted demos use [nod] (lowercase). Both should resolve.

    def __init__(self) -> None:
        self._handlers: dict[str, ActionHandler] = {}

    def register(self, name: str) -> Callable[[ActionHandler], ActionHandler]:
        def decorator(handler: ActionHandler) -> ActionHandler:
            self._handlers[name.lower()] = handler
            return handler

        return decorator

    async def execute(self, name: str, controller: ObotController) -> None:
        handler = self._handlers.get(name.lower())
        if handler is None:
            print(f"[action] unknown: {name}")
            return

        result = handler(controller)
        if result is not None:
            await result


def default_action_registry() -> ActionRegistry:
    registry = ActionRegistry()

    @registry.register("nod")
    async def _nod(controller: ObotController) -> None:
        await controller.nod()

    @registry.register("lookleft")
    async def _look_left(controller: ObotController) -> None:
        await controller.look_left()

    @registry.register("lookright")
    async def _look_right(controller: ObotController) -> None:
        await controller.look_right()

    @registry.register("blink")
    async def _blink(controller: ObotController) -> None:
        await controller.blink()

    @registry.register("wink")
    async def _wink(controller: ObotController) -> None:
        await controller.wink()

    @registry.register("shakehead")
    async def _shake_head(controller: ObotController) -> None:
        await controller.shake_head()

    # snake_case aliases so existing pipeline code that calls "look_left" still resolves
    # to the same handler as the LookLeft tag emitted by the LLM.
    registry._handlers["look_left"] = registry._handlers["lookleft"]
    registry._handlers["look_right"] = registry._handlers["lookright"]
    registry._handlers["shake_head"] = registry._handlers["shakehead"]

    return registry
