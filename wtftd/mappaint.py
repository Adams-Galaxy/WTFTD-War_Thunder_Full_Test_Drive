"""The overlay's minimap and text blocks painted by Windows (GDI+), each into a layered window. The minimap: the game's map
turned with the aircraft and cut round or square, smooth lines and words, its own opacity (Tk can't turn a picture or cut it
round, and can't read a JPEG, which the game sends for some maps; minimap.draw says what goes where). The text: smooth
letters on a see-through window, a clean outline or else a soft dark halo, see-through backgrounds (Tk drew them against a
colour made transparent, which left ragged edges, and its backgrounds were dotted). Windows only, like the overlay."""
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
EDGE, EDGE_PX = 0xE6000000, 2.5  # the dark edge round each mark: on a green or blue map, blue and green marks melted in
HALO, HALO_PX = 0xB0000000, 2.5  # round text with no outline, a soft dark halo: light text on a light sky didn't read
BLOCK_PAD = 10  # between a block's text and its frame or background
TRAILING_SPACES, NO_CLIP = 0x800, 0x4000  # StringFormatFlags: "IAS    771" keeps its spaces


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
    "GdipLoadImageFromStream": [P, ctypes.POINTER(P)],
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
    "GdipStringFormatGetGenericTypographic": [ctypes.POINTER(P)], "GdipCloneStringFormat": [P, ctypes.POINTER(P)],
    "GdipSetStringFormatFlags": [P, ctypes.c_int],
    "GdipMeasureString": [P, ctypes.c_wchar_p, ctypes.c_int, P, ctypes.POINTER(RectF), P, ctypes.POINTER(RectF), P, P],
    "GdipGetLineSpacing": [P, ctypes.c_int, ctypes.POINTER(ctypes.c_uint16)], "GdipGetEmHeight": [P, ctypes.c_int, ctypes.POINTER(ctypes.c_uint16)],
    "GdipAddPathString": [P, ctypes.c_wchar_p, ctypes.c_int, P, ctypes.c_int, F, ctypes.POINTER(RectF), P],
    "GdipDrawPath": [P, P, P], "GdipSetPenLineJoin": [P, ctypes.c_int],
    "GdipFillRectangle": [P, P, F, F, F, F], "GdipDrawRectangle": [P, P, F, F, F, F],
}


def _stream(data: bytes):
    """An IStream over a copy of the bytes (SHCreateMemStream), for GdipLoadImageFromStream."""
    shlwapi = ctypes.WinDLL("shlwapi")
    shlwapi.SHCreateMemStream.argtypes, shlwapi.SHCreateMemStream.restype = [ctypes.c_char_p, ctypes.c_uint], P
    return shlwapi.SHCreateMemStream(data, len(data)) or None


def _release(com) -> None:
    """IUnknown::Release, the third entry of a COM object's table."""
    table = ctypes.cast(com, ctypes.POINTER(ctypes.POINTER(P))).contents
    ctypes.WINFUNCTYPE(ctypes.c_ulong, P)(table[2])(com)


def argb(color: str, alpha: int = 255) -> int:
    return (alpha << 24) | int(color[1:7], 16)


