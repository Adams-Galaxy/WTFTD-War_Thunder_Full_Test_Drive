"""The minimap painted by Windows (GDI+) into a layered window: the game's map turned with the aircraft and cut round or
square, smooth lines and words, its own opacity. Tk can't turn a picture or cut it round, and can't read a JPEG, which
the game sends for some maps; GDI+ does all of it (Windows only, like the overlay). minimap.draw says what goes where."""
from __future__ import annotations

import ctypes
import math
from ctypes import wintypes as w

STATUS = ctypes.c_int
P = ctypes.c_void_p
F = ctypes.c_float
PARGB = 0xE200B  # PixelFormat32bppPARGB: what a layered window takes
UNIT_PIXEL, SMOOTH, BILINEAR, BICUBIC, TEXT_SMOOTH, BOLD = 2, 4, 3, 7, 4, 1
MOST = 4096  # the scaled copy's largest side
ANCHORS = {"w": 0, "m": 1, "e": 2}  # StringAlignmentNear, Center, Far


class StartupInput(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("callback", P), ("no_thread", w.BOOL), ("no_codecs", w.BOOL)]


class PointF(ctypes.Structure):
    _fields_ = [("x", F), ("y", F)]


class RectF(ctypes.Structure):
    _fields_ = [("x", F), ("y", F), ("w", F), ("h", F)]


class Header(ctypes.Structure):  # BITMAPINFOHEADER
    _fields_ = [("size", w.DWORD), ("width", w.LONG), ("height", w.LONG), ("planes", w.WORD), ("bits", w.WORD), ("rest", w.DWORD * 6)]


