"""The app window seen from Windows: minimizing or closing it from here, and the notification area (Windows only).
Minimized with the option on, it leaves the taskbar for an icon there: a click on the icon brings it back. The window is
the browser's, so it is found by its title and only ever shown, hidden, minimized or asked to close."""
from __future__ import annotations

import contextlib
import ctypes
import threading
from ctypes import wintypes as w
from pathlib import Path

TITLE = "WTFTD — War Thunder"
WINDOW_CLASS = "Chrome_WidgetWin_1"
WM_DESTROY, WM_CLOSE, WM_TIMER, WM_LBUTTONUP, WM_RBUTTONUP, WM_ICON = 0x2, 0x10, 0x113, 0x202, 0x205, 0x8001
SW_HIDE, SW_MINIMIZE, SW_RESTORE = 0, 6, 9
SW_SHOWNORMAL, SW_SHOWMINIMIZED, SW_SHOWMAXIMIZED, WPF_RESTORETOMAXIMIZED = 1, 2, 3, 2
NIM_ADD, NIM_DELETE, NIF_MESSAGE, NIF_ICON, NIF_TIP = 0, 2, 1, 2, 4
LOOK_MS = 500


class Placement(ctypes.Structure):  # WINDOWPLACEMENT
    _fields_ = [("length", w.UINT), ("flags", w.UINT), ("show", w.UINT), ("min", w.POINT), ("max", w.POINT), ("normal", w.RECT)]


class IconData(ctypes.Structure):  # NOTIFYICONDATAW
    _fields_ = [("size", w.DWORD), ("hwnd", w.HWND), ("id", w.UINT), ("flags", w.UINT), ("message", w.UINT), ("icon", w.HICON),
                ("tip", w.WCHAR * 128), ("state", w.DWORD), ("stateMask", w.DWORD), ("info", w.WCHAR * 256), ("version", w.UINT),
                ("infoTitle", w.WCHAR * 64), ("infoFlags", w.DWORD), ("guid", ctypes.c_byte * 16), ("balloon", w.HICON)]


def _user32():
    user = ctypes.WinDLL("user32")
    user.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    user.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    user.DefWindowProcW.restype = ctypes.c_ssize_t
    user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, *[ctypes.c_int] * 4, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
    user.CreateWindowExW.restype = w.HWND
    user.LoadImageW.argtypes = [w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int, ctypes.c_int, w.UINT]
    user.LoadImageW.restype = w.HANDLE
    user.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
    user.SetTimer.argtypes = [w.HWND, ctypes.c_size_t, w.UINT, ctypes.c_void_p]
    for name in ("IsIconic", "IsWindowVisible", "SetForegroundWindow", "DestroyWindow"):
        getattr(user, name).argtypes = [w.HWND]
    user.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
    user.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    user.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    user.GetWindowPlacement.argtypes = user.SetWindowPlacement.argtypes = [w.HWND, ctypes.POINTER(Placement)]
    user.MonitorFromRect.argtypes = [ctypes.POINTER(w.RECT), w.DWORD]
    user.MonitorFromRect.restype = w.HANDLE
    return user


@contextlib.contextmanager
def _real_pixels(user):
    """This thread in physical pixels for a while, read and written alike, whatever the process did about DPI (the overlay
    does); then as it was."""
    try:
        user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        before = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    except AttributeError:  # before Windows 10 1607: the process's own setting
        before = None
    try:
        yield
    finally:
        if before:
            user.SetThreadDpiAwarenessContext(ctypes.c_void_p(before))


def primary_scale() -> float:
    """The main screen's scale (1.5 at 150 %): the browser takes a window's place in its own pixels, physical ones divided by it."""
    user, dpi = _user32(), w.UINT(96)
    with _real_pixels(user):
        user.MonitorFromPoint.argtypes, user.MonitorFromPoint.restype = [w.POINT, w.DWORD], w.HANDLE
        try:
            ctypes.windll.shcore.GetDpiForMonitor(user.MonitorFromPoint(w.POINT(0, 0), 1), 0, ctypes.byref(dpi), ctypes.byref(w.UINT()))
        except (AttributeError, OSError):  # MONITOR_DEFAULTTOPRIMARY, MDT_EFFECTIVE_DPI
            pass
    return dpi.value / 96 or 1.0


def place_of(window) -> dict | None:
    """Where a window is: its restored rectangle (Windows' workspace coordinates) and whether it's maximized."""
    user = _user32()
    p = Placement(length=ctypes.sizeof(Placement))
    with _real_pixels(user):
        if not user.GetWindowPlacement(window, ctypes.byref(p)):
            return None
    r = p.normal
    maximized = p.show == SW_SHOWMAXIMIZED or (p.show == SW_SHOWMINIMIZED and p.flags & WPF_RESTORETOMAXIMIZED)
    return {"x": r.left, "y": r.top, "w": r.right - r.left, "h": r.bottom - r.top, "max": bool(maximized)}


def usable(place) -> bool:
    """A place saved earlier, still on a screen: one unplugged since, or odd numbers, and the browser's own place stays."""
    if not isinstance(place, dict) or not all(type(place.get(k)) is int for k in "xywh") or not isinstance(place.get("max"), bool):
        return False
    if not (200 <= place["w"] <= 20000 and 150 <= place["h"] <= 20000):
        return False
    user = _user32()
    rect = w.RECT(place["x"], place["y"], place["x"] + place["w"], place["y"] + place["h"])
    with _real_pixels(user):
        return bool(user.MonitorFromRect(ctypes.byref(rect), 0))  # MONITOR_DEFAULTTONULL


