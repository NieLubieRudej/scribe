"""Pure URL classification — no network, no heavy deps, fully unit-testable.

Decides, from the string alone, whether the user pasted a single video or a
collection (channel tab / playlist), and normalizes channels to their /videos
tab so Shorts and live streams are excluded by default."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

VIDEO = "video"
COLLECTION = "collection"
UNKNOWN = "unknown"

_VIDEO_ID = r"[0-9A-Za-z_-]{11}"
# Tabs that already scope a channel to a concrete listing we should respect.
_KEEP_TABS = {"videos", "shorts", "streams"}
# Tabs/segments that are not a video listing → fall back to /videos.
_OTHER_TABS = {"featured", "about", "community", "playlists", "podcasts", "releases", "store"}


@dataclass
class Classification:
    kind: str                      # VIDEO | COLLECTION | UNKNOWN
    url: str                       # normalized URL to hand to yt-dlp
    video_id: str | None = None


def _ensure_scheme(s: str) -> str:
    if "://" in s:
        return s
    if s.startswith(("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")):
        return "https://" + s
    return s


def _pin_channel_tab(parsed) -> str:
    """Return a channel URL pinned to a video listing tab (default /videos)."""
    segments = [seg for seg in parsed.path.split("/") if seg]
    # segments[0] is the channel identifier (@handle, channel, c, user, UC...).
    # Find the channel-identifier prefix.
    if not segments:
        return f"https://www.youtube.com{parsed.path}"
    # Determine where the channel id ends.
    if segments[0].startswith("@"):
        id_len = 1
    elif segments[0] in {"channel", "c", "user"}:
        id_len = 2
    else:
        id_len = 1
    base = "/".join(segments[:id_len])
    tail = segments[id_len:]
    tab = tail[0] if tail else ""
    if tab in _KEEP_TABS:
        chosen = tab
    else:
        chosen = "videos"
    return f"https://www.youtube.com/{base}/{chosen}"


def classify(raw: str) -> Classification:
    s = raw.strip()
    if not s:
        return Classification(UNKNOWN, raw)

    # Bare @handle (no slashes / spaces).
    if s.startswith("@") and "/" not in s and " " not in s:
        return Classification(COLLECTION, f"https://www.youtube.com/{s}/videos")

    s = _ensure_scheme(s)
    parsed = urlparse(s)
    host = parsed.netloc.lower()
    path = parsed.path

    if host == "youtu.be":
        vid = path.strip("/").split("/")[0]
        if re.fullmatch(_VIDEO_ID, vid):
            return Classification(VIDEO, s, video_id=vid)
        return Classification(UNKNOWN, s)

    if host == "youtube.com" or host.endswith(".youtube.com"):
        q = parse_qs(parsed.query)
        list_id = q.get("list", [None])[0]

        # Single-video shapes (a real v= wins even if a list= is present).
        # 'videoseries' is a reserved playlist-embed keyword, not a video id.
        if path == "/watch":
            vids = q.get("v")
            if vids and vids[0] != "videoseries" and re.fullmatch(_VIDEO_ID, vids[0]):
                return Classification(VIDEO, s, video_id=vids[0])
        m = re.match(rf"/(shorts|embed|v|live)/({_VIDEO_ID})", path)
        if m and m.group(2) != "videoseries":
            vid = m.group(2)
            return Classification(VIDEO, f"https://www.youtube.com/watch?v={vid}", video_id=vid)

        # Playlist (explicit, or the 'videoseries' embed/watch playlist form).
        if list_id and (path == "/playlist" or path == "/watch" or path.startswith("/embed")):
            return Classification(COLLECTION, f"https://www.youtube.com/playlist?list={list_id}")

        # Channel shapes.
        if path.startswith("/@") or re.match(r"/(channel|c|user)/", path):
            return Classification(COLLECTION, _pin_channel_tab(parsed))

    return Classification(UNKNOWN, s)
