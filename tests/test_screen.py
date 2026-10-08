"""Ava's live screen: captions from tool calls, the console's live view and its fallback."""

from precedent.console.state import reconstruct
from precedent.contracts import Event
from precedent.worker.screen import Frames, caption_for


def test_captions_are_plain_language():
    assert (
        caption_for("browser_navigate", {"url": "http://localhost:9/mail/m/m-1"}) == "Opening Mail"
    )
    assert caption_for("browser_navigate", {"url": "http://localhost:9/"}) == (
        "Opening the company apps"
    )
    assert caption_for("browser_click", {"element": 'button "Save draft"'}) == "Clicking Save draft"
    assert caption_for(
        "browser_fill_form", {"fields": [{"name": "Amount"}, {"name": "Account"}]}
    ) == ("Filling Amount, Account")
    assert caption_for("browser_select_option", {"values": ["1400 Prepaid expenses"]}) == (
        "Choosing 1400 Prepaid expenses"
    )


def _event(seq, type, **data):
    return Event(run_id="r", seq=seq, type=type, data=data)


def test_console_shows_the_live_screen_only_while_the_run_is_live():
    events = [
        _event(1, "run_started", request="x"),
        _event(2, "note", kind="screen", url="http://127.0.0.1:9/screen.mjpg"),
        _event(3, "note", kind="thinking", level="medium", reason="a form is on the page"),
        _event(4, "action", tool="browser_click", args={}, caption="Clicking Save draft"),
    ]
    state = reconstruct(events, active=True)
    assert state["screen"] == "http://127.0.0.1:9/screen.mjpg"
    assert state["thinking"] == {"level": "medium", "reason": "a form is on the page"}
    assert state["activity"] == "Clicking Save draft"
    done = reconstruct([*events, _event(5, "run_finished", outcome="unknown")], active=False)
    assert done["screen"] is None


def test_frames_hand_over_the_latest_picture():
    frames = Frames()
    assert frames.wait(0, 0.01) == (None, 0)
    frames.put(b"a")
    frames.put(b"b")
    assert frames.wait(0, 0.01) == (b"b", 2)
