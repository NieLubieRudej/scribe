"""Caption parsing, de-duplication, paragraphing, track selection — pure, no network."""

import json

from scribe import captions as cap


def test_parse_json3_skips_whitespace_events():
    payload = {
        "events": [
            {"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "Hello"}, {"utf8": " world"}]},
            {"tStartMs": 1000, "dDurationMs": 500, "segs": [{"utf8": "\n"}]},   # marker
            {"tStartMs": 1500, "dDurationMs": 1000, "segs": [{"utf8": "second line"}]},
            {"tStartMs": 3000, "dDurationMs": 100},                              # no segs
        ]
    }
    segs = cap.parse_json3(json.dumps(payload).encode())
    assert [s.text for s in segs] == ["Hello world", "second line"]
    assert segs[0].start == 0.0 and segs[1].start == 1.5


def test_build_full_text_paragraph_break_on_gap():
    from scribe.models import Segment

    segs = [
        Segment(0, 1, "first."),
        Segment(1, 2, "still first."),
        Segment(10, 11, "after a long pause."),   # gap > 2.5s → new paragraph
    ]
    text = cap.build_full_text(segs)
    assert text == "first. still first.\n\nafter a long pause."


def test_build_full_text_dedups_consecutive():
    from scribe.models import Segment

    segs = [Segment(0, 1, "repeat"), Segment(1, 2, "repeat"), Segment(2, 3, "new")]
    assert cap.build_full_text(segs) == "repeat new"


def test_parse_vtt_rolling_window_dedup():
    vtt = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\n"
        "<c>hello</c> world\n\n"
        "00:00:03.000 --> 00:00:05.000\n"
        "hello world\n"
        "this is new\n"
    )
    segs = cap.parse_vtt(vtt)
    assert [s.text for s in segs] == ["hello world", "this is new"]


def test_parse_vtt_short_timestamps():
    vtt = "WEBVTT\n\n00:01.000 --> 00:03.000\nhello\n"
    segs = cap.parse_vtt(vtt)
    assert len(segs) == 1 and segs[0].start == 1.0 and segs[0].end == 3.0 and segs[0].text == "hello"


def _track(*exts):
    return [{"ext": e, "url": f"http://x/{e}"} for e in exts]


def test_select_prefers_manual_and_json3():
    info = {
        "subtitles": {"en": _track("vtt", "json3")},
        "automatic_captions": {"en": _track("json3")},
    }
    tag, fmt, is_manual = cap.select_track(info, "en")
    assert tag == "en" and is_manual is True and fmt["ext"] == "json3"


def test_select_auto_prefers_orig():
    info = {
        "subtitles": {},
        "automatic_captions": {"en": _track("json3"), "en-orig": _track("json3")},
    }
    tag, fmt, is_manual = cap.select_track(info, "en")
    assert tag == "en-orig" and is_manual is False


def test_select_returns_none_for_unavailable_language():
    info = {"subtitles": {"en": _track("json3")}, "automatic_captions": {"en": _track("json3")}}
    assert cap.select_track(info, "de") is None
