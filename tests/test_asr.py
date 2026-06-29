"""ASR routing logic — pure (does not load the model)."""

from scribe.asr.parakeet import ParakeetMLX


def test_parakeet_supports_english_only():
    a = ParakeetMLX()
    assert a.supports("en") is True
    assert a.supports("en-US") is True
    assert a.supports("en-orig") is True


def test_parakeet_rejects_non_english_and_unknown():
    a = ParakeetMLX()
    assert a.supports("pl") is False
    assert a.supports("de") is False
    assert a.supports(None) is False   # unknown → skip, never garble
    assert a.supports("") is False
