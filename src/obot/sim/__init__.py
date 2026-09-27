"""Digital OhBot: a tkinter face window driven by the same controller pipeline.

Run standalone with ``python -m obot.sim`` (type sentences, watch the face,
tune the mouth), or pass ``--sim`` to ``python -m obot`` to run the full LLM
pipeline against the simulated robot.
"""

from .face import FaceWindow

__all__ = ["FaceWindow"]
