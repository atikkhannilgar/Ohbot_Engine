"""Servo/joint IDs shared by the hardware controller and the digital simulator.

Values match the ohbot library's motor constants, so a joint id can be passed
straight to ``ohbot.move``. Positions are 0..10 with 5 = neutral/rest.
"""

from __future__ import annotations

HEADNOD = 0
HEADTURN = 1
EYETURN = 2
LIDBLINK = 3
TOPLIP = 4
BOTTOMLIP = 5
EYETILT = 6
# Motor 7 ("HeadRoll") is calibrated in MotorDefinitionsv21.omd on every stock
# Ohbot build, but is only physically wired on units with the 8th servo fitted
# (always present on Picoh). Harmless no-op on units without that servo.
HEADTILT = 7

ALL_JOINTS = (HEADNOD, HEADTURN, EYETURN, LIDBLINK, TOPLIP, BOTTOMLIP, EYETILT, HEADTILT)

# Joints that must snap rather than glide: lips during speech and eyelids for blinks.
FAST_JOINTS = frozenset({LIDBLINK, TOPLIP, BOTTOMLIP})

JOINT_NAMES = {
    HEADNOD: "HeadNod",
    HEADTURN: "HeadTurn",
    EYETURN: "EyeTurn",
    LIDBLINK: "LidBlink",
    TOPLIP: "TopLip",
    BOTTOMLIP: "BottomLip",
    EYETILT: "EyeTilt",
    HEADTILT: "HeadTilt",
}

NAME_TO_JOINT = {name: joint_id for joint_id, name in JOINT_NAMES.items()}

REST_POSITION = 5.0

# Open-eye LidBlink on this OhBot build. Stock OMD RestPosition is often 10, but
# the physical lids here rest fully open at 7 — virtual and hardware both use this.
LIDBLINK_OPEN = 7.0


def resolve(joint: int | str) -> int:
    """Resolve a joint id or name (as sent over the wire by the GUI) to a canonical id."""
    if isinstance(joint, str):
        try:
            return NAME_TO_JOINT[joint]
        except KeyError:
            raise ValueError(f"unknown joint '{joint}'") from None
    joint_id = int(joint)
    if joint_id not in ALL_JOINTS:
        raise ValueError(f"unknown joint id {joint_id}")
    return joint_id