class MonitorInfo(ctypes.Structure):  # MONITORINFO
    _fields_ = [("size", w.DWORD), ("monitor", w.RECT), ("work", w.RECT), ("flags", w.DWORD)]


def work_area(place: dict) -> dict | None:
    """The screen a place is on, without its taskbar: where a maximized window goes, in the place's pixels."""
    user = _user32()
    user.GetMonitorInfoW.argtypes = [w.HANDLE, ctypes.POINTER(MonitorInfo)]
    rect, info = w.RECT(place["x"], place["y"], place["x"] + place["w"], place["y"] + place["h"]), MonitorInfo(ctypes.sizeof(MonitorInfo))
    with _real_pixels(user):
        monitor = user.MonitorFromRect(ctypes.byref(rect), 2)  # MONITOR_DEFAULTTONEAREST
        if not monitor or not user.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
    r = info.work
    return {"x": r.left, "y": r.top, "w": r.right - r.left, "h": r.bottom - r.top, "max": True}


def put(window, place: dict) -> bool:
    user = _user32()
    rect = w.RECT(place["x"], place["y"], place["x"] + place["w"], place["y"] + place["h"])
    p = Placement(length=ctypes.sizeof(Placement), show=SW_SHOWMAXIMIZED if place["max"] else SW_SHOWNORMAL, normal=rect)
    with _real_pixels(user):
        return bool(user.SetWindowPlacement(window, ctypes.byref(p)))


def find_window(title: str = TITLE, kind: str = WINDOW_CLASS):
    """The app's window: its title, in a window of the browser's class, so that no other window is ever touched."""
    user, found, buffer = _user32(), [], ctypes.create_unicode_buffer(128)

    def look(hwnd, _):
        user.GetClassNameW(hwnd, buffer, 128)
        if buffer.value == kind:
            user.GetWindowTextW(hwnd, buffer, 128)
            if buffer.value.startswith(title):
                found.append(hwnd)
        return not found

    user.EnumWindows(ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)(look), 0)
    return found[0] if found else None


def minimize(**where) -> bool:
    window = find_window(**where)
    if window:
        _user32().ShowWindow(window, SW_MINIMIZE)
    return bool(window)


def close(**where) -> bool:
    """Closes the app window as its own cross would: the page says bye and WTFTD quits the usual way."""
    window = find_window(**where)
    return bool(window) and bool(_user32().PostMessageW(window, WM_CLOSE, 0, 0))


class Tray(threading.Thread):
    """wanted: () -> is the option on? The icon shows only while the window is hidden, and there is always a way back."""

    def __init__(self, wanted, icon: Path, title: str = TITLE, kind: str = WINDOW_CLASS):
        super().__init__(daemon=True)
        self.wanted, self.icon, self.where = wanted, icon, {"title": title, "kind": kind}
        self.hwnd, self.window, self.data = None, None, None

    def add_icon(self):
        data = IconData(size=ctypes.sizeof(IconData), hwnd=self.hwnd, id=1, flags=NIF_MESSAGE | NIF_ICON | NIF_TIP, message=WM_ICON,
                        tip="WTFTD", icon=self.user.LoadImageW(None, str(self.icon), 1, 0, 0, 0x50))  # IMAGE_ICON, LOADFROMFILE | DEFAULTSIZE
        self.data = data if ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)) else None
        return self.data is not None

    def remove_icon(self):
        if self.data:
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.data))
            self.data = None

    def bring_back(self):
        self.remove_icon()
        if self.window:
            self.user.ShowWindow(self.window, SW_RESTORE)
            self.user.SetForegroundWindow(self.window)
        self.window = None

    def look(self):
        window = None if self.window or not self.wanted() else find_window(**self.where)
        if window and self.user.IsIconic(window) and self.user.IsWindowVisible(window) and self.add_icon():
            self.window = window  # no icon, no hiding: the window could never come back
            self.user.ShowWindow(window, SW_HIDE)

    def message(self, hwnd, msg, wparam, lparam):
        if msg == WM_TIMER:
            self.look()
        elif msg == WM_ICON and lparam & 0xFFFF in (WM_LBUTTONUP, WM_RBUTTONUP):
            self.bring_back()
        elif msg == WM_CLOSE:
            self.user.DestroyWindow(hwnd)
        elif msg == WM_DESTROY:
            self.bring_back()
            self.user.PostQuitMessage(0)
        else:
            return self.user.DefWindowProcW(hwnd, msg, wparam, lparam)
        return 0

    def run(self):
        self.user = _user32()
        procedure = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)(self.message)

        class WindowClass(ctypes.Structure):  # WNDCLASSW
            _fields_ = [("style", w.UINT), ("proc", type(procedure)), ("extra", ctypes.c_int), ("window", ctypes.c_int), ("instance", w.HINSTANCE),
                        ("icon", w.HICON), ("cursor", w.HANDLE), ("brush", w.HBRUSH), ("menu", w.LPCWSTR), ("name", w.LPCWSTR)]

        self.user.RegisterClassW(ctypes.byref(WindowClass(proc=procedure, name="WTFTDTray")))
        self.hwnd = self.user.CreateWindowExW(0, "WTFTDTray", "", 0, 0, 0, 0, 0, None, None, None, None)
        self.user.SetTimer(self.hwnd, 1, LOOK_MS, None)
        msg = w.MSG()
        while self.user.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            self.user.DispatchMessageW(ctypes.byref(msg))

    def stop(self):
        """Quitting with the window hidden: it comes back, so that nothing stays behind, and the icon goes."""
        if self.hwnd:
            self.user.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
