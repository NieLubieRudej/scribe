"""The ASRBackend interface — the seam for the future multilingual model.

v1: Parakeet-mlx, English only (`supports('en')`). When a fast multilingual
model arrives it implements this and `supports()` widens; the orchestrator's
routing (caption-first → ASR if supported → else skip) needs no change."""

from __future__ import annotations

from abc import ABC, abstractmethod

from scribe.models import ASRResult


class ASRBackend(ABC):
    name: str

    @abstractmethod
    def supports(self, language: str | None) -> bool:
        """Whether this backend can transcribe the given (original) language.
        None = unknown language; backends decide (Parakeet treats unknown as
        unsupported to avoid garbling non-English audio)."""

    @abstractmethod
    def transcribe(self, audio_path: str) -> ASRResult:
        """Transcribe a 16 kHz mono wav file."""
