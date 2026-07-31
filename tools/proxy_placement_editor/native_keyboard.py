"""Native keyboard polling used when Open3D suppresses keys for ImGui edits."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
import time
from typing import Dict, Set


_X11_KEYSYMS = {
    "w": "w",
    "a": "a",
    "s": "s",
    "d": "d",
    "ctrl_left": "Control_L",
    "ctrl_right": "Control_R",
    "shift_left": "Shift_L",
    "shift_right": "Shift_R",
}

_GENERIC_EVENT = 35
_XI_ALL_MASTER_DEVICES = 1
_XI_RAW_KEY_PRESS = 13
_XI_RAW_KEY_RELEASE = 14
_REMOTE_PULSE_HOLD_SECONDS = 0.12
_IMMEDIATE_RELEASE_MAX_MS = 5


class _XEvent(ctypes.Union):
    _fields_ = [("type", ctypes.c_int), ("pad", ctypes.c_long * 24)]


class _XGenericEventCookie(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("extension", ctypes.c_int),
        ("evtype", ctypes.c_int),
        ("cookie", ctypes.c_uint),
        ("data", ctypes.c_void_p),
    ]


class _XIValuatorState(ctypes.Structure):
    _fields_ = [
        ("mask_len", ctypes.c_int),
        ("mask", ctypes.POINTER(ctypes.c_ubyte)),
        ("values", ctypes.POINTER(ctypes.c_double)),
    ]


class _XIRawEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("extension", ctypes.c_int),
        ("evtype", ctypes.c_int),
        ("time", ctypes.c_ulong),
        ("deviceid", ctypes.c_int),
        ("sourceid", ctypes.c_int),
        ("detail", ctypes.c_int),
        ("flags", ctypes.c_int),
        ("valuators", _XIValuatorState),
        ("raw_values", ctypes.POINTER(ctypes.c_double)),
    ]


class _XIEventMask(ctypes.Structure):
    _fields_ = [
        ("deviceid", ctypes.c_int),
        ("mask_len", ctypes.c_int),
        ("mask", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class KeyPulseTracker:
    """Turn RustDesk's immediate press/release pulses into a held key."""

    def __init__(
        self,
        hold_seconds: float = _REMOTE_PULSE_HOLD_SECONDS,
        immediate_release_max_ms: int = _IMMEDIATE_RELEASE_MAX_MS,
    ) -> None:
        self.hold_seconds = float(hold_seconds)
        self.immediate_release_max_ms = int(immediate_release_max_ms)
        self._press_times_ms: Dict[str, int] = {}
        self._deadlines: Dict[str, float] = {}

    def press(self, name: str, event_time_ms: int, now: float) -> None:
        self._press_times_ms[name] = int(event_time_ms)
        self._deadlines[name] = float(now) + self.hold_seconds

    def release(self, name: str, event_time_ms: int) -> None:
        press_time = self._press_times_ms.get(name)
        if press_time is None:
            self._deadlines.pop(name, None)
            return
        elapsed_ms = (int(event_time_ms) - press_time) & 0xFFFFFFFF
        if elapsed_ms > self.immediate_release_max_ms:
            self._deadlines.pop(name, None)
            self._press_times_ms.pop(name, None)

    def pressed(self, now: float) -> Set[str]:
        expired = [
            name for name, deadline in self._deadlines.items() if deadline < now
        ]
        for name in expired:
            self._deadlines.pop(name, None)
            self._press_times_ms.pop(name, None)
        return set(self._deadlines)

    def clear(self) -> None:
        self._press_times_ms.clear()
        self._deadlines.clear()


def pressed_keycodes(key_vector, keycodes: Dict[str, int]) -> Set[str]:
    """Decode the 32-byte XQueryKeymap bitmap for named keycodes."""

    values = bytes(key_vector)
    if len(values) != 32:
        raise ValueError("X11 keymap은 정확히 32 byte여야 합니다.")
    pressed = set()
    for name, keycode in keycodes.items():
        code = int(keycode)
        if code > 0 and values[code >> 3] & (1 << (code & 7)):
            pressed.add(name)
    return pressed


