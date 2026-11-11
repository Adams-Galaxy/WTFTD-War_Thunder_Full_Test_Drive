"""The overlay painted by cairo (Linux), into the X11 windows of x11.Layer: the minimap, the text blocks, the HUD and
the glow, the same shapes at the same places as mappaint (GDI+) and Tk paint them on Windows. cairo through ctypes
(libcairo, part of every Linux desktop); a map the game sends as JPEG is read by gdk-pixbuf, a PNG by cairo itself.
Into a window, each picture is drawn off screen first and then replaces the old one at once: no flicker."""
from __future__ import annotations

import ctypes
import math

from . import x11
from .mappaint import BLOCK_PAD, EDGE, EDGE_PX, HALO, HALO_PX, MOST, Layout

P, D, INT = ctypes.c_void_p, ctypes.c_double, ctypes.c_int
ARGB32, COLOR_ALPHA = 0, 0x3000
CLEAR, SOURCE, OVER, DEST_IN = 0, 1, 2, 8  # cairo_operator_t
GOOD, BILINEAR = 1, 4  # cairo_filter_t
ROUND = 1  # cairo_line_join_t
READ_ERROR = 10  # cairo_status_t
MONO = ("Consolas", "Cascadia Mono", "Lucida Console")  # Windows' fixed-width fonts: fontconfig would give a proportional one
HUD_PAD = 8  # round the HUD's shapes, what is cleared and drawn again


class Matrix(ctypes.Structure):  # cairo_matrix_t
    _fields_ = [(n, D) for n in ("xx", "yx", "xy", "yy", "x0", "y0")]


class TextExtents(ctypes.Structure):
    _fields_ = [(n, D) for n in ("x_bearing", "y_bearing", "width", "height", "x_advance", "y_advance")]


class FontExtents(ctypes.Structure):
    _fields_ = [(n, D) for n in ("ascent", "descent", "height", "max_x_advance", "max_y_advance")]


READ = ctypes.CFUNCTYPE(INT, P, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint)
SIGNATURES = {  # name: (restype, argtypes)
    "cairo_image_surface_create": (P, [INT, INT, INT]),
    "cairo_image_surface_create_for_data": (P, [P, INT, INT, INT, INT]),
    "cairo_image_surface_create_from_png_stream": (P, [READ, P]),
    "cairo_image_surface_get_data": (P, [P]), "cairo_image_surface_get_stride": (INT, [P]),
    "cairo_image_surface_get_width": (INT, [P]), "cairo_image_surface_get_height": (INT, [P]),
    "cairo_surface_create_similar": (P, [P, INT, INT, INT]), "cairo_surface_status": (INT, [P]),
    "cairo_surface_destroy": (None, [P]), "cairo_surface_flush": (None, [P]), "cairo_surface_mark_dirty": (None, [P]),
    "cairo_xlib_surface_create": (P, [P, ctypes.c_ulong, P, INT, INT]), "cairo_xlib_surface_set_size": (None, [P, INT, INT]),
    "cairo_create": (P, [P]), "cairo_destroy": (None, [P]), "cairo_save": (None, [P]), "cairo_restore": (None, [P]),
    "cairo_set_operator": (None, [P, INT]), "cairo_set_source_rgba": (None, [P, D, D, D, D]),
    "cairo_set_source_surface": (None, [P, P, D, D]), "cairo_get_source": (P, [P]), "cairo_pattern_set_filter": (None, [P, INT]),
    "cairo_paint": (None, [P]), "cairo_paint_with_alpha": (None, [P, D]),
    "cairo_push_group": (None, [P]), "cairo_pop_group_to_source": (None, [P]),
    "cairo_new_path": (None, [P]), "cairo_close_path": (None, [P]), "cairo_move_to": (None, [P, D, D]),
    "cairo_line_to": (None, [P, D, D]), "cairo_arc": (None, [P, D, D, D, D, D]), "cairo_rectangle": (None, [P, D, D, D, D]),
    "cairo_stroke": (None, [P]), "cairo_fill": (None, [P]), "cairo_stroke_preserve": (None, [P]), "cairo_clip": (None, [P]),
    "cairo_set_line_width": (None, [P, D]), "cairo_set_line_join": (None, [P, INT]),
    "cairo_transform": (None, [P, ctypes.POINTER(Matrix)]), "cairo_scale": (None, [P, D, D]), "cairo_translate": (None, [P, D, D]),
    "cairo_select_font_face": (None, [P, ctypes.c_char_p, INT, INT]), "cairo_set_font_size": (None, [P, D]),
    "cairo_text_extents": (None, [P, ctypes.c_char_p, ctypes.POINTER(TextExtents)]),
    "cairo_font_extents": (None, [P, ctypes.POINTER(FontExtents)]), "cairo_text_path": (None, [P, ctypes.c_char_p]),
}


