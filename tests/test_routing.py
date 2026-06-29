"""Routing + audio-language inference (the ASR safety gate's basis)."""

from scribe.models import VideoMeta
from scribe.routing import audio_language, estimate, is_english, route


def _v(**kw):
    return VideoMeta(id="x", title="t", url="u", enriched=True, **kw)


def test_route_unknown_before_enrich():
    assert route(VideoMeta(id="x", title="t", url="u")) == "unknown"


def test_route_caption_when_any_caption_present():
    assert route(_v(caption_langs=["pl-orig", "en", "fr"], language="pl")) == "caption"


def test_audio_language_prefers_field_then_orig_tag():
    assert audio_language(_v(language="pl", caption_langs=["en"])) == "pl"
    assert audio_language(_v(language=None, caption_langs=["en", "fr", "en-orig"])) == "en-orig"
    # translations only (no -orig, no language field) → unknown, NOT 'en'
    assert audio_language(_v(language=None, caption_langs=["en", "fr"])) is None


def test_is_english_uses_audio_language_not_translations():
    assert is_english(_v(language=None, caption_langs=["en-orig", "fr"])) is True
    # Spanish audio that also has an English *translation* must NOT count as English
    assert is_english(_v(language="es", caption_langs=["en", "es-orig"])) is False


def test_route_no_caption_english_is_asr_else_skip():
    assert route(_v(caption_langs=[], language="en")) == "asr"
    assert route(_v(caption_langs=[], language="es")) == "skip"
    assert route(_v(caption_langs=[], language=None)) == "skip"


def test_estimate_counts_and_asr_time():
    vids = [
        _v(caption_langs=["en"]),
        _v(caption_langs=[], language="en", duration=600),
        _v(caption_langs=[], language="pl"),
    ]
    e = estimate(vids)
    assert (e.caption, e.asr, e.skip) == (1, 1, 1)
    assert e.asr_seconds > 0 and e.temp_mb > 0
