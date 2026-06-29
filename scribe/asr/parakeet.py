"""Parakeet-mlx ASR backend — the v1 fallback (English).

Measured fastest/lightest local ASR on this M4 (see PLAN_V2 §8). English-only by
design; a future multilingual model implements ASRBackend the same way."""

from __future__ import annotations

from scribe.asr.base import ASRBackend
from scribe.models import ASRResult, Segment

DEFAULT_MODEL = "mlx-community/parakeet-tdt-0.6b-v2"


class ParakeetMLX(ASRBackend):
    name = "parakeet-mlx"

    def __init__(self, model: str = DEFAULT_MODEL, chunk_duration: float = 120.0) -> None:
        self._model_id = model
        # Chunk long audio so GPU memory stays bounded on long-form videos;
        # parakeet-mlx merges chunk results (overlap handles boundaries).
        self._chunk_duration = chunk_duration
        self._model = None

    def _load(self):
        if self._model is None:
            from parakeet_mlx import from_pretrained
            self._model = from_pretrained(self._model_id)
        return self._model

    def supports(self, language: str | None) -> bool:
        # Unknown language → unsupported, so we never garble non-English audio.
        if not language:
            return False
        return language.split("-")[0].lower() == "en"

    def transcribe(self, audio_path: str) -> ASRResult:
        model = self._load()
        result = model.transcribe(audio_path, chunk_duration=self._chunk_duration)
        segments = [
            Segment(start=s.start, end=s.end, text=s.text.strip())
            for s in (result.sentences or [])
            if s.text.strip()
        ]
        return ASRResult(text=(result.text or "").strip(), segments=segments, language="en")