def available() -> bool:
    try:
        ctypes.CDLL("libcairo.so.2")
        return True
    except OSError:
        return False


def rgba(color: str, alpha: float = 1.0) -> tuple:
    return int(color[1:3], 16) / 255, int(color[3:5], 16) / 255, int(color[5:7], 16) / 255, alpha


def argb(value: int) -> tuple:
    """mappaint's 0xAARRGGBB."""
    return (value >> 16 & 255) / 255, (value >> 8 & 255) / 255, (value & 255) / 255, (value >> 24) / 255


def hud_box(shapes: list) -> tuple | None:
    """What the HUD's shapes cover, (x0, y0, x1, y1), a text's width guessed on the large side."""
    xs, ys = [], []
    for s in shapes:
        if s[0] == "l":
            xs += [s[1], s[3]]
            ys += [s[2], s[4]]
        elif s[0] == "t":
            reach = len(s[3]) * s[4]
            xs += [s[1] - reach, s[1] + reach]
            ys += [s[2] - s[4], s[2] + s[4]]
        elif s[0] == "p":
            xs += s[1][0::2]
            ys += s[1][1::2]
        else:
            xs += [s[1] - s[3], s[1] + s[3]]
            ys += [s[2] - s[3], s[2] + s[3]]
    return (min(xs) - HUD_PAD, min(ys) - HUD_PAD, max(xs) + HUD_PAD, max(ys) + HUD_PAD) if xs else None


