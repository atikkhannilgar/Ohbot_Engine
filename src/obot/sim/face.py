"""A tkinter rendering of the OhBot head, driven by the normal joint interface.

The window runs in its own thread (tkinter objects are only ever touched from
that thread); the controller calls :meth:`FaceWindow.set_motor` from anywhere
and the ~30 fps redraw loop picks the values up. With ``tuning=True`` a side
panel exposes every mouth-animation parameter as a live slider plus a save
button, which is the intended workflow for dialing in lip-sync without the
physical robot.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable

from ..robot import joints
from ..speech.config import MouthSettings

_BG = "#101418"
_HEAD = "#e8e4dc"
_HEAD_EDGE = "#b9b4a9"
_EYE_WHITE = "#ffffff"
_PUPIL = "#1b2733"
_LID = "#cfc9bd"
_MOUTH = "#5a1f24"
_LIP = "#8a3038"
_TEXT = "#9fb4c7"

# Max HEADTILT swing, each direction, at position 0/10.
_HEADTILT_DEG = 22.0


def _rotate_pt(px: float, py: float, ox: float, oy: float, angle: float) -> tuple[float, float]:
    """Rotate (px, py) by ``angle`` radians about pivot (ox, oy)."""
    if not angle:
        return px, py
    s, c = math.sin(angle), math.cos(angle)
    dx, dy = px - ox, py - oy
    return ox + dx * c - dy * s, oy + dx * s + dy * c


def _ellipse_points(
    cx: float, cy: float, rx: float, ry: float, angle: float, ox: float, oy: float, n: int = 28
) -> list[float]:
    """Flat [x0, y0, x1, y1, ...] boundary of an ellipse (center cx,cy, radii rx,ry),
    rotated by ``angle`` about pivot (ox, oy) -- used to draw a rolled HEADTILT as a
    polygon, since tkinter's oval/rectangle primitives can't rotate on their own."""
    pts: list[float] = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x = cx + rx * math.cos(t)
        y = cy + ry * math.sin(t)
        pts.extend(_rotate_pt(x, y, ox, oy, angle))
    return pts


# Sliders shown in the tuning panel: (attribute, label, from, to, resolution)
_TUNING_FIELDS = [
    ("top_gain", "top lip gain", 0.0, 5.0, 0.1),
    ("bottom_gain", "bottom lip gain", 0.0, 5.0, 0.1),
    ("gate", "noise gate", 0.0, 0.3, 0.01),
    ("gamma", "gamma curve", 0.2, 1.5, 0.05),
    ("attack", "attack (open speed)", 0.05, 1.0, 0.05),
    ("release", "release (close speed)", 0.05, 1.0, 0.05),
    ("fps", "mouth updates /s", 10, 40, 1),
    ("sync_offset_s", "lip sync offset s", -0.3, 0.3, 0.01),
]


class FaceWindow:
    """Thread-owning tkinter window that draws the robot face.

    ``mouth_settings`` (optional) is mutated live by the tuning sliders; pass
    the same object the SpeechEngine reads so changes are audible/visible on
    the next sentence. ``on_save`` is called (from the tk thread) when the
    save button is pressed.
    """

    def __init__(
        self,
        mouth_settings: MouthSettings | None = None,
        on_save: Callable[[], None] | None = None,
        tuning: bool = False,
        title: str = "OhBot Simulator",
    ) -> None:
        self._mouth_settings = mouth_settings
        self._on_save = on_save
        self._tuning = tuning and mouth_settings is not None
        self._title = title

        self._lock = threading.Lock()
        self._positions: dict[int, float] = {j: joints.REST_POSITION for j in joints.ALL_JOINTS}
        self._status = ""
        self._closed = threading.Event()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="obot-sim-face")
        self._thread.start()
        # Wait briefly so callers can rely on the window existing; if tkinter is
        # unavailable the thread sets _closed and we raise.
        self._ready.wait(timeout=5.0)
        if self._closed.is_set():
            raise RuntimeError("could not open the simulator window (tkinter unavailable?)")

    # -- controller-facing API ----------------------------------------------------------

    def set_motor(self, joint_id: int, position: float) -> None:
        if joint_id not in self._positions:
            return
        with self._lock:
            self._positions[joint_id] = max(0.0, min(10.0, float(position)))

    def set_status(self, text: str) -> None:
        with self._lock:
            self._status = text

    @property
    def is_open(self) -> bool:
        return not self._closed.is_set()

    def close(self) -> None:
        self._closed.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    # -- tk thread ----------------------------------------------------------------------

    def _run(self) -> None:
        try:
            # All tkinter objects live and die inside _tk_main's frame. The
            # explicit collect afterwards runs ON THIS THREAD, so the Tcl
            # interpreter (kept alive by the redraw-closure/after-callback cycle)
            # is finalised in its home thread. Letting the main thread's exit-GC
            # free it instead aborts the process with
            # "Tcl_AsyncDelete: async handler deleted by the wrong thread".
            self._tk_main()
        finally:
            self._closed.set()
            self._ready.set()
            import gc

            gc.collect()

    def _tk_main(self) -> None:
        try:
            import tkinter as tk
        except ImportError:
            self._closed.set()
            self._ready.set()
            return

        # The window lives on this thread. Without this, tkinter stashes the Tk
        # instance in a module-level default root, which the *main* thread then
        # finalises at interpreter exit  Tcl aborts the whole process with
        # "Tcl_AsyncDelete: async handler deleted by the wrong thread".
        try:
            tk.NoDefaultRoot()
        except Exception:
            pass

        root = tk.Tk()
        root.title(self._title)
        root.configure(bg=_BG)
        root.protocol("WM_DELETE_WINDOW", self._closed.set)

        canvas = tk.Canvas(root, width=400, height=470, bg=_BG, highlightthickness=0)
        canvas.pack(side="left", padx=4, pady=4)

        if self._tuning:
            self._build_tuning_panel(tk, root)

        self._ready.set()

        def redraw() -> None:
            if self._closed.is_set():
                try:
                    root.destroy()
                except tk.TclError:
                    pass
                return
            with self._lock:
                v = dict(self._positions)
                status = self._status
            self._draw(canvas, v, status)
            root.after(33, redraw)

        redraw()
        try:
            root.mainloop()
        finally:
            self._closed.set()
            # Destroy from THIS thread so no live widget outlives the loop.
            try:
                root.destroy()
            except tk.TclError:
                pass

    def _build_tuning_panel(self, tk, root) -> None:
        panel = tk.Frame(root, bg=_BG)
        panel.pack(side="right", fill="y", padx=6, pady=6)
        tk.Label(
            panel, text="Mouth tuning", bg=_BG, fg=_TEXT, font=("Segoe UI", 11, "bold")
        ).pack(anchor="w")

        settings = self._mouth_settings
        for attr, label, lo, hi, res in _TUNING_FIELDS:
            def _apply(val: str, attr: str = attr) -> None:
                setattr(settings, attr, float(val))

            scale = tk.Scale(
                panel,
                label=label,
                from_=lo,
                to=hi,
                resolution=res,
                orient="horizontal",
                length=190,
                bg=_BG,
                fg=_TEXT,
                troughcolor="#2a3440",
                highlightthickness=0,
                command=_apply,
            )
            scale.set(getattr(settings, attr))
            scale.pack(anchor="w", pady=1)

        tk.Label(
            panel,
            text="gate/gamma/attack/release/fps\napply from the next sentence.",
            bg=_BG, fg="#5c6f80", font=("Segoe UI", 8), justify="left",
        ).pack(anchor="w", pady=(4, 2))

        if self._on_save is not None:
            tk.Button(
                panel, text="Save to config.json", command=self._on_save,
                bg="#2a3440", fg=_TEXT, activebackground="#3a4855", relief="flat",
            ).pack(anchor="w", pady=6)

    # -- drawing ------------------------------------------------------------------------

    def _draw(self, canvas, v: dict[int, float], status: str) -> None:
        canvas.delete("all")

        # Head pose: HEADTURN pans the whole face, HEADNOD pitches it, HEADTILT
        # rolls it side to side (10 = tilted toward the robot's right). Roll is
        # applied as a rotation about the head center to every shape below.
        cx = 200 + (v[joints.HEADTURN] - 5.0) / 5.0 * 30.0
        cy = 205 - (v[joints.HEADNOD] - 5.0) / 5.0 * 24.0
        roll = math.radians((v[joints.HEADTILT] - 5.0) / 5.0 * _HEADTILT_DEG)

        # Base / neck (fixed to the desk, not the head)
        canvas.create_rectangle(150, 392, 250, 470, fill="#20262d", outline="")
        canvas.create_rectangle(120, 440, 280, 470, fill="#2a323b", outline="")

        # Head shell -- a polygon (not create_oval) so it can actually rotate.
        canvas.create_polygon(
            *_ellipse_points(cx, cy, 115, 135, roll, cx, cy),
            fill=_HEAD, outline=_HEAD_EDGE, width=3, smooth=True,
        )

        # Eyes
        eye_r = 32.0
        pupil_dx = -(v[joints.EYETURN] - 5.0) / 5.0 * 14.0
        pupil_dy = -(v[joints.EYETILT] - 5.0) / 5.0 * 10.0
        pupil_dx, pupil_dy = _rotate_pt(pupil_dx, pupil_dy, 0.0, 0.0, roll)
        # Lids close from the top on the true 0..10 servo scale (10 = fully lifted,
        # 0 = closed). Open-rest is commanded at LIDBLINK_OPEN (7), so the preview
        # matches the hardware's partial-open look rather than treating 7 as max open.
        lid_frac = max(0.0, min(1.0, (10.0 - v[joints.LIDBLINK]) / 10.0))

        for ex0, ey0 in ((cx - 50, cy - 42), (cx + 50, cy - 42)):
            ex, ey = _rotate_pt(ex0, ey0, cx, cy, roll)
            canvas.create_oval(ex - eye_r, ey - eye_r, ex + eye_r, ey + eye_r,
                               fill=_EYE_WHITE, outline=_HEAD_EDGE, width=2)
            px, py = ex + pupil_dx, ey + pupil_dy
            canvas.create_oval(px - 11, py - 11, px + 11, py + 11, fill=_PUPIL, outline="")
            canvas.create_oval(px - 4, py - 6, px + 1, py - 1, fill="#dfe8ef", outline="")
            if lid_frac >= 0.98:
                # Fully shut: paint the whole eye as lid (still a circle -- rotation
                # only moves its center, so create_oval is fine here).
                canvas.create_oval(ex - eye_r, ey - eye_r, ex + eye_r, ey + eye_r,
                                   fill=_LID, outline=_HEAD_EDGE)
            elif lid_frac > 0.01:
                # Lid: a cover sliding down over the eye from the top, rolled with
                # the head -- built from the eye's own unrotated corners so it stays
                # square to the eye rather than the screen.
                lid_y0 = ey0 - eye_r + lid_frac * 2 * eye_r
                corners = (
                    (ex0 - eye_r - 1, ey0 - eye_r - 1),
                    (ex0 + eye_r + 1, ey0 - eye_r - 1),
                    (ex0 + eye_r + 1, lid_y0),
                    (ex0 - eye_r - 1, lid_y0),
                )
                flat = [c for corner in corners for c in _rotate_pt(*corner, cx, cy, roll)]
                canvas.create_polygon(*flat, fill=_LID, outline="")
            canvas.create_oval(ex - eye_r, ey - eye_r, ex + eye_r, ey + eye_r,
                               outline=_HEAD_EDGE, width=2)

        # Mouth: rest (5,5) = closed line; higher = open (viseme), lower = frown-ish.
        mouth_y = cy + 68
        half_w = 56.0
        y_top = mouth_y - (v[joints.TOPLIP] - 5.0) * 6.0
        y_bot = mouth_y + (v[joints.BOTTOMLIP] - 5.0) * 6.0
        if y_bot - y_top > 2.0:
            canvas.create_polygon(
                *_ellipse_points(cx, (y_top + y_bot) / 2.0, half_w, (y_bot - y_top) / 2.0,
                                 roll, cx, cy),
                fill=_MOUTH, outline="",
            )
            top_pts = [c for pt in ((cx - half_w, y_top + 1), (cx + half_w, y_top + 1))
                       for c in _rotate_pt(*pt, cx, cy, roll)]
            canvas.create_line(*top_pts, fill=_LIP, width=5, smooth=True)
            bot_pts = [c for pt in ((cx - half_w, y_bot - 1), (cx + half_w, y_bot - 1))
                       for c in _rotate_pt(*pt, cx, cy, roll)]
            canvas.create_line(*bot_pts, fill=_LIP, width=6, smooth=True)
        else:
            # Closed: one line whose slight bend hints at the emotion offsets
            # (lips pushed up = smile, pushed down = frown).
            bend = (v[joints.TOPLIP] + v[joints.BOTTOMLIP]) / 2.0 - 5.0
            mid_y = (y_top + y_bot) / 2.0
            pts = ((cx - half_w, mid_y), (cx, mid_y + bend * 4.0), (cx + half_w, mid_y))
            flat = [c for pt in pts for c in _rotate_pt(*pt, cx, cy, roll)]
            canvas.create_line(*flat, fill=_LIP, width=6, smooth=True)

        # Joint readout
        for i, j in enumerate(joints.ALL_JOINTS):
            canvas.create_text(
                8, 10 + i * 15, anchor="w", fill=_TEXT, font=("Consolas", 9),
                text=f"{joints.JOINT_NAMES[j]:<10}{v[j]:5.2f}",
            )
        if status:
            canvas.create_text(200, 458, anchor="s", fill=_TEXT, font=("Segoe UI", 9),
                               text=status[:60])
