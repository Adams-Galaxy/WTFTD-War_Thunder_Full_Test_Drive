"""X11 through ctypes (libX11, libXrandr), Linux: which window is in front, the screen's size. One connection per
thread (Xlib's are not shared), opened on first use; every function answers None where there's no X display (a server,
a Wayland session without XWayland). An X error (a window gone between two calls) is ignored, never fatal: Xlib's own
handler would end the process."""
from __future__ import annotations

import ctypes
import threading

P, XID = ctypes.c_void_p, ctypes.c_ulong
_local = threading.local()
_lib: dict = {}


class Monitor(ctypes.Structure):  # XRRMonitorInfo
    _fields_ = [("name", XID), ("primary", ctypes.c_int), ("automatic", ctypes.c_int), ("noutput", ctypes.c_int),
                ("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("mwidth", ctypes.c_int), ("mheight", ctypes.c_int), ("outputs", P)]


def lib():
    """libX11, loaded once; None where it isn't installed."""
    if "x" not in _lib:
        try:
            x = ctypes.CDLL("libX11.so.6")
        except OSError:
            _lib["x"] = None
            return None
        x.XInitThreads()  # before any other call: the overlay's thread and the reader's each have a connection
        x.XOpenDisplay.argtypes, x.XOpenDisplay.restype = [ctypes.c_char_p], P
        x.XDefaultRootWindow.argtypes, x.XDefaultRootWindow.restype = [P], XID
        x.XDefaultScreen.argtypes = [P]
        x.XDisplayWidth.argtypes = x.XDisplayHeight.argtypes = [P, ctypes.c_int]
        x.XInternAtom.argtypes, x.XInternAtom.restype = [P, ctypes.c_char_p, ctypes.c_int], XID
        x.XGetWindowProperty.argtypes = [P, XID, XID, ctypes.c_long, ctypes.c_long, ctypes.c_int, XID, ctypes.POINTER(XID),
                                         ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                                         ctypes.POINTER(P)]
        x.XFree.argtypes = [P]
        _lib["handler"] = ctypes.CFUNCTYPE(ctypes.c_int, P, P)(lambda d, e: 0)  # kept: Xlib calls it later
        x.XSetErrorHandler(_lib["handler"])
        _lib["x"] = x
    return _lib["x"]


def display():
    """This thread's connection to the X server, None if there's none."""
    if not hasattr(_local, "d"):
        x = lib()
        _local.d = x.XOpenDisplay(None) if x else None
    return _local.d


def atom(name: str) -> int:
    return lib().XInternAtom(display(), name.encode(), 0)


def prop(window: int, name: str) -> list | bytes | None:
    """A window's property: numbers (format 32: windows, atoms, cardinals), else bytes; None if it has none."""
    x, d = lib(), display()
    kind, fmt, count, after, data = XID(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong(), P()
    if x.XGetWindowProperty(d, window, atom(name), 0, 1 << 16, 0, 0, ctypes.byref(kind), ctypes.byref(fmt), ctypes.byref(count),
                            ctypes.byref(after), ctypes.byref(data)) or not data.value:
        return None
    try:
        if fmt.value == 32:  # Xlib hands 32-bit items as C longs
            return list(ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[:count.value])
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


def screen_size() -> tuple | None:
    """The main screen's size in pixels: XRandR's primary monitor, else the first, else the whole X screen."""
    d = display()
    if not d:
        return None
    x = lib()
    try:
        rr = ctypes.CDLL("libXrandr.so.2")
        rr.XRRGetMonitors.argtypes, rr.XRRGetMonitors.restype = [P, XID, ctypes.c_int, ctypes.POINTER(ctypes.c_int)], ctypes.POINTER(Monitor)
        rr.XRRFreeMonitors.argtypes = [ctypes.POINTER(Monitor)]
        n = ctypes.c_int()
        found = rr.XRRGetMonitors(d, x.XDefaultRootWindow(d), 1, ctypes.byref(n))
        if found and n.value:
            try:
                m = next((found[i] for i in range(n.value) if found[i].primary), found[0])
                return m.width, m.height
            finally:
                rr.XRRFreeMonitors(found)
    except OSError:  # no XRandR: the X screen
        pass
    screen = x.XDefaultScreen(d)
    return x.XDisplayWidth(d, screen), x.XDisplayHeight(d, screen)