class Painter(Layout):
    """cairo loaded once for the overlay's thread; the map picture read once per map."""

    def __init__(self):
        self.c = ctypes.CDLL("libcairo.so.2")
        for name, (restype, argtypes) in SIGNATURES.items():
            fn = getattr(self.c, name)
            fn.restype, fn.argtypes = restype, argtypes
        self.image, self.image_key, self.image_size = None, None, (0, 0)
        self.scaled, self.scaled_key = None, None  # the picture at the minimap's scale: each image only turns it
        self.measurer = self.c.cairo_image_surface_create(ARGB32, 1, 1)
        self.measuring = self.c.cairo_create(self.measurer)
        self.hud_drawn = None  # where the HUD was last drawn: cleared at the next image

    def close(self, layers=()):
        """Frees what it made, the layers' surfaces too: before their X connection closes."""
        for surface in (self.image, self.scaled, *(layer.surface for layer in layers), self.measurer):
            if surface:
                self.c.cairo_surface_destroy(surface)
        self.c.cairo_destroy(self.measuring)
        self.image = self.scaled = None
        for layer in layers:
            layer.surface = None

    # ---------------------------------------------------------------- the map picture

    def load(self, data: bytes | None, key) -> bool:
        """The map's picture from the game's answer in memory; False when there's none it can read."""
        if (key, data is not None) != self.image_key:
            for old in (self.image, self.scaled):
                if old:
                    self.c.cairo_surface_destroy(old)
            self.image, self.image_key, self.scaled, self.scaled_key = None, (key, data is not None), None, None
            self.image = (self._png(data) if data[:8] == b"\x89PNG\r\n\x1a\n" else self._decoded(data)) if data else None
            if self.image:
                self.image_size = self.c.cairo_image_surface_get_width(self.image), self.c.cairo_image_surface_get_height(self.image)
        return self.image is not None

    def _png(self, data: bytes):
        at = [0]

        @READ
        def read(_, buffer, length):
            chunk = data[at[0]:at[0] + length]
            if len(chunk) < length:
                return READ_ERROR
            ctypes.memmove(buffer, chunk, length)
            at[0] += length
            return 0

        surface = self.c.cairo_image_surface_create_from_png_stream(read, None)
        if self.c.cairo_surface_status(surface):
            self.c.cairo_surface_destroy(surface)
            return None
        return surface

    def _decoded(self, data: bytes):
        """A JPEG (any format gdk-pixbuf reads) into a cairo picture: RGB(A) rows into its B, G, R, A."""
        try:
            gp, go = ctypes.CDLL("libgdk_pixbuf-2.0.so.0"), ctypes.CDLL("libgobject-2.0.so.0")
        except OSError:
            return None
        gp.gdk_pixbuf_loader_new.restype = P
        gp.gdk_pixbuf_loader_write.argtypes = [P, ctypes.c_char_p, ctypes.c_size_t, P]
        gp.gdk_pixbuf_loader_close.argtypes = [P, P]
        gp.gdk_pixbuf_loader_get_pixbuf.argtypes, gp.gdk_pixbuf_loader_get_pixbuf.restype = [P], P
        for name in ("width", "height", "rowstride", "n_channels"):
            getattr(gp, f"gdk_pixbuf_get_{name}").argtypes = [P]
        gp.gdk_pixbuf_get_pixels.argtypes, gp.gdk_pixbuf_get_pixels.restype = [P], P
        go.g_object_unref.argtypes = [P]
        loader = gp.gdk_pixbuf_loader_new()
        try:
            done = gp.gdk_pixbuf_loader_write(loader, data, len(data), None)
            done = gp.gdk_pixbuf_loader_close(loader, None) and done
            pixbuf = gp.gdk_pixbuf_loader_get_pixbuf(loader) if done else None  # the loader's: freed with it
            if not pixbuf:
                return None
            w, h, stride, n = (getattr(gp, f"gdk_pixbuf_get_{k}")(pixbuf) for k in ("width", "height", "rowstride", "n_channels"))
            src = ctypes.string_at(gp.gdk_pixbuf_get_pixels(pixbuf), stride * (h - 1) + w * n)
            surface = self.c.cairo_image_surface_create(ARGB32, w, h)
            out, row = self.c.cairo_image_surface_get_data(surface), self.c.cairo_image_surface_get_stride(surface)
            line = bytearray(w * 4)
            for y in range(h):
                pixels = src[y * stride:y * stride + w * n]
                line[0::4], line[1::4], line[2::4] = pixels[2::n], pixels[1::n], pixels[0::n]
                line[3::4] = pixels[3::n] if n == 4 else b"\xff" * w  # shortcut: alpha not premultiplied, maps are opaque
                ctypes.memmove(out + y * row, bytes(line), w * 4)
            self.c.cairo_surface_mark_dirty(surface)
            return surface
        finally:
            go.g_object_unref(loader)

    def _scaled(self, target, k: float):
        """The map picture k pixels across (its own size at most), made once for a zoom: on the X server for a window."""
        n = max(1, min(round(k), self.image_size[0], MOST))
        if self.scaled_key != (n, target):
            if self.scaled:
                self.c.cairo_surface_destroy(self.scaled)
            c = self.c
            self.scaled = c.cairo_surface_create_similar(target, COLOR_ALPHA, n, n)
            cr = c.cairo_create(self.scaled)
            c.cairo_scale(cr, n / self.image_size[0], n / self.image_size[1])
            c.cairo_set_source_surface(cr, self.image, 0, 0)
            c.cairo_pattern_set_filter(c.cairo_get_source(cr), GOOD)
            c.cairo_paint(cr)
            c.cairo_destroy(cr)
            self.scaled_key = (n, target)
        return self.scaled, n

    # ---------------------------------------------------------------- shapes

    def _font(self, cr, family: str, size: float, bold: bool = True, italic: bool = False):
        self.c.cairo_select_font_face(cr, ("monospace" if family in MONO else family).encode(), int(italic), int(bold))
        self.c.cairo_set_font_size(cr, max(1, round(size)))

    def _path(self, cr, s: list, ox: float, oy: float):
        c = self.c
        c.cairo_new_path(cr)
        if s[0] == "l":
            c.cairo_move_to(cr, s[1] - ox, s[2] - oy)
            c.cairo_line_to(cr, s[3] - ox, s[4] - oy)
        elif s[0] == "c":
            c.cairo_arc(cr, s[1] - ox, s[2] - oy, s[3], 0, 2 * math.pi)
        else:
            c.cairo_move_to(cr, s[1][0] - ox, s[1][1] - oy)
            for i in range(2, len(s[1]), 2):
                c.cairo_line_to(cr, s[1][i] - ox, s[1][i + 1] - oy)
            c.cairo_close_path(cr)

    def _shape(self, cr, s: list, ox: float, oy: float, tint: tuple, outline: float = 1.8):
        """A shape of hud.draw's or minimap.draw's: line, circle, polygon (filled or not), text in Consolas bold whose y
        is its middle (Chinese in a font that has it)."""
        c = self.c
        c.cairo_set_source_rgba(cr, *tint)
        if s[0] == "t":
            text = s[3].encode()
            self._font(cr, "Noto Sans CJK SC" if any(ord(ch) > 0x2E80 for ch in s[3]) else "Consolas", max(6, round(s[4])))
            ext, fe = TextExtents(), FontExtents()
            c.cairo_text_extents(cr, text, ctypes.byref(ext))
            c.cairo_font_extents(cr, ctypes.byref(fe))
            x = s[1] - ox - {"w": 0, "m": ext.x_advance / 2, "e": ext.x_advance}[s[5]]
            c.cairo_new_path(cr)
            c.cairo_move_to(cr, x, s[2] - oy + (fe.ascent - fe.descent) / 2)
            c.cairo_text_path(cr, text)
            c.cairo_fill(cr)
            return
        self._path(cr, s, ox, oy)
        if s[0] == "p" and s[2]:
            c.cairo_fill(cr)
            return
        c.cairo_set_line_width(cr, s[5] if s[0] == "l" else outline)
        c.cairo_stroke(cr)

    def _edge(self, cr, s: list, ox: float, oy: float):
        """A dark edge under a mark, a little wider than it."""
        if s[0] == "t":
            return
        self._path(cr, s, ox, oy)
        self.c.cairo_set_source_rgba(cr, *argb(EDGE))
        self.c.cairo_set_line_width(cr, (s[5] if s[0] == "l" else 1.8) + 2 * EDGE_PX)
        self.c.cairo_stroke(cr)

    # ---------------------------------------------------------------- the minimap

    def draw(self, cr, frame: dict, ox: float, oy: float, target=None):
        """The minimap into a cairo context whose (0, 0) is the screen's (ox, oy); target: the surface it draws on."""
        c, (left, top, size) = self.c, frame["box"]
        r, mid_x, mid_y = size / 2, left + size / 2 - ox, top + size / 2 - oy
        c.cairo_save(cr)
        c.cairo_translate(cr, 0.5, 0.5)  # a pixel's middle where GDI+ has it: cairo's pixel x spans x to x + 1
        c.cairo_save(cr)
        c.cairo_new_path(cr)
        if frame["round"]:
            c.cairo_arc(cr, mid_x, mid_y, r, 0, 2 * math.pi)
        else:
            c.cairo_rectangle(cr, mid_x - r, mid_y - r, size, size)
        c.cairo_clip(cr)
        c.cairo_set_source_rgba(cr, *rgba("#141A22"))
        c.cairo_paint(cr)  # under the picture, and where the map ends when it turns
        pic = frame["picture"]
        if self.image and pic:  # image pixel (u, v) -> share of the map (u/W, v/H) -> the screen, turned around the centre
            (picture, n), k, t = self._scaled(target or self.measurer, pic["k"]), pic["k"], math.radians(pic["turn"])
            cos, sin, a = math.cos(t), math.sin(t), k / n
            m = Matrix(a * cos, -a * sin, a * sin, a * cos, mid_x - pic["cx"] * k * cos - pic["cy"] * k * sin,
                       mid_y + pic["cx"] * k * sin - pic["cy"] * k * cos)
            c.cairo_save(cr)
            c.cairo_transform(cr, ctypes.byref(m))
            c.cairo_set_source_surface(cr, picture, 0, 0)
            c.cairo_pattern_set_filter(c.cairo_get_source(cr), BILINEAR)
            c.cairo_paint(cr)
            c.cairo_restore(cr)
            if frame.get("dim"):  # the map darkened, so that the marks read on it
                c.cairo_set_source_rgba(cr, 0, 0, 0, frame["dim"] / 100)
                c.cairo_paint(cr)
        for shape in frame["marks"]:
            self._edge(cr, shape, ox, oy)
            self._shape(cr, shape, ox, oy, rgba(shape[-1]))
        c.cairo_restore(cr)
        for shape in frame["frame"]:
            self._shape(cr, shape, ox, oy, rgba(shape[-1]))
        c.cairo_restore(cr)

    def pixels(self, frame: dict, width: int, height: int, ox: float, oy: float) -> bytes:
        """The minimap as premultiplied BGRA, top row first, as mappaint's: for the tests."""
        return self._pixels(lambda cr, target: self.draw(cr, frame, ox, oy, target), width, height)

    def _pixels(self, draw, width: int, height: int) -> bytes:
        c = self.c
        surface = c.cairo_image_surface_create(ARGB32, width, height)
        cr = c.cairo_create(surface)
        try:
            draw(cr, surface)
            c.cairo_surface_flush(surface)
            stride = c.cairo_image_surface_get_stride(surface)
            raw = ctypes.string_at(c.cairo_image_surface_get_data(surface), stride * height)
            return b"".join(raw[y * stride:y * stride + width * 4] for y in range(height))
        finally:
            c.cairo_destroy(cr)
            c.cairo_surface_destroy(surface)

    def paint(self, layer, frame: dict, opacity: float, origin: tuple = (0, 0)) -> bool:
        """The minimap into its window, which takes the place and size of the minimap and its words below."""
        left, top, size = frame["box"]
        ox, oy, width, height = int(left) - 2, int(top) - 2, max(int(size), 240) + 4, int(size) + 34
        self.present(layer, (ox + origin[0], oy + origin[1], width, height), lambda cr, t: self.draw(cr, frame, ox, oy, t), opacity)
        return True

    # ---------------------------------------------------------------- into a window

    def surface(self, layer):
        """The layer's cairo surface: a pixmap as big as its window, made again when the window's size changes, see-through
        until drawn (a new pixmap holds anything), set as the window's background."""
        c, x, size = self.c, x11.lib(), layer.box[2:]
        if layer.surface and layer.size == size:
            return layer.surface
        if layer.surface:
            c.cairo_surface_destroy(layer.surface)
            x.XFreePixmap(layer.d, layer.pixmap)
        layer.pixmap, layer.size = x.XCreatePixmap(layer.d, layer.window, *size, 32), size
        layer.surface = c.cairo_xlib_surface_create(layer.d, layer.pixmap, layer.visual, *size)
        cr = c.cairo_create(layer.surface)
        c.cairo_set_operator(cr, CLEAR)
        c.cairo_paint(cr)
        c.cairo_destroy(cr)
        x.XSetWindowBackgroundPixmap(layer.d, layer.window, layer.pixmap)
        return layer.surface

    def present(self, layer, box: tuple, draw, opacity: float, clip: tuple | None = None):
        """A window's new picture: placed, drawn off screen (draw(cr, target)), its opacity applied, then copied over the
        old one in one go; clip (x0, y0, x1, y1, in the window): only that part changes."""
        c = self.c
        layer.place(box)
        surface = self.surface(layer)
        cr = c.cairo_create(surface)
        if clip:
            c.cairo_rectangle(cr, clip[0], clip[1], clip[2] - clip[0], clip[3] - clip[1])
            c.cairo_clip(cr)
        c.cairo_push_group(cr)
        draw(cr, surface)
        if opacity < 1:
            c.cairo_set_operator(cr, DEST_IN)
            c.cairo_set_source_rgba(cr, 0, 0, 0, opacity)
            c.cairo_paint(cr)
        c.cairo_pop_group_to_source(cr)
        c.cairo_set_operator(cr, SOURCE)
        c.cairo_paint(cr)
        c.cairo_destroy(cr)
        c.cairo_surface_flush(surface)
        x0, y0 = (max(0, int(clip[0])), max(0, int(clip[1]))) if clip else (0, 0)
        layer.refresh((x0, y0, math.ceil(clip[2]) - x0, math.ceil(clip[3]) - y0) if clip else (0, 0, 0, 0))

    def paint_hud(self, layer, cfg: dict, shapes: list, lit: bool, size: tuple, origin: tuple = (0, 0)):
        """The HUD, on a window as big as the screen (it moves at every image, the window mustn't): only where it was and
        where it is are drawn again. Its alert shows in the alert colour, flashing with the lines, as Tk's."""
        box, before = hud_box(shapes), self.hud_drawn
        self.hud_drawn = box
        dirty = [b for b in (box, before) if b]
        if not dirty:
            return
        clip = (min(b[0] for b in dirty), min(b[1] for b in dirty), max(b[2] for b in dirty), max(b[3] for b in dirty))

        self.present(layer, (origin[0], origin[1], *size), lambda cr, _: self.draw_hud(cr, cfg, shapes, lit), cfg["opacity"] / 100, clip)

    def draw_hud(self, cr, cfg: dict, shapes: list, lit: bool):
        self.c.cairo_save(cr)
        self.c.cairo_translate(cr, 0.5, 0.5)  # a pixel's middle where Tk has it
        for s in shapes:  # the minimap's carry their colour
            tint = s[-1] if isinstance(s[-1], str) else cfg["alert"] if s[-1] and lit else cfg["hudColor"]
            self._shape(cr, s, 0, 0, rgba(tint), 1.6 if s[0] == "p" else 1.8)
        self.c.cairo_restore(cr)

    def hud_pixels(self, cfg: dict, shapes: list, lit: bool, width: int, height: int) -> bytes:
        """The HUD as premultiplied BGRA: for the tests."""
        return self._pixels(lambda cr, _: self.draw_hud(cr, cfg, shapes, lit), width, height)

    def paint_glow(self, layer, size: tuple, pixels: bytes, origin: tuple = (0, 0)):
        """The glow (alarms.glow_pixels' premultiplied BGRA, as big as the screen) into its window, once per colour."""
        c, (width, height) = self.c, size
        buffer = ctypes.create_string_buffer(pixels, len(pixels))
        picture = c.cairo_image_surface_create_for_data(buffer, ARGB32, width, height, width * 4)

        def draw(cr, _):
            c.cairo_set_source_surface(cr, picture, 0, 0)
            c.cairo_paint(cr)

        try:
            self.present(layer, (origin[0], origin[1], width, height), draw, 1.0)
        finally:
            c.cairo_surface_destroy(picture)

    # ---------------------------------------------------------------- the overlay's text blocks

    def _text_font(self, cfg: dict, size: float):
        """((family, bold, italic, size), ..., the line's height), as mappaint's: Layout lays the text out with it."""
        key = cfg["font"], bool(cfg["bold"]), bool(cfg["italic"]), max(1, round(size))
        fe = FontExtents()
        self._font(self.measuring, cfg["font"], key[3], key[1], key[2])
        self.c.cairo_font_extents(self.measuring, ctypes.byref(fe))
        return key, cfg["font"], None, fe.height

    def _width(self, text: str, font) -> float:
        ext = TextExtents()
        self._font(self.measuring, font[0], font[3], font[1], font[2])
        self.c.cairo_text_extents(self.measuring, text.encode(), ctypes.byref(ext))
        return ext.x_advance

    def draw_text(self, cr, cfg: dict, lines: list, lit, ox: float, oy: float):
        c = self.c
        parts, boxes = self.text_layout(cfg, lines)
        for spot, (x0, y0, x1, y1) in boxes:  # backgrounds and frames first, see-through as asked
            pad = BLOCK_PAD + spot["frame"]
            if spot["background"]:
                c.cairo_rectangle(cr, x0 - pad - ox, y0 - pad - oy, x1 - x0 + 2 * pad, y1 - y0 + 2 * pad)
                c.cairo_set_source_rgba(cr, *rgba(spot["background"], spot["bgOpacity"] / 100))
                c.cairo_fill(cr)
            if spot["frame"]:
                c.cairo_rectangle(cr, x0 - pad + spot["frame"] / 2 - ox, y0 - pad + spot["frame"] / 2 - oy,
                                  x1 - x0 + 2 * pad - spot["frame"], y1 - y0 + 2 * pad - spot["frame"])
                c.cairo_set_source_rgba(cr, *rgba(spot["frameColor"]))
                c.cairo_set_line_width(cr, spot["frame"])
                c.cairo_stroke(cr)
        outline = cfg["outline"]
        for x, y, text, tint, size, blinks, off in parts:  # lit: a bool, or the clock of what flashes (alarms.Watch.lit)
            if blinks and not (lit(blinks) if callable(lit) else lit):
                if not off:  # nothing else to show: hidden out of its turn
                    continue
                tint = off  # its colour out of its turn: the value stays readable, no jump when it comes back
            if not text.strip():
                continue
            fe = FontExtents()
            self._font(cr, cfg["font"], size, cfg["bold"], cfg["italic"])
            c.cairo_font_extents(cr, ctypes.byref(fe))
            c.cairo_new_path(cr)
            c.cairo_move_to(cr, x - ox, y - oy + fe.ascent)  # GDI+ puts the line's top at y
            c.cairo_text_path(cr, text.encode())
            c.cairo_set_line_join(cr, ROUND)
            if outline:  # the outline asked, round at the corners
                c.cairo_set_source_rgba(cr, *rgba(cfg["outlineColor"]))
                c.cairo_set_line_width(cr, 2 * outline)
            else:  # none asked: a soft dark halo, so that light text reads on a light sky and still on a dark one
                c.cairo_set_source_rgba(cr, *argb(HALO))
                c.cairo_set_line_width(cr, 2 * HALO_PX)
            c.cairo_stroke_preserve(cr)
            c.cairo_set_source_rgba(cr, *rgba(tint))
            c.cairo_fill(cr)

    def text_pixels(self, cfg: dict, lines: list, lit: bool = True) -> tuple:
        """The text as premultiplied BGRA and its box: for the tests."""
        box = self.text_box(cfg, lines)
        return self._pixels(lambda cr, _: self.draw_text(cr, cfg, lines, lit, box[0], box[1]), box[2], box[3]), box

    def paint_text(self, layer, cfg: dict, lines: list, lit, origin: tuple = (0, 0)) -> bool:
        """The overlay's text blocks into their window; False when there's nothing to show. The window only grows while
        its corner stays: a value one digit longer doesn't resize it at every reading."""
        box = self.text_box(cfg, lines)
        if not box:
            return False
        x, y = box[0] + origin[0], box[1] + origin[1]
        w, h = (max(box[2], layer.box[2]), max(box[3], layer.box[3])) if layer.box[:2] == (x, y) else box[2:]
        self.present(layer, (x, y, w, h), lambda cr, _: self.draw_text(cr, cfg, lines, lit, box[0], box[1]), cfg["opacity"] / 100)
        return True
