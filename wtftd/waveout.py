"""Plays a .wav held in memory on the sound output the player picked (Windows): the standard library's PlaySound only
knows the default one. waveOut is the oldest of Windows' sound APIs and still the simplest that can choose."""
from __future__ import annotations

import ctypes
import io
import time
import wave
from ctypes import wintypes as w

WAVE_MAPPER = 0xFFFFFFFF  # Windows' default output
WHDR_DONE = 1
WHDR_BEGINLOOP, WHDR_ENDLOOP = 4, 8
FOREVER = 0xFFFFFFFF  # loops: as good as for ever, Loop.stop ends it


class Format(ctypes.Structure):  # WAVEFORMATEX
    _pack_ = 1
    _fields_ = [("tag", w.WORD), ("channels", w.WORD), ("rate", w.DWORD), ("bytes_s", w.DWORD), ("align", w.WORD),
                ("bits", w.WORD), ("extra", w.WORD)]


class Header(ctypes.Structure):  # WAVEHDR
    _fields_ = [("data", ctypes.c_char_p), ("length", w.DWORD), ("recorded", w.DWORD), ("user", ctypes.c_size_t),
                ("flags", w.DWORD), ("loops", w.DWORD), ("next", ctypes.c_void_p), ("reserved", ctypes.c_size_t)]


class Caps(ctypes.Structure):  # WAVEOUTCAPSW
    _fields_ = [("mid", w.WORD), ("pid", w.WORD), ("version", w.UINT), ("name", w.WCHAR * 32), ("formats", w.DWORD),
                ("channels", w.WORD), ("reserved", w.WORD), ("support", w.DWORD)]


def _winmm():
    mm = ctypes.WinDLL("winmm")
    mm.waveOutGetNumDevs.restype = w.UINT
    mm.waveOutGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(Caps), w.UINT]
    mm.waveOutOpen.argtypes = [ctypes.POINTER(w.HANDLE), w.UINT, ctypes.POINTER(Format), ctypes.c_size_t, ctypes.c_size_t, w.DWORD]
    for name in ("waveOutPrepareHeader", "waveOutWrite", "waveOutUnprepareHeader"):
        getattr(mm, name).argtypes = [w.HANDLE, ctypes.POINTER(Header), w.UINT]
    mm.waveOutReset.argtypes = mm.waveOutClose.argtypes = [w.HANDLE]
    return mm


def devices() -> list:
    """The sound outputs' names: what settings keep, numbers change when a headset is plugged in. Windows cuts them at 31
    characters."""
    try:
        mm, out = _winmm(), []
    except (AttributeError, OSError):  # not Windows
        return []
    for i in range(mm.waveOutGetNumDevs()):
        caps = Caps()
        if not mm.waveOutGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)):
            out.append(caps.name)
    return out


def _open(data: bytes, device: str):
    """(winmm, handle, frames, format) of a .wav on this output, else on the default one; None if it can't."""
    try:
        with wave.open(io.BytesIO(data), "rb") as sound:
            params, frames = sound.getparams(), sound.readframes(sound.getnframes())
        names, mm = devices(), _winmm()
    except (AttributeError, OSError, EOFError, wave.Error):
        return None
    align = params.nchannels * params.sampwidth
    fmt = Format(1, params.nchannels, params.framerate, params.framerate * align, align, params.sampwidth * 8, 0)
    handle = w.HANDLE()
    if mm.waveOutOpen(ctypes.byref(handle), names.index(device) if device in names else WAVE_MAPPER, ctypes.byref(fmt), 0, 0, 0):
        return None
    return mm, handle, frames, fmt


class Loop:
    """A .wav played over and over, without a gap, until stop(): waveOut loops the buffer itself. Nothing if it can't."""

    def __init__(self, data: bytes, device: str = ""):
        self.opened = _open(data, device)
        if not self.opened:
            return
        mm, handle, self.frames, _ = self.opened  # the frames stay here while the device reads them
        self.head, size = Header(self.frames, len(self.frames)), ctypes.sizeof(Header)
        mm.waveOutPrepareHeader(handle, ctypes.byref(self.head), size)
        self.head.flags |= WHDR_BEGINLOOP | WHDR_ENDLOOP
        self.head.loops = FOREVER
        if mm.waveOutWrite(handle, ctypes.byref(self.head), size):
            self.stop()

    def stop(self):
        if self.opened:
            mm, handle, _, _ = self.opened
            self.opened = None
            mm.waveOutReset(handle)
            mm.waveOutUnprepareHeader(handle, ctypes.byref(self.head), ctypes.sizeof(Header))
            mm.waveOutClose(handle)


def play(data: bytes, device: str = "") -> bool:
    """Plays a .wav to its end, on this output if it's still there, else on the default one. False if it couldn't."""
    opened = _open(data, device)
    if not opened:
        return False
    mm, handle, frames, fmt = opened
    head = Header(frames, len(frames))
    size = ctypes.sizeof(head)
    try:
        mm.waveOutPrepareHeader(handle, ctypes.byref(head), size)
        if mm.waveOutWrite(handle, ctypes.byref(head), size):
            return False
        end = time.monotonic() + len(frames) / fmt.bytes_s + 1  # a driver that never answers doesn't hold the alarms up
        while not head.flags & WHDR_DONE and time.monotonic() < end:
            time.sleep(0.005)
        return bool(head.flags & WHDR_DONE)
    finally:
        mm.waveOutReset(handle)
        mm.waveOutUnprepareHeader(handle, ctypes.byref(head), size)
        mm.waveOutClose(handle)
