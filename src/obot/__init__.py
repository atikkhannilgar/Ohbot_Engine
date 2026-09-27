"""The Obot voice pipeline: LLM streaming, speech, and robot motion."""

from .core.orchestrator import RobotPipeline
from .core.processor import StreamProcessor
from .llm.client import ScriptedLLMClient
from .robot.actions import default_action_registry
from .robot.controller import (
    ConsoleObotController,
    HardwareObotController,
    ObotController,
)

__all__ = [
    "ConsoleObotController",
    "HardwareObotController",
    "ObotController",
    "RobotPipeline",
    "ScriptedLLMClient",
    "StreamProcessor",
    "default_action_registry",
]
