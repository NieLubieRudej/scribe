"""Caption track selection, parsing, de-duplication, and paragraphing.

Design notes (verified empirically on real videos, see PLAN_V2):
- Prefer **json3**: each event is a distinct cue, so the YouTube auto-caption
  "rolling window" (every line repeated 2-3×) that plagues VTT simply does not
  occur — we only skip the whitespace-only newline-marker events.
- Prefer creator-uploaded subtitles over auto; for auto, prefer the original-
  language ASR track (`<lang>-orig`) over machine translations."""

from __future__ import annotations

import json
import re

from scribe.models import Captions, Segment

_PREF_EXT = ("json3", "vtt")


def select_track(info: dict, wanted_lang: str | None):
    """Choose (tag, subformat, is_manual) for the wanted language, or None.

    Only considers tracks whose base language matches the request, so we never
    silently hand back a machine translation into some unrelated language."""
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    base = (wanted_lang or "").split("-")[0].lower() or "en"

    def pick(formats: list[dict]) -> dict | None:
        by_ext: dict[str, dict] = {}
        for f in formats:
            by_ext.setdefault(f.get("ext"), f)
        for ext in _PREF_EXT:
            if ext in by_ext:
                return by_ext[ext]
        return formats[-1] if formats else None

    # Manual (creator-uploaded) first.
    man_candidates = [wanted_lang, base] + sorted(
        t for t in subs if t.split("-")[0].lower() == base
    )
    for t in man_candidates:
        if t and t in subs:
            f = pick(subs[t])
            if f:
                return t, f, True

    # Automatic: prefer the original-language ASR, then the plain base tag.
    auto_candidates = [f"{base}-orig", wanted_lang, base] + sorted(
        t for t in auto if t.split("-")[0].lower() == base
    )
    for t in auto_candidates:
        if t and t in auto:
            f = pick(auto[t])
            if f:
                return t, f, False
    return None


def parse_json3(data: bytes) -> list[Segment]:
    """Parse a YouTube json3 timedtext payload into clean segments.
    Skips whitespace-only events (the auto-caption line-position markers)."""
    doc = json.loads(data)
    out: list[Segment] = []
    for ev in doc.get("events") or []:
        segs = ev.get("segs")
        if not segs:
            continue
        text = "".join(s.get("utf8", "") for s in segs)
        text = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
        if not text:
            continue
        start = (ev.get("tStartMs") or 0) / 1000.0
        dur = (ev.get("dDurationMs") or 0) / 1000.0
        out.append(Segment(start, start + dur, text))
    return out


_TAG = re.compile(r"<[^>]+>")
# Accept both HH:MM:SS.mmm and the short MM:SS.mmm form (valid WebVTT under 1h).
_TS = r"(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3}"
_CUE_TIME = re.compile(rf"({_TS})\s*-->\s*({_TS})")


def _vtt_ts(s: str) -> float:
    s = s.replace(",", ".")
    parts = s.split(":")
    if len(parts) == 3:
        h, m, rest = parts
    else:
        h, (m, rest) = "0", parts
    return int(h) * 3600 + int(m) * 60 + float(rest)


def parse_vtt(text: str) -> list[Segment]:
    """Fallback parser for VTT, with rolling-window de-duplication: drop a cue
    line equal to the previous line, and strip inline karaoke tags."""
    out: list[Segment] = []
    last_line = None
    blocks = re.split(r"\n\s*\n", text)
    for block in blocks:
        lines = block.splitlines()
        tline = next((ln for ln in lines if "-->" in ln), None)
        if not tline:
            continue
        m = _CUE_TIME.search(tline)
        if not m:
            continue
        start, end = _vtt_ts(m.group(1)), _vtt_ts(m.group(2))
        idx = lines.index(tline)
        for raw in lines[idx + 1:]:
            line = _TAG.sub("", raw)
            line = re.sub(r"\s+", " ", line).strip()
            if not line or line == last_line:
                continue
            out.append(Segment(start, end, line))
            last_line = line
    return out


def build_full_text(segments: list[Segment], gap: float = 2.5,
                    max_para_chars: int = 700) -> str:
    """Join caption lines into readable paragraphs. Paragraph breaks fall on
    pauses (> `gap` seconds) or after a sentence end once a paragraph is long."""
    paras: list[str] = []
    cur: list[str] = []
    last_end: float | None = None
    for s in segments:
        line = s.text.strip()
        if not line:
            continue
        if cur and last_end is not None and (s.start - last_end) > gap:
            paras.append(" ".join(cur))
            cur = []
        if cur and cur[-1] == line:        # belt-and-braces dedup
            last_end = s.end
            continue
        cur.append(line)
        if sum(len(x) + 1 for x in cur) > max_para_chars and re.search(r'[.!?]["\')]?$', line):
            paras.append(" ".join(cur))
            cur = []
        last_end = s.end
    if cur:
        paras.append(" ".join(cur))
    text = "\n\n".join(paras)
    return re.sub(r"[ \t]+", " ", text).strip()


def to_captions(segments: list[Segment], language: str, is_manual: bool) -> Captions:
    return Captions(segments=segments, language=language, is_manual=is_manual)
