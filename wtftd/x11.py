"""X11 through ctypes (libX11, libXext, libXrandr), Linux: which window is in front, the screen, the keys held, and the
overlay's windows. Questions go through one shared connection (any thread, under a lock: the page's requests each come
in a thread of their own); the overlay opens its own for its windows. Every question answers None where there's no X
display (a server, a Wayland session without XWayland). An X error (a window gone between two calls) is ignored, never
fatal: Xlib's own handler would end the process."""
from __future__ import annotations

import ctypes
import os
import threading

P, XID, INT, UINT = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_uint
_lock = threading.RLock()
_lib: dict = {}
_atoms: dict = {}
_codes: dict = {}  # keysym -> keycode, on the shared connection
SHAPE_INPUT, INPUT_OUTPUT, TRUE_COLOR = 2, 1, 4
CW_BACK_PIXEL, CW_BORDER_PIXEL, CW_OVERRIDE_REDIRECT, CW_COLORMAP = 1 << 1, 1 << 3, 1 << 9, 1 << 13

# Windows' key codes (My overlay keeps the browser's keyCode, which are those) -> X keysyms; a tuple: either key
VK_KEYSYMS = {**{vk: vk + 0x20 for vk in range(0x41, 0x5B)}, **{vk: vk for vk in range(0x30, 0x3A)},  # letters, digits
              **{0x70 + i: 0xFFBE + i for i in range(24)}, **{0x60 + i: 0xFFB0 + i for i in range(10)},  # F1-F24, numpad
              0x6A: 0xFFAA, 0x6B: 0xFFAB, 0x6C: 0xFFAC, 0x6D: 0xFFAD, 0x6E: 0xFFAE, 0x6F: 0xFFAF,
              0x08: 0xFF08, 0x09: 0xFF09, 0x0D: 0xFF0D, 0x13: 0xFF13, 0x14: 0xFFE5, 0x1B: 0xFF1B, 0x20: 0x20,
              0x21: 0xFF55, 0x22: 0xFF56, 0x23: 0xFF57, 0x24: 0xFF50, 0x25: 0xFF51, 0x26: 0xFF52, 0x27: 0xFF53, 0x28: 0xFF54,
              0x2C: 0xFF61, 0x2D: 0xFF63, 0x2E: 0xFFFF, 0x90: 0xFF7F, 0x91: 0xFF14, 0x5B: 0xFFEB, 0x5C: 0xFFEC, 0x5D: 0xFF67,
              0x10: (0xFFE1, 0xFFE2), 0x11: (0xFFE3, 0xFFE4), 0x12: (0xFFE9, 0xFFEA, 0xFE03),  # Shift, Ctrl, Alt (AltGr too)
              0xA0: 0xFFE1, 0xA1: 0xFFE2, 0xA2: 0xFFE3, 0xA3: 0xFFE4, 0xA4: 0xFFE9, 0xA5: 0xFFEA,
              0xBA: 0x3B, 0xBB: 0x3D, 0xBC: 0x2C, 0xBD: 0x2D, 0xBE: 0x2E, 0xBF: 0x2F, 0xC0: 0x60, 0xDB: 0x5B, 0xDC: 0x5C,
              0xDD: 0x5D, 0xDE: 0x27, 0xE2: 0x3C}
MOUSE = {1: 1 << 8, 2: 1 << 10, 4: 1 << 9}  # left, right, middle -> X's pointer mask; the side buttons aren't in it


class Monitor(ctypes.Structure):  # XRRMonitorInfo
    _fields_ = [("name", XID), ("primary", INT), ("automatic", INT), ("noutput", INT), ("x", INT), ("y", INT),
                ("width", INT), ("height", INT), ("mwidth", INT), ("mheight", INT), ("outputs", P)]


class VisualInfo(ctypes.Structure):  # XVisualInfo
    _fields_ = [("visual", P), ("visualid", XID), ("screen", INT), ("depth", INT), ("cls", INT), ("red_mask", XID),
                ("green_mask", XID), ("blue_mask", XID), ("colormap_size", INT), ("bits_per_rgb", INT)]


class WindowAttributes(ctypes.Structure):  # XSetWindowAttributes
    _fields_ = [("background_pixmap", XID), ("background_pixel", XID), ("border_pixmap", XID), ("border_pixel", XID),
                ("bit_gravity", INT), ("win_gravity", INT), ("backing_store", INT), ("backing_planes", XID), ("backing_pixel", XID),
                ("save_under", INT), ("event_mask", ctypes.c_long), ("do_not_propagate_mask", ctypes.c_long),
                ("override_redirect", INT), ("colormap", XID), ("cursor", XID)]


