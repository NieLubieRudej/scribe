import json

from scribe import transcript as tr
from scribe.models import Segment, Transcript, VideoMeta


def _t():
    segs = [
        Segment(0, 2, "Intro line one."),
        Segment(2, 4, "Intro line two."),
        Segment(60, 62, "Body line."),
    ]
    meta = VideoMeta(id="vid1", title="My Title", url="http://x", channel="Chan",
                     upload_date="20260101", duration=62)
    return Transcript(segments=segs, text="", source="caption", language="en",
                      chapters=[{"start_time": 0, "end_time": 50, "title": "Intro"},
                                {"start_time": 50, "end_time": 100, "title": "Body"}],
                      meta=meta)


def test_full_paragraphs_and_timestamps():
    t = _t()
    body, ext = tr.render(t, "full")
    assert ext == "txt" and "Intro line one. Intro line two." in body
    ts, _ = tr.render(t, "full", timestamps=True)
    assert ts.startswith("[0:00] Intro line one.")


def test_smart_uses_chapter_headings():
    body, ext = tr.render(_t(), "smart")
    assert ext == "md"
    assert "## Intro" in body and "## Body" in body
    assert body.index("## Intro") < body.index("## Body")
    assert "Body line." in body.split("## Body", 1)[1]


def test_srt_and_vtt():
    srt, _ = tr.render(_t(), "srt")
    assert srt.startswith("1\n00:00:00,000 --> 00:00:02,000\nIntro line one.")
    vtt, _ = tr.render(_t(), "vtt")
    assert vtt.startswith("WEBVTT") and "00:00:00.000 --> 00:00:02.000" in vtt


def test_json_roundtrips():
    body, ext = tr.render(_t(), "json")
    assert ext == "json"
    doc = json.loads(body)
    assert doc["id"] == "vid1" and doc["language"] == "en" and len(doc["segments"]) == 3


def test_front_matter_prepended_for_text_modes():
    body, _ = tr.render(_t(), "full", with_front_matter=True)
    assert body.startswith("---\n") and "title: My Title" in body and "url: http://x" in body
