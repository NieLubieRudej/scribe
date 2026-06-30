# scribe

[![CI](https://github.com/NieLubieRudej/scribe/actions/workflows/ci.yml/badge.svg)](https://github.com/NieLubieRudej/scribe/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue)
![Platform: macOS Apple Silicon](https://img.shields.io/badge/platform-macOS%20Apple%20Silicon-black)

Fast, comfortable CLI for **mass transcript extraction from YouTube** on Apple Silicon.

Paste a channel, playlist, or video → see the videos → **pick exactly the ones you want** in
an interactive picker → get clean transcripts. **Captions-first** (any language), with an
automatic local **Parakeet** ASR fallback for English videos that have no captions.

```
scribe https://www.youtube.com/@SomeChannel
```

A 1000-video channel lists in seconds; selecting 12 of them transcribes just those 12.

---

## Requirements

- macOS, Apple Silicon (M-series)
- [`uv`](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `ffmpeg` (only needed for the ASR fallback) — `brew install ffmpeg`

## Install

```sh
uv tool install git+https://github.com/NieLubieRudej/scribe
```

That's it — `scribe` is on your PATH. `uv` fetches a managed Python 3.12 and the prebuilt
Apple-Silicon wheels (no compiler needed); the Parakeet ASR model (~0.6 B) is downloaded
lazily on first ASR use, so the base install stays small.

**Update:**

```sh
uv tool upgrade scribe
# (from a moving branch, force the newest commit:)
uv tool install --reinstall git+https://github.com/NieLubieRudej/scribe
```

**From a local checkout** (development): `uv tool install .` · or `uv sync && uv run scribe`.

> Captions work without ffmpeg. Only the local ASR fallback (for English videos with no
> captions) needs it — scribe tells you to `brew install ffmpeg` if it's missing and skips
> just those videos.

---

## Use it

### Interactive (default)

```sh
scribe https://www.youtube.com/@veritasium
```

Detects the input type automatically (channel `@handle` / `/channel/…` / `/c/` / `/user/`,
playlist, single video, `youtu.be`, Shorts), lists the videos, and opens the picker.

**Picker keys**

| key | action | | key | action |
|---|---|---|---|---|
| `space` | select / deselect | | `/` | filter by title (fuzzy) |
| `a` | select all (shown) | | `d` `u` `w` `c` `t` | sort by date / duration / views / captions / title |
| `n` | select none | | `enter` | confirm → transcribe |
| `i` | invert | | `q` | quit |
| `v` | range select (press at both ends) | | `esc` | leave the filter box |

The footer shows a live cost preview for your selection:
`12 selected · 8 captioned · 4 ASR (~3m20s, ~6MB temp)`. Caption availability is probed only
for what you select — the channel is never fully probed.

### Scriptable (every picker action has a flag)

```sh
scribe @veritasium --latest 10 --yes                 # 10 newest, no picker
scribe @veritasium --filter "GPS" --mode smart       # titles containing "GPS", chaptered .md
scribe @veritasium --all --since 20260101 --yes      # everything since 2026-01-01
scribe @veritasium --match '(?i)part \d+' --dry-run  # preview + cost, write nothing
```

| flag | meaning |
|---|---|
| `--all` | select every enumerated video |
| `--filter SUB` | keep titles containing `SUB` |
| `--match REGEX` | keep titles matching `REGEX` |
| `--latest N` | keep the N most recent |
| `--since YYYYMMDD` / `--until YYYYMMDD` | date window |
| `--yes`, `-y` | skip the picker; take the filtered set |
| `--mode` | `full` (default) · `smart` · `srt` · `vtt` · `json` |
| `--lang`, `-l` | preferred caption language (default: the video's original) |
| `--timestamps` / `--front-matter` | include timestamps / YAML front-matter |
| `--output`, `-o` | output directory (default `transcripts`) |
| `--limit N` | cap enumeration at N videos |
| `--dry-run` | show the plan and cost; write nothing |
| `--cookies-from-browser NAME` | read cookies from a browser (bot-check mitigation) |

(Without a TTY, pass a selection flag or `--yes` — there's no picker to open.)

---

## Modes

- **full** (default, `.txt`) — the whole transcript as clean, readable, de-duplicated
  paragraphs.
- **smart** (`.md`) — chapter-aware: the video's chapters become `##` headings; with no
  chapters it falls back to paragraphs split on pauses.
- **srt** / **vtt** — standard subtitle files.
- **json** — segments (with timing) plus metadata.

YouTube auto-caption "rolling window" duplication is removed (json3 is used internally).

## Output

```
transcripts/<channel>/<upload_date>__<sanitized title>.<ext>
```

Filenames are sanitized; existing files are never overwritten (a ` (2)` suffix is added).
Each run writes a `.scribe-manifest.jsonl` — re-running the same command **resumes**, skipping
videos already done. A per-video failure is logged and the run continues; you get a summary at
the end (written / skipped / failed).

## Config

Optional defaults in `~/.config/scribe/config.toml` (CLI flags override):

```toml
mode = "smart"
output = "~/Transcripts"
lang = "en"
timestamps = false
front_matter = true
caption_workers = 8
```

---

## Performance (measured on an M4, 16 GB)

| operation | measured |
|---|---|
| list a 444-video channel | ~4 s · 1000 videos ~10 s |
| caption fast-path (captioned video) | ~1–3 s |
| ASR (Parakeet) on real YouTube audio | **~24× realtime** (RTF ~0.042), ~6% WER vs manual captions |

## Languages

Captions are language-agnostic, so **Polish, English, and any other language work whenever a
caption track exists** (which is the case for nearly all spoken-word videos, via YouTube's
auto-captions). The ASR fallback in v1 is **English-only** (Parakeet); a non-English video
with *no captions at all* is skipped with a clear message. A fast multilingual ASR model is
planned next, behind the same interface.

## Roadmap

- Multilingual ASR (same speed/quality, not English-only).
- More platforms (TikTok / Instagram / X) behind the existing `Source` interface — the same
  caption→ASR pipeline and the same picker.

See [`PLAN_V2.md`](./PLAN_V2.md) for the full design, gates, and measured numbers.