SIGNATURES = {  # name: (restype, argtypes)
    "XOpenDisplay": (P, [ctypes.c_char_p]), "XCloseDisplay": (INT, [P]), "XFlush": (INT, [P]), "XFree": (INT, [P]),
    "XDefaultRootWindow": (XID, [P]), "XDefaultScreen": (INT, [P]),
    "XDisplayWidth": (INT, [P, INT]), "XDisplayHeight": (INT, [P, INT]),
    "XInternAtom": (XID, [P, ctypes.c_char_p, INT]), "XGetSelectionOwner": (XID, [P, XID]),
    "XGetWindowProperty": (INT, [P, XID, XID, ctypes.c_long, ctypes.c_long, INT, XID, ctypes.POINTER(XID), ctypes.POINTER(INT),
                                 ctypes.POINTER(XID), ctypes.POINTER(XID), ctypes.POINTER(P)]),
    "XQueryKeymap": (INT, [P, ctypes.c_char * 32]), "XKeysymToKeycode": (ctypes.c_ubyte, [P, XID]),
    "XQueryPointer": (INT, [P, XID, ctypes.POINTER(XID), ctypes.POINTER(XID), ctypes.POINTER(INT), ctypes.POINTER(INT),
                            ctypes.POINTER(INT), ctypes.POINTER(INT), ctypes.POINTER(UINT)]),
    "XMatchVisualInfo": (INT, [P, INT, INT, INT, ctypes.POINTER(VisualInfo)]),
    "XCreateColormap": (XID, [P, XID, P, INT]),
    "XCreateWindow": (XID, [P, XID, INT, INT, UINT, UINT, UINT, INT, UINT, P, XID, ctypes.POINTER(WindowAttributes)]),
    "XMoveResizeWindow": (INT, [P, XID, INT, INT, UINT, UINT]), "XMapRaised": (INT, [P, XID]), "XUnmapWindow": (INT, [P, XID]),
    "XRaiseWindow": (INT, [P, XID]), "XDestroyWindow": (INT, [P, XID]), "XStoreName": (INT, [P, XID, ctypes.c_char_p]),
    "XCreatePixmap": (XID, [P, XID, UINT, UINT, UINT]), "XFreePixmap": (INT, [P, XID]),
    "XSetWindowBackgroundPixmap": (INT, [P, XID, XID]), "XClearArea": (INT, [P, XID, INT, INT, UINT, UINT, INT]),
}


def lib():
    """libX11, loaded once; None where it isn't installed."""
    if "x" not in _lib:
        try:
            x = ctypes.CDLL("libX11.so.6")
        except OSError:
            _lib["x"] = None
            return None
        x.XInitThreads()  # before any other call: the shared connection is used from several threads
        for name, (restype, argtypes) in SIGNATURES.items():
            fn = getattr(x, name)
            fn.restype, fn.argtypes = restype, argtypes
        _lib["handler"] = ctypes.CFUNCTYPE(INT, P, P)(lambda d, e: 0)  # kept: Xlib calls it later
        x.XSetErrorHandler(_lib["handler"])
        _lib["x"] = x
    return _lib["x"]


def open_display():
    """A connection of its own (the overlay's), None if there's no X display."""
    x = lib()
    return x.XOpenDisplay(None) if x else None


def display():
    """The shared connection for questions, opened once."""
    with _lock:
        if "d" not in _lib:
            _lib["d"] = open_display()
        return _lib["d"]


def atom(name: str) -> int:
    if name not in _atoms:
        _atoms[name] = lib().XInternAtom(display(), name.encode(), 0)
    return _atoms[name]


