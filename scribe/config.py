"""Optional defaults from ~/.config/scribe/config.toml (CLI flags override).

Recognized keys (all optional):
    mode = "full"          # full | smart | srt | vtt | json
    output = "transcripts" # output directory
    lang = "en"            # preferred caption language
    timestamps = false
    front_matter = false
    theme = "nord"         # any Textual theme (Ctrl+P in the picker switches live)
    caption_workers = 8
"""

from __future__ import annotations

import json
import os
import tomllib

CONFIG_PATH = os.path.expanduser("~/.config/scribe/config.toml")
STATE_PATH = os.path.expanduser("~/.config/scribe/state.json")


def load_config(path: str = CONFIG_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def load_last_theme() -> str | None:
    """The theme last chosen live (Ctrl+P), persisted across runs."""
    try:
        with open(STATE_PATH) as f:
            return json.load(f).get("theme")
    except Exception:
        return None


def save_last_theme(name: str) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w") as f:
            json.dump({"theme": name}, f)
    except Exception:
        pass