class Blend(ctypes.Structure):
    _fields_ = [("op", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("constant", ctypes.c_ubyte), ("format", ctypes.c_ubyte)]


SIGNATURES = {
    "GdiplusStartup": [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(StartupInput), P],
    "GdipLoadImageFromFile": [ctypes.c_wchar_p, ctypes.POINTER(P)],
    "GdipGetImageWidth": [P, ctypes.POINTER(ctypes.c_uint)], "GdipGetImageHeight": [P, ctypes.POINTER(ctypes.c_uint)],
    "GdipDisposeImage": [P],
    "GdipCreateBitmapFromScan0": [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, P, ctypes.POINTER(P)],
    "GdipGetImageGraphicsContext": [P, ctypes.POINTER(P)], "GdipDeleteGraphics": [P],
    "GdipSetSmoothingMode": [P, ctypes.c_int], "GdipSetInterpolationMode": [P, ctypes.c_int], "GdipSetTextRenderingHint": [P, ctypes.c_int],
    "GdipCreatePath": [ctypes.c_int, ctypes.POINTER(P)], "GdipDeletePath": [P],
    "GdipAddPathEllipse": [P, F, F, F, F], "GdipAddPathRectangle": [P, F, F, F, F],
    "GdipSetClipPath": [P, P, ctypes.c_int], "GdipResetClip": [P],
    "GdipCreateSolidFill": [ctypes.c_uint32, ctypes.POINTER(P)], "GdipDeleteBrush": [P], "GdipFillPath": [P, P, P],
    "GdipCreateMatrix2": [F, F, F, F, F, F, ctypes.POINTER(P)], "GdipDeleteMatrix": [P],
    "GdipSetWorldTransform": [P, P], "GdipResetWorldTransform": [P],
    "GdipDrawImageRectI": [P, P, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int],
    "GdipCreatePen1": [ctypes.c_uint32, F, ctypes.c_int, ctypes.POINTER(P)], "GdipDeletePen": [P],
    "GdipDrawLine": [P, P, F, F, F, F], "GdipDrawEllipse": [P, P, F, F, F, F],
    "GdipFillPolygon": [P, P, ctypes.POINTER(PointF), ctypes.c_int, ctypes.c_int], "GdipDrawPolygon": [P, P, ctypes.POINTER(PointF), ctypes.c_int],
    "GdipCreateFontFamilyFromName": [ctypes.c_wchar_p, P, ctypes.POINTER(P)], "GdipDeleteFontFamily": [P],
    "GdipCreateFont": [P, F, ctypes.c_int, ctypes.c_int, ctypes.POINTER(P)], "GdipDeleteFont": [P],
    "GdipCreateStringFormat": [ctypes.c_int, ctypes.c_int, ctypes.POINTER(P)], "GdipDeleteStringFormat": [P],
    "GdipSetStringFormatAlign": [P, ctypes.c_int], "GdipSetStringFormatLineAlign": [P, ctypes.c_int],
    "GdipDrawString": [P, ctypes.c_wchar_p, ctypes.c_int, P, ctypes.POINTER(RectF), P, P],
}


def argb(color: str, alpha: int = 255) -> int:
    return (alpha << 24) | int(color[1:7], 16)


class Painter:
    """GDI+ started once for the overlay's thread; the map picture read once per map (any format the game sends)."""

    def __init__(self):
        self.gp = ctypes.WinDLL("gdiplus")
        for name, args in SIGNATURES.items():
            fn = getattr(self.gp, name)
            fn.argtypes, fn.restype = args, STATUS
        self.token = ctypes.c_size_t()
        if self.gp.GdiplusStartup(ctypes.byref(self.token), ctypes.byref(StartupInput(1)), None):
            raise OSError("GDI+ didn't start")
        self.image, self.image_key, self.image_size, self.fonts, self.formats = None, None, (0, 0), {}, {}
        self.scaled, self.scaled_key = None, None  # the picture at the minimap's scale: each image only turns it
        self.family = P()
        self.gp.GdipCreateFontFamilyFromName("Consolas", None, ctypes.byref(self.family))

    def load(self, path: str | None, key) -> bool:
        """The map's picture, from the file the game's answer was kept in; False when there's none it can read."""
        if key != self.image_key:
            for old in (self.image, self.scaled):
                if old:
                    self.gp.GdipDisposeImage(old)
            self.image, self.image_key, self.scaled, self.scaled_key = None, key, None, None
            image = P()
            if path and not self.gp.GdipLoadImageFromFile(path, ctypes.byref(image)):
                width, height = ctypes.c_uint(), ctypes.c_uint()
                self.gp.GdipGetImageWidth(image, ctypes.byref(width))
                self.gp.GdipGetImageHeight(image, ctypes.byref(height))
                self.image, self.image_size = image, (width.value, height.value)
        return self.image is not None

    def _scaled(self, k: float):
        """The map picture k pixels across (its own size at most), made once for a zoom and size: shrinking 2048 pixels at
        each image took 15 ms, turning a copy already at its scale takes a few."""
        n = max(1, min(round(k), self.image_size[0], MOST))
        if self.scaled_key != n:
            if self.scaled:
                self.gp.GdipDisposeImage(self.scaled)
            bitmap, g = P(), P()
            self.gp.GdipCreateBitmapFromScan0(n, n, 0, PARGB, None, ctypes.byref(bitmap))
            self.gp.GdipGetImageGraphicsContext(bitmap, ctypes.byref(g))
            self.gp.GdipSetInterpolationMode(g, BICUBIC)
            self.gp.GdipDrawImageRectI(g, self.image, 0, 0, n, n)
            self.gp.GdipDeleteGraphics(g)
            self.scaled, self.scaled_key = bitmap, n
        return self.scaled, n

    def _font(self, size: float):
        key = round(size)
        if key not in self.fonts:
            font = P()
            self.gp.GdipCreateFont(self.family, F(max(6, key)), BOLD, UNIT_PIXEL, ctypes.byref(font))
            self.fonts[key] = font
        return self.fonts[key]

    def _format(self, anchor: str):
        if anchor not in self.formats:
            fmt = P()
            self.gp.GdipCreateStringFormat(0, 0, ctypes.byref(fmt))
            self.gp.GdipSetStringFormatAlign(fmt, ANCHORS[anchor])
            self.gp.GdipSetStringFormatLineAlign(fmt, 1)  # the middle of the text on y, as hud.draw's
            self.formats[anchor] = fmt
        return self.formats[anchor]

    def _shape(self, g, s: list, ox: float, oy: float):
        color = argb(s[-1])
        if s[0] == "t":
            brush = P()
            self.gp.GdipCreateSolidFill(color, ctypes.byref(brush))
            x = s[1] - ox - (0 if s[5] == "w" else 300 if s[5] == "m" else 600)
            self.gp.GdipDrawString(g, s[3], len(s[3]), self._font(s[4]), ctypes.byref(RectF(x, s[2] - oy - 50, 600, 100)), self._format(s[5]), brush)
            self.gp.GdipDeleteBrush(brush)
            return
        if s[0] == "p" and s[2]:
            brush = P()
            self.gp.GdipCreateSolidFill(color, ctypes.byref(brush))
            pts = (PointF * (len(s[1]) // 2))(*(PointF(s[1][i] - ox, s[1][i + 1] - oy) for i in range(0, len(s[1]), 2)))
            self.gp.GdipFillPolygon(g, brush, pts, len(pts), 0)
            self.gp.GdipDeleteBrush(brush)
            return
        pen = P()
        self.gp.GdipCreatePen1(color, F(s[5] if s[0] == "l" else 1.8), UNIT_PIXEL, ctypes.byref(pen))
        if s[0] == "l":
            self.gp.GdipDrawLine(g, pen, s[1] - ox, s[2] - oy, s[3] - ox, s[4] - oy)
        elif s[0] == "c":
            self.gp.GdipDrawEllipse(g, pen, s[1] - s[3] - ox, s[2] - s[3] - oy, 2 * s[3], 2 * s[3])
        else:
            pts = (PointF * (len(s[1]) // 2))(*(PointF(s[1][i] - ox, s[1][i + 1] - oy) for i in range(0, len(s[1]), 2)))
            self.gp.GdipDrawPolygon(g, pen, pts, len(pts))
        self.gp.GdipDeletePen(pen)

    def draw(self, g, frame: dict, ox: float, oy: float):
        """The minimap into a GDI+ graphics whose (0, 0) is the screen's (ox, oy)."""
        gp, (left, top, size) = self.gp, frame["box"]
        r, mid_x, mid_y = size / 2, left + size / 2 - ox, top + size / 2 - oy
        gp.GdipSetSmoothingMode(g, SMOOTH)
        gp.GdipSetInterpolationMode(g, BILINEAR)
        gp.GdipSetTextRenderingHint(g, TEXT_SMOOTH)
        path, dark = P(), P()
        gp.GdipCreatePath(0, ctypes.byref(path))
        (gp.GdipAddPathEllipse if frame["round"] else gp.GdipAddPathRectangle)(path, mid_x - r, mid_y - r, size, size)
        gp.GdipSetClipPath(g, path, 0)
        gp.GdipCreateSolidFill(argb("#141A22"), ctypes.byref(dark))
        gp.GdipFillPath(g, dark, path)  # under the picture, and where the map ends when it turns
        gp.GdipDeleteBrush(dark)
        pic = frame["picture"]
        if self.image and pic:  # image pixel (u, v) -> share of the map (u/W, v/H) -> the screen, turned around the centre
            (picture, n), k, t = self._scaled(pic["k"]), pic["k"], math.radians(pic["turn"])
            c, s, a, b = math.cos(t), math.sin(t), k / n, k / n
            matrix = P()
            gp.GdipCreateMatrix2(a * c, -a * s, b * s, b * c, mid_x - pic["cx"] * k * c - pic["cy"] * k * s,
                                 mid_y + pic["cx"] * k * s - pic["cy"] * k * c, ctypes.byref(matrix))
            gp.GdipSetWorldTransform(g, matrix)
            gp.GdipDrawImageRectI(g, picture, 0, 0, n, n)
            gp.GdipResetWorldTransform(g)
            gp.GdipDeleteMatrix(matrix)
        for shape in frame["marks"]:
            self._shape(g, shape, ox, oy)
        gp.GdipResetClip(g)
        gp.GdipDeletePath(path)
        for shape in frame["frame"]:
            self._shape(g, shape, ox, oy)

    def pixels(self, frame: dict, width: int, height: int, ox: float, oy: float) -> bytes:
        """The minimap as premultiplied BGRA, top row first: for the tests, and what paint sends to the window."""
        buffer = (ctypes.c_ubyte * (width * height * 4))()
        self._paint_into(ctypes.addressof(buffer), frame, width, height, ox, oy)
        return bytes(buffer)

    def _paint_into(self, bits: int, frame: dict, width: int, height: int, ox: float, oy: float):
        bitmap, g = P(), P()
        self.gp.GdipCreateBitmapFromScan0(width, height, width * 4, PARGB, P(bits), ctypes.byref(bitmap))
        self.gp.GdipGetImageGraphicsContext(bitmap, ctypes.byref(g))
        try:
            self.draw(g, frame, ox, oy)
        finally:
            self.gp.GdipDeleteGraphics(g)
            self.gp.GdipDisposeImage(bitmap)

    def paint(self, hwnd: int, frame: dict, opacity: float) -> bool:
        """The minimap into its layered window, which takes the place and size of the minimap and its words below."""
        left, top, size = frame["box"]
        ox, oy, width, height = int(left) - 2, int(top) - 2, max(int(size), 240) + 4, int(size) + 34
        gdi, user = ctypes.WinDLL("gdi32"), ctypes.WinDLL("user32")
        gdi.CreateCompatibleDC.argtypes, gdi.CreateCompatibleDC.restype = [w.HDC], w.HDC
        gdi.CreateDIBSection.argtypes = [w.HDC, P, w.UINT, ctypes.POINTER(P), w.HANDLE, w.DWORD]
        gdi.CreateDIBSection.restype = w.HBITMAP
        gdi.SelectObject.argtypes, gdi.SelectObject.restype = [w.HDC, w.HANDLE], w.HANDLE
        gdi.DeleteObject.argtypes, gdi.DeleteDC.argtypes = [w.HANDLE], [w.HDC]
        user.UpdateLayeredWindow.argtypes = [w.HWND, w.HDC, ctypes.POINTER(w.POINT), ctypes.POINTER(w.SIZE), w.HDC,
                                             ctypes.POINTER(w.POINT), w.COLORREF, ctypes.POINTER(Blend), w.DWORD]
        dc, bits = gdi.CreateCompatibleDC(None), P()
        picture = gdi.CreateDIBSection(dc, ctypes.byref(Header(40, width, -height, 1, 32)), 0, ctypes.byref(bits), None, 0)  # top row first
        done = False
        if picture:
            self._paint_into(bits.value, frame, width, height, ox, oy)
            before = gdi.SelectObject(dc, picture)
            done = bool(user.UpdateLayeredWindow(hwnd, None, ctypes.byref(w.POINT(ox, oy)), ctypes.byref(w.SIZE(width, height)), dc,
                                                 ctypes.byref(w.POINT(0, 0)), 0, ctypes.byref(Blend(0, 0, round(255 * opacity), 1)), 2))
            gdi.SelectObject(dc, before)
            gdi.DeleteObject(picture)
        gdi.DeleteDC(dc)
        return done