def prop(window: int, name: str) -> list | bytes | None:
    """A window's property: numbers (format 32: windows, atoms, cardinals), else bytes; None if it has none."""
    x, d = lib(), display()
    kind, fmt, count, after, data = XID(), INT(), XID(), XID(), P()
    with _lock:
        if x.XGetWindowProperty(d, window, atom(name), 0, 1 << 16, 0, 0, ctypes.byref(kind), ctypes.byref(fmt), ctypes.byref(count),
                                ctypes.byref(after), ctypes.byref(data)) or not data.value:
            return None
    try:
        if fmt.value == 32:  # Xlib hands 32-bit items as C longs
            return list(ctypes.cast(data, ctypes.POINTER(XID))[:count.value])
        return ctypes.string_at(data, count.value * fmt.value // 8)
    finally:
        x.XFree(data)


def active_pid() -> int | None:
    """The process of the window in front (_NET_ACTIVE_WINDOW, its _NET_WM_PID); None when it can't be told."""
    if not display():
        return None
    active = prop(lib().XDefaultRootWindow(display()), "_NET_ACTIVE_WINDOW")
    pid = prop(active[0], "_NET_WM_PID") if active and active[0] else None
    return pid[0] if pid else None


def screen_box() -> tuple | None:
    """The main screen (x, y, width, height): XRandR's primary monitor, else the first, else the whole X screen."""
    d = display()
    if not d:
        return None
    x = lib()
    with _lock:
        try:
            rr = ctypes.CDLL("libXrandr.so.2")
            rr.XRRGetMonitors.argtypes, rr.XRRGetMonitors.restype = [P, XID, INT, ctypes.POINTER(INT)], ctypes.POINTER(Monitor)
            rr.XRRFreeMonitors.argtypes = [ctypes.POINTER(Monitor)]
            n = INT()
            found = rr.XRRGetMonitors(d, x.XDefaultRootWindow(d), 1, ctypes.byref(n))
            if found and n.value:
                try:
                    m = next((found[i] for i in range(n.value) if found[i].primary), found[0])
                    return m.x, m.y, m.width, m.height
                finally:
                    rr.XRRFreeMonitors(found)
        except OSError:  # no XRandR: the X screen
            pass
        screen = x.XDefaultScreen(d)
        return 0, 0, x.XDisplayWidth(d, screen), x.XDisplayHeight(d, screen)


def screen_size() -> tuple | None:
    box = screen_box()
    return box[2:] if box else None


def composited() -> bool:
    """Something composites the windows, so that a 32-bit one is see-through: an X compositing manager, or Wayland
    (whose compositor shows XWayland's windows)."""
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    d = display()
    with _lock:
        return bool(d and lib().XGetSelectionOwner(d, atom(f"_NET_WM_CM_S{lib().XDefaultScreen(d)}")))


def held(keys) -> set:
    """Of these Windows key codes (keys and mouse buttons), the ones held now. Seen by X only while an X window (the
    game's, through XWayland too) has the keyboard."""
    d, x = display(), lib()
    if not d:
        return set()
    keymap, mask = (ctypes.c_char * 32)(), UINT()
    with _lock:
        x.XQueryKeymap(d, keymap)
        if any(k in MOUSE for k in keys):
            w, i = XID(), INT()
            x.XQueryPointer(d, x.XDefaultRootWindow(d), ctypes.byref(w), ctypes.byref(w), ctypes.byref(i), ctypes.byref(i),
                            ctypes.byref(i), ctypes.byref(i), ctypes.byref(mask))
        out = set()
        for k in keys:
            if k in MOUSE:
                if mask.value & MOUSE[k]:
                    out.add(k)
                continue
            syms = VK_KEYSYMS.get(k, ())
            for sym in syms if isinstance(syms, tuple) else (syms,):
                if sym not in _codes:
                    _codes[sym] = x.XKeysymToKeycode(d, sym)
                code = _codes[sym]
                if code and keymap.raw[code >> 3] >> (code & 7) & 1:
                    out.add(k)
    return out


class Layer:
    """One of the overlay's windows: see-through where nothing's drawn (a 32-bit visual, which a compositor blends),
    clicks going through it (an empty input shape), neither managed nor ever focused (override-redirect). cairopaint
    draws into .pixmap, its background: X shows it again by itself each time the window is mapped (a window drawn while
    hidden would come back empty). .surface is the pixmap's cairo surface, .size the pixmap's."""

    def __init__(self, d, name: str = "WTFTD overlay"):
        x, self.d = lib(), d
        root, info = x.XDefaultRootWindow(d), VisualInfo()
        if not x.XMatchVisualInfo(d, x.XDefaultScreen(d), 32, TRUE_COLOR, ctypes.byref(info)):
            raise OSError("no 32-bit visual: no see-through windows")
        attrs = WindowAttributes(background_pixel=0, border_pixel=0, override_redirect=1, colormap=x.XCreateColormap(d, root, info.visual, 0))
        self.visual = info.visual
        self.window = x.XCreateWindow(d, root, 0, 0, 1, 1, 0, 32, INPUT_OUTPUT, info.visual,
                                      CW_BACK_PIXEL | CW_BORDER_PIXEL | CW_OVERRIDE_REDIRECT | CW_COLORMAP, ctypes.byref(attrs))
        x.XStoreName(d, self.window, name.encode())
        ext = ctypes.CDLL("libXext.so.6")
        ext.XShapeCombineRectangles.argtypes = [P, XID, INT, INT, INT, P, INT, INT, INT]
        ext.XShapeCombineRectangles(d, self.window, SHAPE_INPUT, 0, 0, None, 0, 0, 0)  # ShapeSet, no rectangle: nothing to click
        self.box, self.shown, self.surface, self.pixmap, self.size = (0, 0, 1, 1), False, None, None, None

    def place(self, box: tuple) -> bool:
        """Moves and sizes it (x, y, width, height), when that changes; True if it did."""
        box = tuple(int(v) for v in box[:2]) + tuple(max(1, int(v)) for v in box[2:])
        if box == self.box:
            return False
        self.box = box
        lib().XMoveResizeWindow(self.d, self.window, *box)
        return True

    def show(self, on: bool):
        if bool(on) != self.shown:
            self.shown = bool(on)
            (lib().XMapRaised if on else lib().XUnmapWindow)(self.d, self.window)

    def refresh(self, area: tuple = (0, 0, 0, 0)):
        """Shows what its background holds now, in this part (x, y, width, height; 0 wide: all of it)."""
        lib().XClearArea(self.d, self.window, *area, 0)

    def lift(self):
        if self.shown:
            lib().XRaiseWindow(self.d, self.window)

    def close(self):
        lib().XDestroyWindow(self.d, self.window)
        if self.pixmap:
            lib().XFreePixmap(self.d, self.pixmap)
