"""Per-emotion default motor poses.

While an emotion is active, the mixer (:meth:`AnimatedObotController._mixer_loop`
in ``controller.py``) adds these deltas to :data:`joints.REST_POSITION` every
tick instead of settling back to plain neutral. Ambient behaviors (blinks, sway,
idle wander) and live speech visemes simply ride on top of this shifted
baseline, so a sad face still blinks and talks normally  just around a lower
mouth and downward gaze instead of dead-center rest.

Each pose is a servo-position delta (same 0..10 units as everything else,
0 = no change from rest) keyed by joint id. These values are the place to
fine-tune expressions against real hardware or the sim face.

:data:`NEUTRAL` is special: it is not just "the pose while idle", it is a
standing override of what "rest" means per joint, applied underneath *every*
emotion via :func:`combined_pose`. If a joint's true physical rest isn't
:data:`joints.REST_POSITION` (e.g. hardware where LidBlink rests fully open
at :data:`joints.LIDBLINK_OPEN`), correct it once in NEUTRAL and every emotion
shifts with it.
"""

from __future__ import annotations

from . import joints

# joint_id -> delta from REST_POSITION.
EmotionPose = dict[int, float]


def _lid_from_open(delta_from_open: float) -> float:
    """LidBlink emotion delta so NEUTRAL open + this lands at LIDBLINK_OPEN + delta.

    Emotion poses are merged on top of :data:`NEUTRAL`, which already lifts the lids
    from :data:`joints.REST_POSITION` to :data:`joints.LIDBLINK_OPEN`. Pass the
    change you want *from that open rest* (e.g. ``-2`` = droop two units), not a
    delta from ``REST_POSITION`` and not an absolute 0..10 position.
    """
    return delta_from_open


# No bias for most joints. LidBlink open-rest is LIDBLINK_OPEN (7), while the
# engine REST_POSITION is 5 — bias the difference so every emotion sits on open lids.
NEUTRAL: EmotionPose = {
    joints.TOPLIP: 0.0,
    joints.BOTTOMLIP: 0.0,
    joints.EYETILT: 0.0,
    joints.HEADNOD: 0.0,
    joints.LIDBLINK: joints.LIDBLINK_OPEN - joints.REST_POSITION,
}

# Smile, bright upward gaze, head held slightly up.
HAPPY: EmotionPose = {
    joints.TOPLIP: -3.0,
    joints.BOTTOMLIP: 3.0,
    joints.EYETILT: 1.5,
    joints.HEADNOD: 0.5,
}

# Frown, eyes looking down, head hanging low.
SAD: EmotionPose = {
    joints.TOPLIP: 2.0,
    joints.BOTTOMLIP: -2.0,
    joints.EYETILT: -2.5,
    joints.HEADNOD: -1.5,
}

# Head cocked to one side, questioning upward glance, slightly pursed mouth.
CONFUSED: EmotionPose = {
    joints.HEADTURN: 1.5,
    joints.EYETILT: 0.5,
    joints.TOPLIP: -1.0,
}

# Tight downturned mouth, lowered gaze, head dropped  confrontational.
ANGRY: EmotionPose = {
    joints.TOPLIP: -2.0,
    joints.BOTTOMLIP: 1.0,
    joints.EYETILT: -1.0,
    joints.HEADNOD: -1.0,
}

# Heavy half-closed eyelids, drooping head, slack mouth.
EXHAUSTED: EmotionPose = {
    # Droop from open-rest 7 → ~5 (old -4 was calibrated for open-at-10 → 6).
    joints.LIDBLINK: _lid_from_open(-2.0),
    joints.HEADNOD: -2.0,
    joints.TOPLIP: -1.5,
    joints.BOTTOMLIP: -1.5,
}

# Mouth barely open.
WHISPERING: EmotionPose = {
    joints.TOPLIP: -0.5,
    joints.BOTTOMLIP: -0.5,
}

# Mouth wide open, head thrown back; lids stay at open-rest (old +2 under
# open-at-10 clamped to 10 and reopened the virtual/hardware mismatch).
SHOUTING: EmotionPose = {
    joints.TOPLIP: 4.0,
    joints.BOTTOMLIP: 4.0,
    joints.HEADNOD: 1.0,
    joints.LIDBLINK: _lid_from_open(0.0),
}

# Name -> pose, in the same order as the "Available Emotions" list in
# system_prompt.txt (Neutral first, as the GUI's "clear emotion" option). Both the
# LLM's (Emotion) markers and the GUI's manual control panel key into this by name.
EMOTIONS: dict[str, EmotionPose] = {
    "Neutral": NEUTRAL,
    "Happy": HAPPY,
    "Sad": SAD,
    "Confused": CONFUSED,
    "Angry": ANGRY,
    "Exhausted": EXHAUSTED,
    "Whispering": WHISPERING,
    "Shouting": SHOUTING,
}


def resolve(name: str) -> EmotionPose | None:
    """Look up a pose by name (case-insensitive).

    Returns None for an unrecognised name  callers still surface the raw name
    (e.g. an ``emotion`` event / transcript chip) even when it doesn't map to a
    pose, since the LLM's persona can name any emotion word.
    """
    if name in EMOTIONS:
        return EMOTIONS[name]
    lowered = name.lower()
    for key, pose in EMOTIONS.items():
        if key.lower() == lowered:
            return pose
    return None


def combined_pose(name: str) -> EmotionPose | None:
    """The pose actually handed to the mixer for ``name``.

    :data:`NEUTRAL`'s rest-position override plus the emotion's own expression
    on top, so recalibrating NEUTRAL shifts every emotion's baseline  not just
    the plain "Neutral" state. None for an unrecognised name (see :func:`resolve`).
    """
    pose = resolve(name)
    if pose is None:
        return None
    # Always copy NEUTRAL first so LidBlink open-rest (and any future rest
    # overrides) apply under every named emotion, including ones that also
    # touch LIDBLINK.
    merged = dict(NEUTRAL)
    if pose is NEUTRAL:
        return merged
    for joint_id, delta in pose.items():
        merged[joint_id] = merged.get(joint_id, 0.0) + delta
    return merged
