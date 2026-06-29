import os

from scribe.manifest import Manifest
from scribe.models import VideoMeta
from scribe.run import RunOptions, apply_filters


def _v(i, title, date):
    return VideoMeta(id=f"id{i}", title=title, url="x", upload_date=date)


def test_apply_filters_none_without_criterion():
    assert apply_filters([_v(1, "a", "20260101")], RunOptions()) is None


def test_apply_filters_substring_and_latest():
    vids = [_v(1, "Python tips", "20260103"), _v(2, "Rust guide", "20260102"),
            _v(3, "python deep", "20260101")]
    assert {v.id for v in apply_filters(vids, RunOptions(filter="python"))} == {"id1", "id3"}
    assert [v.id for v in apply_filters(vids, RunOptions(latest=2))] == ["id1", "id2"]


def test_apply_filters_since_until():
    vids = [_v(1, "a", "20260103"), _v(2, "b", "20260102"), _v(3, "c", "20260101")]
    assert {v.id for v in apply_filters(vids, RunOptions(since="20260102"))} == {"id1", "id2"}
    assert {v.id for v in apply_filters(vids, RunOptions(until="20260102"))} == {"id2", "id3"}


def test_apply_filters_match_regex():
    vids = [_v(1, "Episode 1", "x"), _v(2, "Trailer", "x")]
    assert [v.id for v in apply_filters(vids, RunOptions(match=r"episode \d"))] == ["id1"]


def test_select_single_video_extracts_id():
    from scribe.run import _select
    from scribe.sources.base import InputKind
    from scribe.sources.youtube import YouTubeSource

    src = YouTubeSource()
    for url in ("https://youtu.be/dQw4w9WgXcQ",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "https://www.youtube.com/shorts/abcdefghijk"):
        sel = _select(src, url, InputKind.VIDEO, RunOptions())
        assert len(sel) == 1 and len(sel[0].id) == 11


def test_manifest_roundtrip(tmp_path):
    p = str(tmp_path / "m.jsonl")
    m = Manifest(p)
    assert not m.is_done("a")
    m.record("a", "done", source="caption")
    m2 = Manifest(p)
    assert m2.is_done("a") and m2.status("a") == "done"


def test_manifest_is_done_requires_existing_output(tmp_path):
    mpath = str(tmp_path / "m.jsonl")
    out = str(tmp_path / "out.txt")
    open(out, "w").write("x")
    Manifest(mpath).record("v", "done", path=out)
    assert Manifest(mpath).is_done("v")
    os.remove(out)
    assert not Manifest(mpath).is_done("v")    # deleted output → regenerate
