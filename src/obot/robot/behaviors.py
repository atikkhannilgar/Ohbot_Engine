"""Ambient behavior modules: things the robot does *around* the conversation.

The :class:`BehaviorManager` tracks what the robot is currently doing 
``idle``, ``listening`` (a human is talking to it) or ``speaking``  and runs
small background gestures that match the moment:

* **auto_blink**  periodic blinks in every state (replaces the old blink thread),
* **listening_nod**  slow attentive nods while being spoken to,
* **speaking_sway**  subtle head/eye drift while talking, so the robot doesn't
  freeze like a statue between scripted gestures,
* **idle_wander**  occasional eye wandering when nothing is happening.

Adding a module = appending one :class:`BehaviorModule` in
:func:`default_modules`. All timings/strengths are tunable via the
``behaviors`` section of config.json.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from . import joints

if TYPE_CHECKING:
    from .controller import ObotController


class BotState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    SPEAKING = "speaking"


@dataclass
class ModuleSettings:
    enabled: bool = True
    min_interval_s: float = 2.0
    max_interval_s: float = 6.0
    intensity: float = 1.0  # scales gesture size, 0..~1.5

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, base: "ModuleSettings") -> "ModuleSettings":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", base.enabled)),
            min_interval_s=float(data.get("min_interval_s", base.min_interval_s)),
            max_interval_s=float(data.get("max_interval_s", base.max_interval_s)),
            intensity=float(data.get("intensity", base.intensity)),
        )


@dataclass
class BehaviorSettings:
    auto_blink: ModuleSettings = field(
        default_factory=lambda: ModuleSettings(min_interval_s=2.0, max_interval_s=6.0)
    )
    listening_nod: ModuleSettings = field(
        default_factory=lambda: ModuleSettings(min_interval_s=2.5, max_interval_s=6.0, intensity=0.6)
    )
    speaking_sway: ModuleSettings = field(
        default_factory=lambda: ModuleSettings(min_interval_s=1.2, max_interval_s=2.8, intensity=0.6)
    )
    idle_wander: ModuleSettings = field(
        default_factory=lambda: ModuleSettings(min_interval_s=3.0, max_interval_s=8.0)
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "BehaviorSettings":
        data = data or {}
        defaults = cls()
        return cls(
            auto_blink=ModuleSettings.from_dict(data.get("auto_blink"), defaults.auto_blink),
            listening_nod=ModuleSettings.from_dict(data.get("listening_nod"), defaults.listening_nod),
            speaking_sway=ModuleSettings.from_dict(data.get("speaking_sway"), defaults.speaking_sway),
            idle_wander=ModuleSettings.from_dict(data.get("idle_wander"), defaults.idle_wander),
        )

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


@dataclass
class BehaviorModule:
    name: str
    settings: ModuleSettings
    states: frozenset[BotState]
    fire: Callable[["ObotController", float], Awaitable[None]]  # (controller, intensity)
    # When the manager's state changes, modules not valid in the new state have
    # their timer re-rolled so e.g. a listening nod can start soon after the
    # user begins talking instead of inheriting a stale 6-second timer.
    next_due: float = 0.0


# -- gesture implementations -------------------------------------------------------------

async def _fire_blink(controller: "ObotController", intensity: float) -> None:
    del intensity
    # announce=False keeps ambient blinks off the console so they don't spam
    # the action log during pickers, typing, and interrupts.
    await controller.blink(announce=False)
    # Occasional quick double blink reads as much more lifelike than a metronome.
    if random.random() < 0.2:
        await asyncio.sleep(0.15)
        await controller.blink(announce=False)


async def _fire_listening_nod(controller: "ObotController", intensity: float) -> None:
    # Two gentle dips  an attentive "mm-hm", far smaller than the [Nod] action.
    dip = 1.2 * intensity
    for _ in range(2):
        if not controller.enqueue_offset(joints.HEADNOD, +dip, 0.22):
            return
        await asyncio.sleep(0.22)
        controller.enqueue_offset(joints.HEADNOD, -dip * 0.4, 0.25)
        await asyncio.sleep(0.28)


async def _fire_speaking_sway(controller: "ObotController", intensity: float) -> None:
    # A small drift on one or two joints, held briefly. Random sign/size so the
    # head keeps living without ever competing with scripted [Nod]/[LookLeft].
    duration = random.uniform(0.5, 1.1)
    choices = [
        (joints.HEADTURN, 1.4),
        (joints.HEADNOD, 1.0),
        (joints.EYETURN, 1.2),
    ]
    for joint_id, scale in random.sample(choices, k=random.randint(1, 2)):
        delta = random.uniform(0.3, 1.0) * scale * intensity * random.choice((-1.0, 1.0))
        if not controller.enqueue_offset(joint_id, delta, duration):
            return
    await asyncio.sleep(duration)


async def _fire_idle_wander(controller: "ObotController", intensity: float) -> None:
    # Eyes drift somewhere and linger; occasionally the head follows a little.
    hold = random.uniform(0.8, 2.0)
    x = random.uniform(-2.0, 2.0) * intensity
    y = random.uniform(-1.2, 1.2) * intensity
    if not controller.enqueue_offset(joints.EYETURN, x, hold):
        return
    controller.enqueue_offset(joints.EYETILT, y, hold)
    if random.random() < 0.35:
        controller.enqueue_offset(joints.HEADTURN, x * 0.4, hold)
    await asyncio.sleep(hold)


def default_modules(settings: BehaviorSettings) -> list[BehaviorModule]:
    every_state = frozenset({BotState.IDLE, BotState.LISTENING, BotState.SPEAKING})
    return [
        BehaviorModule("auto_blink", settings.auto_blink, every_state, _fire_blink),
        BehaviorModule(
            "listening_nod", settings.listening_nod, frozenset({BotState.LISTENING}), _fire_listening_nod
        ),
        BehaviorModule(
            "speaking_sway", settings.speaking_sway, frozenset({BotState.SPEAKING}), _fire_speaking_sway
        ),
        BehaviorModule(
            "idle_wander", settings.idle_wander, frozenset({BotState.IDLE}), _fire_idle_wander
        ),
    ]


class BehaviorManager:
    """Schedules ambient gestures based on what the robot is currently doing.

    ``set_speaking``/``set_listening`` may be called from any thread (the mic
    capture thread flips *listening*); the manager only reads the flags on the
    event loop, so plain attributes are safe.
    """

    _TICK_S = 0.15

    def __init__(
        self,
        controller: "ObotController",
        settings: BehaviorSettings | None = None,
        modules: list[BehaviorModule] | None = None,
    ) -> None:
        self.controller = controller
        self.settings = settings or BehaviorSettings()
        self.modules = modules if modules is not None else default_modules(self.settings)
        self._speaking = False
        self._listening = False
        self._task: asyncio.Task | None = None
        self._fires: set[asyncio.Task] = set()

    # -- state -------------------------------------------------------------------------

    @property
    def state(self) -> BotState:
        if self._speaking:
            return BotState.SPEAKING
        if self._listening:
            return BotState.LISTENING
        return BotState.IDLE

    def set_speaking(self, speaking: bool) -> None:
        self._speaking = speaking

    def set_listening(self, listening: bool) -> None:
        self._listening = listening

    # -- lifecycle ---------------------------------------------------------------------

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        for fire in list(self._fires):
            fire.cancel()
        self._fires.clear()

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        last_state = self.state
        for module in self.modules:
            module.next_due = loop.time() + self._roll(module)

        while True:
            await asyncio.sleep(self._TICK_S)
            now = loop.time()
            state = self.state

            if state != last_state:
                # Entering a state re-rolls the timers of its modules with a short
                # first delay, so the matching behavior shows up promptly.
                for module in self.modules:
                    if state in module.states and last_state not in module.states:
                        module.next_due = now + self._roll(module) * 0.4
                last_state = state

            for module in self.modules:
                if not module.settings.enabled or state not in module.states:
                    continue
                if now < module.next_due:
                    continue
                module.next_due = now + self._roll(module)
                task = asyncio.create_task(self._fire_safely(module))
                self._fires.add(task)
                task.add_done_callback(self._fires.discard)

    async def _fire_safely(self, module: BehaviorModule) -> None:
        try:
            await module.fire(self.controller, module.settings.intensity)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - ambient motion must never kill the app
            print(f"[behavior] {module.name} failed: {exc}")

    @staticmethod
    def _roll(module: BehaviorModule) -> float:
        lo = max(0.2, module.settings.min_interval_s)
        hi = max(lo, module.settings.max_interval_s)
        return random.uniform(lo, hi)
