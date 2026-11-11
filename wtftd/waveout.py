"""Plays a .wav held in memory on the sound output the player picked: the standard library's PlaySound only knows the
default one. Windows: waveOut, the oldest of its sound APIs and still the simplest that can choose. Linux: PulseAudio's
simple API, which PipeWire serves too (outputs listed by pactl), else ALSA's aplay on the default output."""
from __future__ import annotations

import ctypes
import io
import json
import subprocess
import sys
import threading
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
    characters; Linux gives their descriptions, as its sound settings show them."""
    if sys.platform != "win32":
        _SINKS.clear()
        _SINKS.update(_sinks())
        return list(_SINKS)
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
    """A .wav played over and over, without a gap, until stop(): waveOut loops the buffer itself, on Linux a thread feeds
    the stream. Nothing if it can't."""

    def __init__(self, data: bytes, device: str = ""):
        self.linux = _Repeat(data, device) if sys.platform != "win32" else None
        self.opened = _open(data, device) if not self.linux else None
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
        if self.linux:
            self.linux.stop()
        if self.opened:
            mm, handle, _, _ = self.opened
            self.opened = None
            mm.waveOutReset(handle)
            mm.waveOutUnprepareHeader(handle, ctypes.byref(self.head), ctypes.sizeof(Header))
            mm.waveOutClose(handle)


def play(data: bytes, device: str = "") -> bool:
    """Plays a .wav to its end, on this output if it's still there, else on the default one. False if it couldn't."""
    if sys.platform != "win32":
        out, frames, _ = _output(data, device) or (None, b"", None)
        if not out:
            return False
        done = out.write(frames)
        out.close(drain=done)
        return done
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


# ------------------------------------------------------------------------------------------------------------- Linux
_SINKS: dict = {}  # an output's description -> its name, as pactl last listed them
PULSE_FORMATS = {1: 0, 2: 3, 3: 9, 4: 7}  # bytes a sample -> pa_sample_format_t: U8, S16LE, S24LE, S32LE
ALSA_FORMATS = {1: "U8", 2: "S16_LE", 3: "S24_3LE", 4: "S32_LE"}
CHUNK_S = 0.05  # written this much at a time: a loop stops within it


class SampleSpec(ctypes.Structure):  # pa_sample_spec
    _fields_ = [("format", ctypes.c_int), ("rate", ctypes.c_uint32), ("channels", ctypes.c_uint8)]


class BufferAttr(ctypes.Structure):  # pa_buffer_attr
    _fields_ = [(n, ctypes.c_uint32) for n in ("maxlength", "tlength", "prebuf", "minreq", "fragsize")]


def _sinks() -> list:
    """Linux: the outputs PulseAudio or PipeWire has, as (description, name); none without pactl."""
    try:
        listed = json.loads(subprocess.run(["pactl", "--format=json", "list", "sinks"], capture_output=True, timeout=5, check=True).stdout)
        return [(s.get("description") or s["name"], s["name"]) for s in listed]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, AttributeError):
        return []


def _sink(device: str) -> str | None:
    if device and device not in _SINKS:
        devices()
    return _SINKS.get(device)


class _Pulse:
    """A playback stream on PulseAudio's simple API; its buffer holds a tenth of a second, so that a loop stops at once."""

    def __init__(self, params, sink: str | None):
        lib = ctypes.CDLL("libpulse-simple.so.0")
        lib.pa_simple_new.restype = ctypes.c_void_p
        lib.pa_simple_new.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
                                      ctypes.POINTER(SampleSpec), ctypes.c_void_p, ctypes.POINTER(BufferAttr), ctypes.POINTER(ctypes.c_int)]
        lib.pa_simple_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p]
        lib.pa_simple_drain.argtypes = lib.pa_simple_flush.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.pa_simple_free.argtypes = [ctypes.c_void_p]
        spec = SampleSpec(PULSE_FORMATS[params.sampwidth], params.framerate, params.nchannels)
        default = 0xFFFFFFFF
        attr = BufferAttr(default, params.framerate * params.nchannels * params.sampwidth // 10, default, default, default)
        error = ctypes.c_int()
        self.lib, self.stream = lib, lib.pa_simple_new(None, b"WTFTD", 1, sink.encode() if sink else None, b"alarm",  # 1: playback
                                                       ctypes.byref(spec), None, ctypes.byref(attr), ctypes.byref(error))
        if not self.stream:
            raise OSError(f"PulseAudio error {error.value}")

    def write(self, frames: bytes) -> bool:
        return self.lib.pa_simple_write(self.stream, frames, len(frames), None) == 0

    def close(self, drain: bool):
        (self.lib.pa_simple_drain if drain else self.lib.pa_simple_flush)(self.stream, None)
        self.lib.pa_simple_free(self.stream)


class _Aplay:
    """ALSA's player reading the frames: the default output only."""

    def __init__(self, params, sink: str | None):
        self.proc = subprocess.Popen(["aplay", "-q", "-t", "raw", "-f", ALSA_FORMATS[params.sampwidth], "-r", str(params.framerate),
                                      "-c", str(params.nchannels)], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def write(self, frames: bytes) -> bool:
        try:
            self.proc.stdin.write(frames)
            return True
        except OSError:
            return False

    def close(self, drain: bool):
        if not drain:
            self.proc.kill()
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _output(data: bytes, device: str):
    """Linux: (a stream for this .wav on this output, else the default one, its frames, its wave params); None if nothing
    plays it."""
    try:
        with wave.open(io.BytesIO(data), "rb") as sound:
            params, frames = sound.getparams(), sound.readframes(sound.getnframes())
    except (EOFError, wave.Error):
        return None
    for kind in (_Pulse, _Aplay):
        try:
            return kind(params, _sink(device)), frames, params
        except (OSError, AttributeError, KeyError):  # not installed, no sound server, a format it doesn't take
            continue
    return None


class _Repeat(threading.Thread):
    """Linux: the frames written again and again into one stream, a twentieth of a second at a time, until stop()."""

    def __init__(self, data: bytes, device: str):
        super().__init__(daemon=True)
        self.out, frames, params = _output(data, device) or (None, b"", None)
        self.stopping = threading.Event()
        step = max(1, int(params.framerate * CHUNK_S)) * params.nchannels * params.sampwidth if params else 1
        self.chunks = [frames[i:i + step] for i in range(0, len(frames), step)]
        if self.out and self.chunks:
            self.start()

    def run(self):
        while not self.stopping.is_set():
            for chunk in self.chunks:
                if self.stopping.is_set() or not self.out.write(chunk):
                    return

    def stop(self):
        self.stopping.set()
        if self.out:
            if self.is_alive():
                self.join(1)
            self.out.close(drain=False)
            self.out = None
