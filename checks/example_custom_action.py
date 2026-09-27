"""Add an action label using the existing engine; console output only.

Requires the supplied engine and its console dependencies on PYTHONPATH.
Run: PYTHONPATH=/path/to/engine/src python example_custom_action.py
"""

import asyncio

from obot.core.orchestrator import RobotPipeline
from obot.llm.client import ScriptedLLMClient
from obot.robot.actions import default_action_registry
from obot.robot.controller import ConsoleObotController, ObotController


async def main() -> None:
    registry = default_action_registry()

    @registry.register("Acknowledge")
    async def acknowledge(controller: ObotController) -> None:
        await controller.nod()
        await controller.blink()

    controller = ConsoleObotController()
    pipeline = RobotPipeline(
        llm_client=ScriptedLLMClient("[Acknowledge] I will explain the next step."),
        controller=controller,
        action_registry=registry,
    )
    try:
        await pipeline.run("Explain the next step.")
    finally:
        controller.close()


if __name__ == "__main__":
    asyncio.run(main())
