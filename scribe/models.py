"""Shared, dependency-light data models. Plain dataclasses so they are cheap to
import (the CLI's `--version` path must not pull in yt-dlp / textual / mlx)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VideoMeta:
    """One row in the picker. Cheap fields come from flat enumeration; the rest are
    filled lazily by a full per-video extract (see YouTubeSource.enrich)."""

    id: str
    title: str
    url: str
    duration: float | None = None            # seconds
    view_count: int | None = None
    upload_date: str | None = None           # 'YYYYMMDD' (approximate in flat mode)
    timestamp: int | None = None
    channel: str | None = None               # channel/playlist name (for foldering)
    # --- enrichment (full extract) ---
    language: str | None = None              # original audio language code, e.g. 'en'
    chapters: list[dict] | None = None       # [{start_time, end_time?, title?}]
    caption_langs: list[str] | None = None   # union of manual+auto caption tags
    has_manual_subs: bool | None = None
    enriched: bool = False

    @property
    def has_captions(self) -> bool | None:
        """None = not probed yet; True/False once enriched."""
        if self.caption_langs is None:
            return None
        return len(self.caption_langs) > 0


@dataclass
class Segment:
    start: float          # seconds
    end: float            # seconds
    text: str


@dataclass
class Transcript:
    segments: list[Segment]
    text: str
    source: str                       # 'caption' | 'asr'
    language: str | None = None
    chapters: list[dict] | None = None
    meta: VideoMeta | None = None


@dataclass
class ASRResult:
    text: str
    segments: list[Segment] = field(default_factory=list)
    language: str | None = None


@dataclass
class Captions:
    """A fetched, parsed caption track."""

    segments: list[Segment]
    language: str          # the chosen track tag, e.g. 'en' or 'pl-orig'
    is_manual: bool        # True = creator-uploaded; False = auto-generated (ASR)