class Layout:
    """Where the overlay's text blocks go, for both painters (this one, cairopaint's): each needs _text_font(cfg, size)
    -> (font, ..., line height) and _width(text, font)."""

    def text_layout(self, cfg: dict, lines: list) -> tuple:
        """Where each part of each line goes, as the Tk overlay laid them out: each block's lines in its columns, a column
        as wide as its widest line. Returns ([(x, y, text, colour, size, blinks, colour out of its turn)...], [(block, box)...])
        in screen pixels."""
        from .alarms import columns_of  # here: alarms imports this module
        parts, boxes = [], []
        for index, spot in enumerate([cfg, *cfg["blocks"]]):
            rows = [x for x in lines if x[4] == index]
            left, low, high, top = spot["x"], None, None, spot["y"]
            for column in columns_of(rows, spot["columns"]):
                y, wide = spot["y"], 0.0
                for _, color, size, blinks, _, row in column:
                    font, _, _, height = self._text_font(cfg, size)
                    x = left
                    for text, tint, *flash in row or [(" ", color)]:  # each part flashes on its own, or with its line
                        parts.append((x, y, text, tint, size, flash[0] if flash else blinks, flash[1] if len(flash) > 1 else None))
                        x += self._width(text, font)
                    y += height + cfg["spacing"]
                    wide = max(wide, x - left)
                    low = left if low is None else low
                high = max(high or 0, left + wide)
                left += wide + cfg["size"]
                top = max(top, y)
            if rows:
                boxes.append((spot, (spot["x"], spot["y"], high, top - cfg["spacing"])))
        return parts, boxes

    def text_box(self, cfg: dict, lines: list) -> tuple | None:
        """The window round all the blocks, with room for their frames, outlines and shadows: (x, y, width, height)."""
        _, boxes = self.text_layout(cfg, lines)
        if not boxes:
            return None
        margin = BLOCK_PAD + max(spot["frame"] for spot, _ in boxes) + 2 * cfg["outline"] + 4
        x0, y0 = min(b[0] for _, b in boxes) - margin, min(b[1] for _, b in boxes) - margin
        x1, y1 = max(b[2] for _, b in boxes) + margin, max(b[3] for _, b in boxes) + margin
        return int(x0), int(y0), int(x1 - x0) + 1, int(y1 - y0) + 1