class NativeKeyboardState:
    """Poll Linux/X11 key state without depending on Open3D widget focus."""

    def __init__(self) -> None:
        self._x11 = None
        self._xi = None
        self._display = None
        self._keycodes: Dict[str, int] = {}
        self._key_names_by_code: Dict[int, str] = {}
        self._xi_opcode = 0
        self._pulses = KeyPulseTracker()
        if not sys.platform.startswith("linux") or not os.environ.get("DISPLAY"):
            return
        library = ctypes.util.find_library("X11")
        if not library:
            return
        try:
            x11 = ctypes.CDLL(library)
            x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x11.XOpenDisplay.restype = ctypes.c_void_p
            x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            x11.XCloseDisplay.restype = ctypes.c_int
            x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
            x11.XStringToKeysym.restype = ctypes.c_ulong
            x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            x11.XKeysymToKeycode.restype = ctypes.c_uint
            x11.XQueryKeymap.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_char),
            ]
            x11.XQueryKeymap.restype = ctypes.c_int
            x11.XQueryExtension.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int),
            ]
            x11.XQueryExtension.restype = ctypes.c_int
            x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            x11.XDefaultRootWindow.restype = ctypes.c_ulong
            x11.XPending.argtypes = [ctypes.c_void_p]
            x11.XPending.restype = ctypes.c_int
            x11.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.POINTER(_XEvent)]
            x11.XNextEvent.restype = ctypes.c_int
            x11.XGetEventData.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(_XGenericEventCookie),
            ]
            x11.XGetEventData.restype = ctypes.c_int
            x11.XFreeEventData.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(_XGenericEventCookie),
            ]
            x11.XFreeEventData.restype = None
            x11.XFlush.argtypes = [ctypes.c_void_p]
            x11.XFlush.restype = ctypes.c_int
            display = x11.XOpenDisplay(None)
            if not display:
                return
            keycodes = {}
            for name, symbol in _X11_KEYSYMS.items():
                keysym = x11.XStringToKeysym(symbol.encode("ascii"))
                keycodes[name] = int(x11.XKeysymToKeycode(display, keysym))
            if not all(keycodes.values()):
                x11.XCloseDisplay(display)
                return
            self._x11 = x11
            self._display = display
            self._keycodes = keycodes
            self._key_names_by_code = {
                keycode: name for name, keycode in keycodes.items()
            }
            self._setup_raw_events()
        except (AttributeError, OSError, TypeError, ValueError):
            self.close()

    def _setup_raw_events(self) -> None:
        library = ctypes.util.find_library("Xi")
        if not library or self._x11 is None or self._display is None:
            return
        try:
            xi = ctypes.CDLL(library)
            xi.XISelectEvents.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.POINTER(_XIEventMask),
                ctypes.c_int,
            ]
            xi.XISelectEvents.restype = ctypes.c_int
            opcode = ctypes.c_int()
            first_event = ctypes.c_int()
            first_error = ctypes.c_int()
            found = self._x11.XQueryExtension(
                self._display,
                b"XInputExtension",
                ctypes.byref(opcode),
                ctypes.byref(first_event),
                ctypes.byref(first_error),
            )
            if not found:
                return
            bits = (ctypes.c_ubyte * 2)()
            for event_type in (_XI_RAW_KEY_PRESS, _XI_RAW_KEY_RELEASE):
                bits[event_type >> 3] |= 1 << (event_type & 7)
            mask = _XIEventMask(
                deviceid=_XI_ALL_MASTER_DEVICES,
                mask_len=len(bits),
                mask=ctypes.cast(bits, ctypes.POINTER(ctypes.c_ubyte)),
            )
            root = self._x11.XDefaultRootWindow(self._display)
            if xi.XISelectEvents(self._display, root, ctypes.byref(mask), 1) != 0:
                return
            self._x11.XFlush(self._display)
            self._xi = xi
            self._xi_opcode = int(opcode.value)
        except (AttributeError, OSError, TypeError, ValueError):
            # Physical keyboard state polling remains available without Xi.
            self._xi = None
            self._xi_opcode = 0

    @property
    def available(self) -> bool:
        return self._x11 is not None and self._display is not None

    @property
    def raw_events_available(self) -> bool:
        return self.available and self._xi is not None and self._xi_opcode > 0

    def _drain_raw_events(self, now: float, record: bool = True) -> None:
        if not self.raw_events_available:
            return
        assert self._x11 is not None and self._display is not None
        event = _XEvent()
        while self._x11.XPending(self._display) > 0:
            self._x11.XNextEvent(self._display, ctypes.byref(event))
            cookie = ctypes.cast(
                ctypes.byref(event), ctypes.POINTER(_XGenericEventCookie)
            )
            if (
                cookie.contents.type != _GENERIC_EVENT
                or cookie.contents.extension != self._xi_opcode
                or cookie.contents.evtype
                not in (_XI_RAW_KEY_PRESS, _XI_RAW_KEY_RELEASE)
                or not self._x11.XGetEventData(self._display, cookie)
            ):
                continue
            try:
                raw = ctypes.cast(
                    cookie.contents.data, ctypes.POINTER(_XIRawEvent)
                ).contents
                name = self._key_names_by_code.get(int(raw.detail))
                if not record or name is None:
                    continue
                if raw.evtype == _XI_RAW_KEY_PRESS:
                    self._pulses.press(name, int(raw.time), now)
                else:
                    self._pulses.release(name, int(raw.time))
            finally:
                self._x11.XFreeEventData(self._display, cookie)

    def reset_transient(self) -> None:
        if self.available:
            self._drain_raw_events(time.monotonic(), record=False)
        self._pulses.clear()

    def pressed(self) -> Set[str]:
        if not self.available:
            return set()
        now = time.monotonic()
        self._drain_raw_events(now)
        vector = (ctypes.c_char * 32)()
        assert self._x11 is not None and self._display is not None
        self._x11.XQueryKeymap(self._display, vector)
        snapshot = pressed_keycodes(vector, self._keycodes)
        return snapshot | self._pulses.pressed(now)

    def close(self) -> None:
        if self._x11 is not None and self._display is not None:
            self._x11.XCloseDisplay(self._display)
        self._display = None
        self._x11 = None
        self._xi = None
        self._xi_opcode = 0
        self._keycodes = {}
        self._key_names_by_code = {}
        self._pulses.clear()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def fps_keys_from_native(pressed: Set[str]) -> Set[str]:
    """Map the native snapshot to editor movement and modifier names."""

    result = {key for key in ("w", "a", "s", "d") if key in pressed}
    if "shift_left" in pressed or "shift_right" in pressed:
        result.add("shift")
    if "ctrl_left" in pressed or "ctrl_right" in pressed:
        result.add("ctrl")
    return result
