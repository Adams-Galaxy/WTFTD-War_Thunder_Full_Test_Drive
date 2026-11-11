"""The overlay on Linux: what alarms.run_overlay does on Windows, in four X11 windows (x11.Layer) painted by cairo
(cairopaint): the HUD, the text blocks, the minimap and the glow. Keys and mouse buttons come from X, joystick buttons
from /dev/input. It needs an X display and a compositor (see-through windows): a Wayland session gives both through
XWayland, though its compositor may keep a full-screen game above every other window (overlay_note says so)."""
from __future__ import annotations

import os
import sys
import time

from . import alarms, cairopaint, x11

KEY_NAMES = ("hotkey", "logKey", "muteKey", "hudKey", "holdKey", "sheetKey", "profileKey")


def note() -> str | None:
    """What may keep the overlay off the screen here: "x11" (no X display), "compositor" (none: its windows would be
    black), "wayland" (a Wayland session: a full-screen game may stay above it); None where nothing is known against it."""
    if not sys.platform.startswith("linux"):
        return None
    if not x11.display():
        return "x11"
    if not x11.composited():
        return "compositor"
    return "wayland" if os.environ.get("WAYLAND_DISPLAY") else None


def run(watch):
    """Runs in its own thread until watch stops, as run_overlay does."""
    d = layers = painter = None
    try:
        problem = note()
        if problem in ("x11", "compositor") or not cairopaint.available():
            raise OSError({"x11": "no X display", "compositor": "no compositor, its see-through windows would show black"}.get(problem, "no cairo"))
        painter, d = cairopaint.Painter(), x11.open_display()
        hud, text, mapw, glow = layers = [x11.Layer(d, f"WTFTD {name}") for name in ("HUD", "text", "minimap", "glow")]
        drawn, map_drawn, text_drawn, painted, shown_text, raised = None, None, None, None, False, 0.0
        origin, keys = (x11.screen_box() or (0, 0))[:2], {"now": set(), "before": set()}
        while not watch.stopping.is_set():
            cfg, lines, shapes = watch.shown_cfg(), watch.display, watch.hud_frame()
            frame, lit, size = watch.map_frame(), watch.lit(), alarms.screen()
            state = cfg, shapes, lit if any(s[-1] for s in shapes) else None
            if state != drawn:
                drawn = state
                painter.paint_hud(hud, cfg, shapes, lit, size, origin)
            clocks = sorted({p[2] for x in lines for p in x[5] if len(p) > 2 and p[2]}, key=str)  # the flashing parts' rhythms
            words = cfg, lines, tuple(watch.lit(c) for c in clocks)
            if words != text_drawn:
                text_drawn = words
                shown_text = bool(lines and painter.paint_text(text, cfg, lines, watch.lit, origin))
            if frame and (frame, cfg["mapOpacity"]) != map_drawn:
                map_drawn = frame, cfg["mapOpacity"]
                painter.load(*frame["image"])
                painter.paint(mapw, frame, cfg["mapOpacity"] / 100, origin)
            used = [k for name in KEY_NAMES for k in cfg[name]]
            keys["before"], keys["now"] = keys["now"], x11.held([k for k in used if k < alarms.JOY]) | \
                alarms.joy_buttons({(k - alarms.JOY) // 32 for k in used if k >= alarms.JOY})
            down = keys["now"].__contains__

            def pressed(combo: list) -> bool:
                """Its last key pressed since the last look, the others held."""
                return bool(combo and combo[-1] in keys["now"] - keys["before"] and alarms.game_focused() and all(map(down, combo[:-1])))

            if pressed(cfg["profileKey"]):
                watch.next_profile()
            watch.sheet = bool(cfg["sheetKey"]) and all(map(down, cfg["sheetKey"]))
            if pressed(cfg["hotkey"]):
                watch.hidden = not watch.hidden
            if pressed(cfg["logKey"]):
                watch.set_log(not watch.log)
            if pressed(cfg["muteKey"]):
                watch.muted = not watch.muted
            if pressed(cfg["hudKey"]):
                watch.hud_place = "outside" if watch.hud_place == "cockpit" else "cockpit"
            held = cfg["holdKey"] and all(map(down, cfg["holdKey"]))
            on_game = (cfg["show"] and not watch.hidden and not held and alarms.game_focused()) or watch.trial
            hud.show(shapes and (watch.preview or on_game))
            text.show(shown_text and (watch.preview or on_game))
            mapw.show(frame and (watch.preview or on_game))
            spec = watch.glow if watch.trial or not watch.preview else alarms.first_glow(cfg)
            want = spec or alarms.first_glow(cfg)  # ahead of the first alarm: painting takes a moment on a big screen
            if want and want[:2] != painted:
                painted = want[:2]
                painter.paint_glow(glow, size, alarms.glow_pixels(size, *painted), origin)
            shown_glow = spec and spec[:2] == painted and (watch.preview or watch.trial or (not watch.hidden and alarms.game_focused()))
            glow.show(shown_glow and (not spec[2] or watch.lit(spec[2])))
            if time.monotonic() - raised >= alarms.TOP_S:  # back on top of a game that went full screen; the screen may have changed
                raised, origin = time.monotonic(), (x11.screen_box() or (0, 0))[:2]
                for layer in layers:
                    layer.lift()
            x11.lib().XFlush(d)
            ms = alarms.HUD_FRAME_MS if shapes or watch.ringing else alarms.MAP_FRAME_MS if frame else int(alarms.POLL_S * 1000)
            watch.stopping.wait(ms / 1000)
    except Exception as e:  # no X display, no compositor, no cairo...: the alarms still beep
        print(f"Overlay off: {e}", flush=True)
    finally:
        if painter:
            painter.close(layers or [])
        for layer in layers or []:
            layer.close()
        if d:
            x11.lib().XCloseDisplay(d)