class Painter(Layout):
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
        self.stream = None  # the memory the picture is read from: GDI+ needs it as long as the picture lives
        self.family = P()
        self.gp.GdipCreateFontFamilyFromName("Consolas", None, ctypes.byref(self.family))
        self.families, self.text_fonts = {}, {}
        typographic, self.typographic = P(), P()  # no padding round the words, their spaces kept: measured as Tk did
        self.gp.GdipStringFormatGetGenericTypographic(ctypes.byref(typographic))
        self.gp.GdipCloneStringFormat(typographic, ctypes.byref(self.typographic))
        self.gp.GdipSetStringFormatFlags(self.typographic, TRAILING_SPACES | NO_CLIP)
        self.measurer, self.measuring = P(), P()  # a graphics of its own to measure words with
        self.gp.GdipCreateBitmapFromScan0(1, 1, 0, PARGB, None, ctypes.byref(self.measurer))
        self.gp.GdipGetImageGraphicsContext(self.measurer, ctypes.byref(self.measuring))
        self.gp.GdipSetTextRenderingHint(self.measuring, TEXT_SMOOTH)

    def load(self, data: bytes | None, key) -> bool:
        """The map's picture, from the game's answer in memory (a file could be held by another WTFTD still closing, and
        then the map never came); False when there's none it can read."""
        if (key, data is not None) != self.image_key:
            for old in (self.image, self.scaled):
                if old:
                    self.gp.GdipDisposeImage(old)
            if self.stream:
                _release(self.stream)
            self.image, self.image_key, self.scaled, self.scaled_key, self.stream = None, (key, data is not None), None, None, None
            image = P()
            self.stream = _stream(data) if data else None
            if self.stream and not self.gp.GdipLoadImageFromStream(self.stream, ctypes.byref(image)):
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

    def _edge(self, g, s: list, ox: float, oy: float):
        """A dark edge under a mark, a little wider than it."""
        pen = P()
        self.gp.GdipCreatePen1(EDGE, F((s[5] if s[0] == "l" else 1.8) + 2 * EDGE_PX), UNIT_PIXEL, ctypes.byref(pen))
        if s[0] == "l":
            self.gp.GdipDrawLine(g, pen, s[1] - ox, s[2] - oy, s[3] - ox, s[4] - oy)
        elif s[0] == "c":
            self.gp.GdipDrawEllipse(g, pen, s[1] - s[3] - ox, s[2] - s[3] - oy, 2 * s[3], 2 * s[3])
        elif s[0] == "p":
            pts = (PointF * (len(s[1]) // 2))(*(PointF(s[1][i] - ox, s[1][i + 1] - oy) for i in range(0, len(s[1]), 2)))
            self.gp.GdipDrawPolygon(g, pen, pts, len(pts))
        self.gp.GdipDeletePen(pen)

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
        if self.image and pic and frame.get("dim"):  # the map darkened, so that the marks read on it
            shade = P()
            gp.GdipCreateSolidFill(round(255 * frame["dim"] / 100) << 24, ctypes.byref(shade))
            gp.GdipFillPath(g, shade, path)
            gp.GdipDeleteBrush(shade)
        for shape in frame["marks"]:
            self._edge(g, shape, ox, oy)
            self._shape(g, shape, ox, oy)
        gp.GdipResetClip(g)
        gp.GdipDeletePath(path)
        for shape in frame["frame"]:
            self._shape(g, shape, ox, oy)

    def pixels(self, frame: dict, width: int, height: int, ox: float, oy: float) -> bytes:
        """The minimap as premultiplied BGRA, top row first: for the tests, and what paint sends to the window."""
        return self._pixels(lambda g: self.draw(g, frame, ox, oy), width, height)

    def _pixels(self, draw, width: int, height: int) -> bytes:
        buffer = (ctypes.c_ubyte * (width * height * 4))()
        self._paint_into(ctypes.addressof(buffer), draw, width, height)
        return bytes(buffer)

    def _paint_into(self, bits: int, draw, width: int, height: int):
        bitmap, g = P(), P()
        self.gp.GdipCreateBitmapFromScan0(width, height, width * 4, PARGB, P(bits), ctypes.byref(bitmap))
        self.gp.GdipGetImageGraphicsContext(bitmap, ctypes.byref(g))
        try:
            draw(g)
        finally:
            self.gp.GdipDeleteGraphics(g)
            self.gp.GdipDisposeImage(bitmap)

    def paint(self, hwnd: int, frame: dict, opacity: float) -> bool:
        """The minimap into its layered window, which takes the place and size of the minimap and its words below."""
        left, top, size = frame["box"]
        ox, oy, width, height = int(left) - 2, int(top) - 2, max(int(size), 240) + 4, int(size) + 34
        return self._layered(hwnd, lambda g: self.draw(g, frame, ox, oy), ox, oy, width, height, opacity)

    def _layered(self, hwnd: int, draw, ox: int, oy: int, width: int, height: int, opacity: float) -> bool:
        """A layered window's whole picture, place and size at once: no move or resize to show black for a moment."""
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
            self._paint_into(bits.value, draw, width, height)
            before = gdi.SelectObject(dc, picture)
            done = bool(user.UpdateLayeredWindow(hwnd, None, ctypes.byref(w.POINT(ox, oy)), ctypes.byref(w.SIZE(width, height)), dc,
                                                 ctypes.byref(w.POINT(0, 0)), 0, ctypes.byref(Blend(0, 0, round(255 * opacity), 1)), 2))
            gdi.SelectObject(dc, before)
            gdi.DeleteObject(picture)
        gdi.DeleteDC(dc)
        return done

    # ---------------------------------------------------------------- the overlay's text blocks

    def _family(self, name: str):
        if name not in self.families:
            family = P()
            if self.gp.GdipCreateFontFamilyFromName(name, None, ctypes.byref(family)):
                family = self.family  # a font that isn't on this PC: Consolas
            self.families[name] = family
        return self.families[name]

    def _text_font(self, cfg: dict, size: float):
        style = (BOLD if cfg["bold"] else 0) | (2 if cfg["italic"] else 0)
        key = cfg["font"], round(size), style
        if key not in self.text_fonts:
            family, font = self._family(cfg["font"]), P()
            self.gp.GdipCreateFont(family, F(max(1, round(size))), style, UNIT_PIXEL, ctypes.byref(font))
            spacing, em = ctypes.c_uint16(), ctypes.c_uint16()
            self.gp.GdipGetLineSpacing(family, style, ctypes.byref(spacing))
            self.gp.GdipGetEmHeight(family, style, ctypes.byref(em))
            self.text_fonts[key] = (font, family, style, round(size) * spacing.value / (em.value or 1))
        return self.text_fonts[key]

    def _width(self, text: str, font) -> float:
        box = RectF()
        self.gp.GdipMeasureString(self.measuring, text, len(text), font, ctypes.byref(RectF(0, 0, 100000, 100000)), self.typographic,
                                  ctypes.byref(box), None, None)
        return box.w

    def draw_text(self, g, cfg: dict, lines: list, lit: bool, ox: float, oy: float):
        gp = self.gp
        gp.GdipSetSmoothingMode(g, SMOOTH)
        gp.GdipSetTextRenderingHint(g, TEXT_SMOOTH)
        parts, boxes = self.text_layout(cfg, lines)
        for spot, (x0, y0, x1, y1) in boxes:  # backgrounds and frames first, see-through as asked
            pad = BLOCK_PAD + spot["frame"]
            if spot["background"]:
                brush = P()
                gp.GdipCreateSolidFill(argb(spot["background"], round(255 * spot["bgOpacity"] / 100)), ctypes.byref(brush))
                gp.GdipFillRectangle(g, brush, x0 - pad - ox, y0 - pad - oy, x1 - x0 + 2 * pad, y1 - y0 + 2 * pad)
                gp.GdipDeleteBrush(brush)
            if spot["frame"]:
                pen = P()
                gp.GdipCreatePen1(argb(spot["frameColor"]), F(spot["frame"]), UNIT_PIXEL, ctypes.byref(pen))
                gp.GdipDrawRectangle(g, pen, x0 - pad + spot["frame"] / 2 - ox, y0 - pad + spot["frame"] / 2 - oy,
                                     x1 - x0 + 2 * pad - spot["frame"], y1 - y0 + 2 * pad - spot["frame"])
                gp.GdipDeletePen(pen)
        outline = cfg["outline"]
        for x, y, text, tint, size, blinks, off in parts:  # lit: a bool, or the clock of what flashes (alarms.Watch.lit)
            if blinks and not (lit(blinks) if callable(lit) else lit):
                if not off:  # nothing else to show: hidden out of its turn
                    continue
                tint = off  # its colour out of its turn: the value stays readable, no jump when it comes back
            if not text.strip():
                continue
            _, family, style, _ = self._text_font(cfg, size)
            path, brush = P(), P()
            gp.GdipCreatePath(0, ctypes.byref(path))
            gp.GdipAddPathString(path, text, len(text), family, style, F(max(1, round(size))), ctypes.byref(RectF(x - ox, y - oy, 0, 0)), self.typographic)
            if outline:  # the outline asked, round at the corners
                pen = P()
                gp.GdipCreatePen1(argb(cfg["outlineColor"]), F(2 * outline), UNIT_PIXEL, ctypes.byref(pen))
                gp.GdipSetPenLineJoin(pen, 2)
                gp.GdipDrawPath(g, pen, path)
                gp.GdipDeletePen(pen)
            else:  # none asked: a soft dark halo, so that light text reads on a light sky and still on a dark one
                pen = P()
                gp.GdipCreatePen1(HALO, F(2 * HALO_PX), UNIT_PIXEL, ctypes.byref(pen))
                gp.GdipSetPenLineJoin(pen, 2)
                gp.GdipDrawPath(g, pen, path)
                gp.GdipDeletePen(pen)
            gp.GdipCreateSolidFill(argb(tint), ctypes.byref(brush))
            gp.GdipFillPath(g, brush, path)
            gp.GdipDeleteBrush(brush)
            gp.GdipDeletePath(path)

    def text_pixels(self, cfg: dict, lines: list, lit: bool = True) -> tuple:
        """The text as premultiplied BGRA and its box: for the tests."""
        box = self.text_box(cfg, lines)
        return self._pixels(lambda g: self.draw_text(g, cfg, lines, lit, box[0], box[1]), box[2], box[3]), box

    def paint_text(self, hwnd: int, cfg: dict, lines: list, lit: bool) -> bool:
        """The overlay's text blocks into their layered window; False when there's nothing to show."""
        box = self.text_box(cfg, lines)
        if not box:
            return False
        return self._layered(hwnd, lambda g: self.draw_text(g, cfg, lines, lit, box[0], box[1]), *box, cfg["opacity"] / 100)
