"""The app window seen from X11 (Linux): tray.py's functions, so that __main__ keeps its place, minimizes it and closes it
with the game as on Windows. The window is the browser's (started on X11, through XWayland on a Wayland session), found
by its title and only ever moved, minimized, brought forward or asked to close, through the window manager (EWMH).
No notification area: its icon needs a D-Bus service the standard library can't offer, so that option stays off here."""
from __future__ import annotations

import ctypes
import time

from . import x11
from .tray import TITLE

P, XID, INT, UINT = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_uint
CLIENT_MESSAGE, ROOT_MASK = 33, (1 << 19) | (1 << 20)  # SubstructureNotify | SubstructureRedirect: what the window manager hears
ADD, REMOVE, FROM_PAGER = 1, 0, 2
SETTLE_LOOKS, SETTLE_S = 10, 0.05  # how long a move is waited for
_normal: dict = {}  # window -> its last place not maximized: X keeps none while it is


class ClientMessage(ctypes.Structure):  # XClientMessageEvent
    _fields_ = [("type", INT), ("serial", XID), ("send_event", INT), ("display", P), ("window", XID), ("message_type", XID),
                ("format", INT), ("data", ctypes.c_long * 5)]


class Event(ctypes.Union):  # XEvent: 24 longs
    _fields_ = [("client", ClientMessage), ("pad", ctypes.c_long * 24)]


class Attributes(ctypes.Structure):  # XWindowAttributes, as far as the size
    _fields_ = [("x", INT), ("y", INT), ("width", INT), ("height", INT), ("rest", ctypes.c_long * 32)]


def _lib():
    x = x11.lib()
    x.XQueryTree.argtypes = [P, XID, ctypes.POINTER(XID), ctypes.POINTER(XID), ctypes.POINTER(ctypes.POINTER(XID)), ctypes.POINTER(UINT)]
    x.XSendEvent.argtypes = [P, XID, INT, ctypes.c_long, ctypes.POINTER(Event)]
    x.XGetWindowAttributes.argtypes = [P, XID, ctypes.POINTER(Attributes)]
    x.XTranslateCoordinates.argtypes = [P, XID, XID, INT, INT, ctypes.POINTER(INT), ctypes.POINTER(INT), ctypes.POINTER(XID)]
    x.XIconifyWindow.argtypes = [P, XID, INT]
    return x


def _tell(window: int, kind: str, *data: int, to: int | None = None):
    """A message about this window to the window manager (EWMH), or to the window itself (to=window, ICCCM)."""
    d, x = x11.display(), _lib()
    event = Event(client=ClientMessage(CLIENT_MESSAGE, 0, 1, d, window, x11.atom(kind), 32, (ctypes.c_long * 5)(*data)))
    with x11._lock:
        x.XSendEvent(d, to or x.XDefaultRootWindow(d), 0, 0 if to else ROOT_MASK, ctypes.byref(event))
        x.XFlush(d)


def _children(window: int, depth: int) -> list:
    """The windows under this one, this many levels down: a window manager's frames hold the windows it manages."""
    d, x = x11.display(), _lib()
    root, parent, kids, count = XID(), XID(), ctypes.POINTER(XID)(), UINT()
    with x11._lock:
        if not x.XQueryTree(d, window, ctypes.byref(root), ctypes.byref(parent), ctypes.byref(kids), ctypes.byref(count)):
            return []
        found = kids[:count.value]
        if kids:
            x.XFree(kids)
    return [w for k in found for w in (k, *(_children(k, depth - 1) if depth > 1 else ()))]


def primary_scale() -> float:
    """X counts in the screen's pixels, as the browser's window flags do here."""
    return 1.0


def find_window(title: str = TITLE, **_):
    """The app's window, by its title among the windows the window manager lists."""
    if not x11.display():
        return None
    root = x11.lib().XDefaultRootWindow(x11.display())
    for window in x11.prop(root, "_NET_CLIENT_LIST") or _children(root, 3):  # no list from this window manager: all of them
        name = x11.prop(window, "_NET_WM_NAME") or x11.prop(window, "WM_NAME") or b""
        if isinstance(name, bytes) and name.decode("utf-8", "replace").startswith(title):
            return window
    return None


def _maximized(window: int) -> bool:
    state = x11.prop(window, "_NET_WM_STATE") or []
    return {x11.atom("_NET_WM_STATE_MAXIMIZED_VERT"), x11.atom("_NET_WM_STATE_MAXIMIZED_HORZ")} <= set(state)


