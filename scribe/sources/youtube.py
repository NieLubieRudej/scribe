"""YouTubeSource — the only v1 source.

Two-phase by design (see PLAN_V2 §2): cheap flat ENUMERATION for the picker,
and an expensive per-video ENRICH/fetch only for the user's selection."""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone

from scribe import urls
from scribe.models import Captions, VideoMeta
from scribe.sources.base import InputKind, Source


class _Silent:
    """Swallow yt-dlp's chatter so the TUI/CLI stays clean."""

    def debug(self, msg): ...
    def info(self, msg): ...
    def warning(self, msg): ...
    def error(self, msg): ...


def _flat_opts(limit: int | None) -> dict:
    opts = {
        "extract_flat": "in_playlist",
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "noprogress": True,
        "logger": _Silent(),
        # Stream entries as pages arrive so the picker opens on the first batch
        # instead of blocking until the whole channel is paginated.
        "lazy_playlist": True,
        # Parse YouTube's "published X ago" text into an approximate upload_date
        # without paying for a full extract per video.
        "extractor_args": {"youtubetab": {"approximate_date": [""]}},
    }
    if limit is not None:
        opts["playlistend"] = limit
    return opts


def _full_opts() -> dict:
    """Options for a full per-video extract (captions/chapters/language)."""
    return {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _Silent(),
    }


def _meta_from_entry(e: dict) -> VideoMeta | None:
    vid = e.get("id")
    if not vid or e.get("ie_key") not in (None, "Youtube"):
        # Skip nested tab stubs / non-video entries.
        return None
    ts = e.get("timestamp")
    upload_date = e.get("upload_date")
    if not upload_date and ts:
        # In flat mode `approximate_date` fills `timestamp` but not `upload_date`
        # (yt-dlp derives the latter only at output time). Derive it ourselves in
        # UTC, matching yt-dlp. Approximate (parsed from "X ago"); day may be off.
        upload_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y%m%d")
    return VideoMeta(
        id=vid,
        title=e.get("title") or "(untitled)",
        url=e.get("url") or f"https://www.youtube.com/watch?v={vid}",
        duration=e.get("duration"),
        view_count=e.get("view_count"),
        upload_date=upload_date,
        timestamp=ts,
    )


