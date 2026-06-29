"""Render a Transcript into the user's chosen format.

Modes: full (txt, default) · smart (md, chapter-aware) · srt · vtt · json.
Optional YAML front-matter for the text formats."""

from __future__ import annotations

import json

from scribe.captions import build_full_text
from scribe.models import ASRResult, Captions, Segment, Transcript, VideoMeta

EXT = {"full": "txt", "smart": "md", "srt": "srt", "vtt": "vtt", "json": "json"}


# ---- assembly --------------------------------------------------------------
def from_captions(caps: Captions, meta: VideoMeta) -> Transcript:
    return Transcript(
        segments=caps.segments,
        text=build_full_text(caps.segments),
        source="caption",
        language=caps.language,
        chapters=meta.chapters,
        meta=meta,
    )


def from_asr(res: ASRResult, meta: VideoMeta) -> Transcript:
    return Transcript(
        segments=res.segments,
        text=res.text or build_full_text(res.segments),
        source="asr",
        language=res.language,
        chapters=meta.chapters,
        meta=meta,
    )


# ---- time formatting -------------------------------------------------------
def _clock(seconds: float, sep: str) -> str:
    if seconds < 0:
        seconds = 0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _stamp(seconds: float) -> str:
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"[{h:d}:{m:02d}:{s:02d}]" if h else f"[{m:d}:{s:02d}]"


# ---- renderers -------------------------------------------------------------
def render_full(segments: list[Segment], timestamps: bool = False) -> str:
    if timestamps:
        return "\n".join(f"{_stamp(s.start)} {s.text}" for s in segments if s.text.strip())
    return build_full_text(segments)


def _segments_in(segments: list[Segment], start: float, end: float) -> list[Segment]:
    return [s for s in segments if start <= s.start < end]


def render_smart(segments: list[Segment], chapters: list[dict] | None,
                 timestamps: bool = False) -> str:
    if not chapters:
        # No chapters → paragraphs by pause (build_full_text already does this).
        return render_full(segments, timestamps)
    out: list[str] = []
    n = len(chapters)
    duration_end = segments[-1].end if segments else 0.0
    for i, ch in enumerate(chapters):
        start = ch.get("start_time") or 0.0
        end = ch.get("end_time")
        if end is None:
            end = chapters[i + 1].get("start_time") if i + 1 < n else duration_end + 1
        title = (ch.get("title") or f"Chapter {i + 1}").strip()
        body = render_full(_segments_in(segments, start, end), timestamps)
        out.append(f"## {title}\n\n{body}".rstrip())
    return "\n\n".join(out)


def render_srt(segments: list[Segment]) -> str:
    lines = []
    for i, s in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{_clock(s.start, ',')} --> {_clock(s.end, ',')}")
        lines.append(s.text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_vtt(segments: list[Segment]) -> str:
    lines = ["WEBVTT", ""]
    for s in segments:
        lines.append(f"{_clock(s.start, '.')} --> {_clock(s.end, '.')}")
        lines.append(s.text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_json(t: Transcript) -> str:
    m = t.meta
    doc = {
        "id": m.id if m else None,
        "title": m.title if m else None,
        "url": m.url if m else None,
        "channel": m.channel if m else None,
        "upload_date": m.upload_date if m else None,
        "duration": m.duration if m else None,
        "language": t.language,
        "source": t.source,
        "chapters": t.chapters,
        "text": t.text,
        "segments": [{"start": s.start, "end": s.end, "text": s.text} for s in t.segments],
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)


# ---- front-matter ----------------------------------------------------------
def front_matter(t: Transcript) -> str:
    import yaml  # transitive dep; safe_dump handles escaping

    m = t.meta
    data = {
        "title": m.title if m else None,
        "url": m.url if m else None,
        "channel": m.channel if m else None,
        "upload_date": m.upload_date if m else None,
        "duration": m.duration if m else None,
        "language": t.language,
        "source": t.source,
    }
    data = {k: v for k, v in data.items() if v is not None}
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{body}\n---\n"


# ---- top-level -------------------------------------------------------------
def render(t: Transcript, mode: str = "full", timestamps: bool = False,
           with_front_matter: bool = False) -> tuple[str, str]:
    """Return (content, extension)."""
    if mode == "json":
        return render_json(t), "json"
    if mode == "full":
        body = render_full(t.segments, timestamps)
    elif mode == "smart":
        body = render_smart(t.segments, t.chapters, timestamps)
    elif mode == "srt":
        body = render_srt(t.segments)
    elif mode == "vtt":
        body = render_vtt(t.segments)
    else:
        raise ValueError(f"unknown mode: {mode}")
    if with_front_matter and mode in ("full", "smart"):
        body = front_matter(t) + "\n" + body
    return body, EXT[mode]
