from tools.proxy_placement_editor.native_keyboard import (
    KeyPulseTracker,
    fps_keys_from_native,
    pressed_keycodes,
)


def test_x11_keymap_bitmap_decoding():
    keycodes = {"w": 25, "a": 38, "shift_left": 50}
    vector = bytearray(32)
    for code in (25, 50):
        vector[code >> 3] |= 1 << (code & 7)
    assert pressed_keycodes(vector, keycodes) == {"w", "shift_left"}


def test_native_keys_map_to_fps_keys():
    assert fps_keys_from_native({"w", "d", "shift_right"}) == {
        "w",
        "d",
        "shift",
    }
    assert fps_keys_from_native({"shift_left", "unknown"}) == {"shift"}
    assert fps_keys_from_native({"ctrl_left"}) == {"ctrl"}


def test_rustdesk_immediate_release_pulses_are_treated_as_held():
    tracker = KeyPulseTracker()
    tracker.press("w", event_time_ms=1000, now=1.0)
    tracker.release("w", event_time_ms=1000)
    assert tracker.pressed(1.15) == {"w"}

    tracker.press("w", event_time_ms=1150, now=1.15)
    tracker.release("w", event_time_ms=1150)
    assert tracker.pressed(1.32) == {"w"}
    assert tracker.pressed(1.34) == set()


def test_rustdesk_short_tap_expires_without_sticky_movement():
    tracker = KeyPulseTracker()
    tracker.press("shift_left", event_time_ms=1000, now=1.0)
    tracker.release("shift_left", event_time_ms=1000)

    assert tracker.pressed(1.20) == set()


def test_normal_keyboard_release_stops_pulse_fallback_immediately():
    tracker = KeyPulseTracker(hold_seconds=0.12, immediate_release_max_ms=5)
    tracker.press("a", event_time_ms=2000, now=2.0)
    tracker.release("a", event_time_ms=2200)
    assert tracker.pressed(2.01) == set()


def test_pulse_tracker_clear_discards_remote_input():
    tracker = KeyPulseTracker()
    tracker.press("shift_left", event_time_ms=3000, now=3.0)
    tracker.clear()
    assert tracker.pressed(3.0) == set()