class YouTubeSource(Source):
    name = "youtube"

    def __init__(self, cookies_from_browser: str | None = None) -> None:
        # Cache full per-video info dicts (id -> info) so enrich() and the later
        # caption/audio fetch never pay for the same extract twice.
        self._info_cache: dict[str, dict | None] = {}
        self._cache_lock = threading.Lock()
        self._cookies = cookies_from_browser

    def _with_cookies(self, opts: dict) -> dict:
        if self._cookies:
            opts = {**opts, "cookiesfrombrowser": (self._cookies,)}
        return opts

    # ---- detection -------------------------------------------------------
    def matches(self, url: str) -> bool:
        return urls.classify(url).kind != urls.UNKNOWN

    def detect_kind(self, url: str) -> str:
        c = urls.classify(url)
        if c.kind == urls.VIDEO:
            return InputKind.VIDEO
        if c.kind == urls.COLLECTION:
            return InputKind.COLLECTION
        return InputKind.UNKNOWN

    def normalize(self, url: str) -> str:
        return urls.classify(url).url

    # ---- enumeration (cheap) --------------------------------------------
    def enumerate(self, url: str, limit: int | None = None) -> Iterator[VideoMeta]:
        from yt_dlp import YoutubeDL  # lazy: keeps CLI startup light

        c = urls.classify(url)
        if c.kind == urls.VIDEO:
            # A single video still gets a (1-row) listing.
            yield VideoMeta(id=c.video_id or "", title="(single video)", url=c.url)
            return

        with YoutubeDL(self._with_cookies(_flat_opts(limit))) as ydl:
            info = ydl.extract_info(c.url, download=False)
            if not info:
                return
            collection = info.get("channel") or info.get("uploader") or info.get("title")
            # With lazy_playlist=True this is a generator that pulls continuation
            # pages on demand — iterate inside the session so it streams.
            for e in info.get("entries") or []:
                if not isinstance(e, dict):
                    continue
                meta = _meta_from_entry(e)
                if meta is not None:
                    meta.channel = collection
                    yield meta

    # ---- enrichment / fetch (expensive — selection only) ----------------
    def _full_info(self, video: VideoMeta) -> dict | None:
        """One full extract per video id, cached. Each call uses its own
        YoutubeDL so concurrent enrichment is safe."""
        with self._cache_lock:
            if video.id in self._info_cache:
                return self._info_cache[video.id]
        from yt_dlp import YoutubeDL

        info: dict | None
        try:
            with YoutubeDL(self._with_cookies(_full_opts())) as ydl:
                info = ydl.extract_info(video.url, download=False)
        except Exception:
            info = None
        with self._cache_lock:
            self._info_cache[video.id] = info
        return info

    def enrich(self, videos: Iterable[VideoMeta], max_workers: int = 8) -> None:
        from concurrent.futures import ThreadPoolExecutor

        # De-dup by id so concurrent workers never double-extract the same video.
        todo = list({v.id: v for v in videos if not v.enriched}.values())
        if not todo:
            return

        def work(v: VideoMeta) -> None:
            info = self._full_info(v)
            if not info:
                v.caption_langs = []          # probed: none / unavailable
                v.has_manual_subs = False
                v.enriched = True
                return
            subs = info.get("subtitles") or {}
            auto = info.get("automatic_captions") or {}
            v.language = info.get("language")
            v.chapters = info.get("chapters")
            v.caption_langs = sorted(set(subs) | set(auto))
            v.has_manual_subs = bool(subs)
            # Upgrade the cheap/approximate flat fields with exact values.
            if info.get("view_count") is not None:
                v.view_count = info["view_count"]
            if info.get("upload_date"):
                v.upload_date = info["upload_date"]
            if info.get("duration"):
                v.duration = info["duration"]
            if info.get("title"):
                v.title = info["title"]
            if info.get("channel") or info.get("uploader"):
                v.channel = info.get("channel") or info.get("uploader")
            v.enriched = True

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            list(ex.map(work, todo))

    def fetch_captions(self, video: VideoMeta, lang: str | None) -> Captions | None:
        from scribe import captions as cap

        info = self._full_info(video)
        if not info:
            return None
        wanted = lang or info.get("language") or "en"
        sel = cap.select_track(info, wanted)
        if not sel:
            return None
        tag, subformat, is_manual = sel
        data = self._http_get(subformat.get("url"), subformat.get("http_headers"))
        if not data:
            return None
        # A 200 response can still be HTML (consent/redirect/PO-token page), so
        # guard every parse and degrade to None rather than raising.
        ext = subformat.get("ext")
        try:
            if ext == "vtt":
                segs = cap.parse_vtt(data.decode("utf-8", "replace"))
            else:
                segs = cap.parse_json3(data)
        except Exception:
            try:
                segs = cap.parse_vtt(data.decode("utf-8", "replace"))
            except Exception:
                return None
        if not segs:
            return None
        return Captions(segments=segs, language=tag, is_manual=is_manual)

    @staticmethod
    def _http_get(url: str | None, headers: dict | None) -> bytes | None:
        if not url:
            return None
        import requests

        try:
            r = requests.get(url, headers=headers or {}, timeout=30)
            r.raise_for_status()
            return r.content
        except Exception:
            return None

    def download_audio(self, video: VideoMeta, dest_dir: str) -> str:
        """Download audio-only and transcode to 16 kHz mono wav (Whisper/Parakeet
        optimal). Returns the wav path; the intermediate source is auto-deleted."""
        import os

        from yt_dlp import YoutubeDL

        os.makedirs(dest_dir, exist_ok=True)
        opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(dest_dir, "%(id)s.%(ext)s"),
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
            "postprocessor_args": {"extractaudio": ["-ar", "16000", "-ac", "1"]},
            "keepvideo": False,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": _Silent(),
        }
        with YoutubeDL(self._with_cookies(opts)) as ydl:
            ydl.download([video.url])
        path = os.path.join(dest_dir, f"{video.id}.wav")
        if not os.path.exists(path):
            raise RuntimeError(f"audio extraction failed for {video.id}")
        return path
