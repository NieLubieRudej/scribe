"""Filesystem output: safe filenames, per-channel foldering, no silent overwrite."""

from __future__ import annotations

import os
import re

_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize(name: str, maxlen: int = 120) -> str:
    name = _ILLEGAL.sub(" ", name or "")
    name = re.sub(r"\s+", " ", name).strip().strip(". ")
    return name[:maxlen].strip() or "untitled"


def output_path(base_dir: str, channel: str | None, upload_date: str | None,
                title: str, ext: str) -> str:
    """`<base>/<Channel>/<YYYY-MM-DD> <Title>.<ext>` — readable and sorts by date.
    Videos with no known date drop the prefix (just the title)."""
    folder = os.path.join(base_dir, sanitize(channel or "unknown", 80))
    title = sanitize(title)
    if upload_date and len(upload_date) == 8:
        name = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]} {title}"
    else:
        name = title
    return os.path.join(folder, f"{name}.{ext}")


def write_no_clobber(path: str, content: str) -> str:
    """Write `content`, never overwriting an existing different file: if the path
    is taken, append ' (2)', ' (3)', … Returns the path actually written.

    The filename is reserved atomically (O_CREAT|O_EXCL), so concurrent callers
    racing for the same path each get a distinct file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    root, ext = os.path.splitext(path)
    candidate, i = path, 1
    while True:
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o644)
            break
        except FileExistsError:
            i += 1
            candidate = f"{root} ({i}){ext}"
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return candidate