def place_of(window) -> dict | None:
    """Where a window is: its frame's corner on the screen and its size, and whether it's maximized (then its place
    before that, when it was seen)."""
    d, x = x11.display(), _lib()
    attrs, left, top, child = Attributes(), INT(), INT(), XID()
    with x11._lock:
        if not x.XGetWindowAttributes(d, window, ctypes.byref(attrs)) or \
                not x.XTranslateCoordinates(d, window, x.XDefaultRootWindow(d), 0, 0, ctypes.byref(left), ctypes.byref(top), ctypes.byref(child)):
            return None
    frame = x11.prop(window, "_NET_FRAME_EXTENTS") or [0, 0, 0, 0]  # left, right, top, bottom: the window manager's frame
    place = {"x": left.value - frame[0], "y": top.value - frame[2], "w": attrs.width, "h": attrs.height, "max": _maximized(window)}
    if not place["max"]:
        _normal[window] = place
    return {**_normal.get(window, place), "max": True} if place["max"] else place


def usable(place) -> bool:
    """A place saved earlier, still on the screen: one unplugged since, or odd numbers, and the browser's own place stays."""
    if not isinstance(place, dict) or not all(type(place.get(k)) is int for k in "xywh") or not isinstance(place.get("max"), bool):
        return False
    if not (200 <= place["w"] <= 20000 and 150 <= place["h"] <= 20000) or not x11.display():
        return False
    x, d = x11.lib(), x11.display()
    screen = x.XDefaultScreen(d)
    width, height = x.XDisplayWidth(d, screen), x.XDisplayHeight(d, screen)
    return place["x"] < width and place["y"] < height and place["x"] + place["w"] > 0 and place["y"] + place["h"] > 0


def work_area(place: dict) -> dict | None:
    return None  # the window manager sizes a maximized window itself


def _move(window: int, left: int, top: int, width: int, height: int):
    d, x = x11.display(), _lib()
    with x11._lock:
        x.XMoveResizeWindow(d, window, left, top, width, height)
        x.XFlush(d)


def put(window, place: dict) -> bool:
    """Its place and size, then maximized or not, as the window manager does it. Window managers count a move from the
    frame's corner or from the window's: where it lands is read back, and a window that's off is moved by the difference
    (else the place would creep at every start)."""
    _tell(window, "_NET_WM_STATE", REMOVE, x11.atom("_NET_WM_STATE_MAXIMIZED_VERT"), x11.atom("_NET_WM_STATE_MAXIMIZED_HORZ"), FROM_PAGER)
    before = place_of(window)
    _move(window, place["x"], place["y"], place["w"], place["h"])
    landed = before
    for _ in range(SETTLE_LOOKS):  # the window manager moves it in its own time
        time.sleep(SETTLE_S)
        landed = place_of(window)
        if landed != before:
            break
    if landed and (landed["x"], landed["y"]) != (place["x"], place["y"]):
        _move(window, 2 * place["x"] - landed["x"], 2 * place["y"] - landed["y"], place["w"], place["h"])
    _normal[window] = {k: place[k] for k in "xywh"} | {"max": False}
    if place["max"]:
        _tell(window, "_NET_WM_STATE", ADD, x11.atom("_NET_WM_STATE_MAXIMIZED_VERT"), x11.atom("_NET_WM_STATE_MAXIMIZED_HORZ"), FROM_PAGER)
    return True


def minimize(**where) -> bool:
    window = find_window(**where)
    if window:
        d, x = x11.display(), _lib()
        with x11._lock:
            x.XIconifyWindow(d, window, x.XDefaultScreen(d))
            x.XFlush(d)
    return bool(window)


def show(**where) -> bool:
    """Brings the app window to the front, restored if it was minimized: WTFTD started a second time shows this one."""
    window = find_window(**where)
    if window:
        _tell(window, "_NET_ACTIVE_WINDOW", FROM_PAGER, 0, 0)
    return bool(window)


def close(**where) -> bool:
    """Closes the app window as its own cross would (WM_DELETE_WINDOW, what the window manager sends it): the page says
    bye and WTFTD quits the usual way."""
    window = find_window(**where)
    if window:
        _tell(window, "WM_PROTOCOLS", x11.atom("WM_DELETE_WINDOW"), 0, to=window)
    return bool(window)


class Tray:
    """No notification area here: nothing to show, nothing to bring back."""

    def __init__(self, *_, **__):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def click(self) -> bool:
        return False
