"""Tiny display formatters shared by the CLI and the TUI."""

from __future__ import annotations


def fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return "--"
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_date(d: str | None) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if d and len(d) == 8 else "----------"


def fmt_views(n: int | None) -> str:
    if n is None:
        return "--"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def fmt_hms(seconds: float) -> str:
    s = int(round(seconds))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"
