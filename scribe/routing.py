"""How each selected video will be handled, and the cost estimate.

route():
  'caption' — has a usable caption track (fast path, any language)
  'asr'     — no captions but English → Parakeet ASR
  'skip'    — no captions and non-English → skipped in v1 (no multilingual ASR yet)
  'unknown' — not enriched yet (caption availability not probed)"""

from __future__ import annotations

from dataclasses import dataclass

from scribe.models import VideoMeta

# Conservative vs the measured ~0.042 RTF on this M4 (PLAN_V2 §8) — estimates
# should not under-promise.
ASR_RTF = 0.05
AUDIO_MB_PER_MIN = 2.0          # 16 kHz mono wav temp file


def audio_language(meta: VideoMeta) -> str | None:
    """Best estimate of the spoken-audio language. Uses yt-dlp's `language`
    field, else the original-ASR caption tag (`<lang>-orig`). Deliberately does
    NOT trust the bare caption tags, since auto-captions are machine-translated
    into ~157 languages (including 'en') for every video."""
    if meta.language:
        return meta.language
    for tag in meta.caption_langs or []:
        if tag.endswith("-orig"):
            return tag
    return None


def is_english(meta: VideoMeta) -> bool:
    lang = audio_language(meta)
    return bool(lang) and lang.split("-")[0].lower() == "en"


def route(meta: VideoMeta) -> str:
    if not meta.enriched and meta.caption_langs is None:
        return "unknown"
    if meta.caption_langs:
        return "caption"
    return "asr" if is_english(meta) else "skip"


@dataclass
class CostEstimate:
    total: int
    caption: int
    asr: int
    skip: int
    unknown: int
    asr_seconds: float
    temp_mb: float


def estimate(videos: list[VideoMeta]) -> CostEstimate:
    caption = asr = skip = unknown = 0
    asr_seconds = temp_mb = 0.0
    for m in videos:
        r = route(m)
        if r == "caption":
            caption += 1
        elif r == "asr":
            asr += 1
            asr_seconds += (m.duration or 0) * ASR_RTF
            temp_mb += (m.duration or 0) / 60.0 * AUDIO_MB_PER_MIN
        elif r == "skip":
            skip += 1
        else:
            unknown += 1
    return CostEstimate(len(videos), caption, asr, skip, unknown, asr_seconds, temp_mb)
