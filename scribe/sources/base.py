"""The Source interface — the seam that keeps Phase-2 platforms additive.

A Source knows how to: detect whether a URL belongs to it, enumerate a
collection cheaply (metadata only), enrich a single video with the expensive
per-video data (captions/chapters/language), fetch caption text, and download
audio for ASR. v1 implements this once, for YouTube."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator

from scribe.models import VideoMeta


class InputKind:
    VIDEO = "video"
    COLLECTION = "collection"   # channel tab or playlist
    UNKNOWN = "unknown"


class Source(ABC):
    name: str

    @abstractmethod
    def matches(self, url: str) -> bool:
        """True if this source handles the URL/handle."""

    @abstractmethod
    def detect_kind(self, url: str) -> str:
        """Return InputKind.* — cheap, no full extraction where avoidable."""

    @abstractmethod
    def enumerate(self, url: str, limit: int | None = None) -> Iterator[VideoMeta]:
        """Yield lightweight VideoMeta (metadata only). Must be fast at 1000+."""

    @abstractmethod
    def enrich(self, videos: Iterable[VideoMeta], max_workers: int = 8) -> None:
        """Fill caption/chapter/language fields in place (full per-video extract).
        Expensive — call only for the user's selection (or lazy background)."""

    @abstractmethod
    def fetch_captions(self, video: VideoMeta, lang: str | None) -> object | None:
        """Return a parsed caption document for the chosen language, or None."""

    @abstractmethod
    def download_audio(self, video: VideoMeta, dest_dir: str) -> str:
        """Download audio-only as 16 kHz mono wav; return the file path."""
