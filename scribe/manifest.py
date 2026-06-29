"""Resumable run state: an append-only JSONL keyed by video id.

Idempotent re-runs: a video recorded as 'done' is skipped. Append-only means an
interrupted run loses at most the in-flight item; the last record per id wins."""

from __future__ import annotations

import json
import os
import threading


class Manifest:
    def __init__(self, path: str) -> None:
        self.path = path
        self.records: dict[str, dict] = {}
        self._lock = threading.Lock()
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "id" in r:
                        self.records[r["id"]] = r

    def status(self, vid: str) -> str | None:
        rec = self.records.get(vid)
        return rec.get("status") if rec else None

    def is_done(self, vid: str) -> bool:
        rec = self.records.get(vid)
        if not rec or rec.get("status") != "done":
            return False
        # If the recorded output was deleted/moved, regenerate it.
        path = rec.get("path")
        if path and not os.path.exists(path):
            return False
        return True

    def record(self, vid: str, status: str, **extra) -> None:
        rec = {"id": vid, "status": status, **extra}
        with self._lock:
            self.records[vid] = rec
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
