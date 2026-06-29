"""scribe command-line entry point.

Single root command (via typer.run) so `scribe URL --opt val` parses naturally.
Kept import-light: `--version`/`--help` must not import yt-dlp / textual / mlx."""

from __future__ import annotations

from enum import Enum
from typing import Optional

import typer

from scribe import __version__


class Mode(str, Enum):
    full = "full"
    smart = "smart"
    srt = "srt"
    vtt = "vtt"
    json = "json"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"scribe {__version__}")
        raise typer.Exit()


def main(
    url: Optional[str] = typer.Argument(
        None, metavar="URL", show_default=False,
        help="YouTube channel/playlist/video URL, youtu.be link, Shorts, or @handle.",
    ),
    mode: Optional[Mode] = typer.Option(None, "--mode", "-m", help="Transcript mode (default: full)."),
    lang: Optional[str] = typer.Option(None, "--lang", "-l", help="Preferred caption language (default: original)."),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output directory (default: transcripts)."),
    timestamps: Optional[bool] = typer.Option(None, "--timestamps/--no-timestamps", help="Include timestamps."),
    front_matter: Optional[bool] = typer.Option(None, "--front-matter/--no-front-matter", help="YAML front-matter."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the picker; take the (filtered) set."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan and cost; write nothing."),
    limit: Optional[int] = typer.Option(None, "--limit", help="Max videos to enumerate."),
    all_: bool = typer.Option(False, "--all", help="Select every enumerated video."),
    filter_: Optional[str] = typer.Option(None, "--filter", help="Keep titles containing this substring."),
    match: Optional[str] = typer.Option(None, "--match", help="Keep titles matching this regex."),
    latest: Optional[int] = typer.Option(None, "--latest", help="Keep the N most recent."),
    since: Optional[str] = typer.Option(None, "--since", help="Keep uploads on/after YYYYMMDD."),
    until: Optional[str] = typer.Option(None, "--until", help="Keep uploads on/before YYYYMMDD."),
    cookies_from_browser: Optional[str] = typer.Option(
        None, "--cookies-from-browser", help="Browser to read cookies from (bot-check mitigation)."),
    open_finder: bool = typer.Option(False, "--open", "-O", help="Reveal the output in Finder when done (default for interactive runs)."),
    no_open: bool = typer.Option(False, "--no-open", help="Never auto-open Finder."),
    version: Optional[bool] = typer.Option(
        None, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version and exit."),
) -> None:
    """Mass transcript extraction from YouTube. Paste a channel, playlist, or
    video; pick what you want; get clean transcripts."""
    if not url:
        typer.echo("Provide a YouTube URL or @handle. See `scribe --help`.")
        raise typer.Exit()

    from scribe.config import load_config, load_last_theme
    from scribe.run import RunOptions, run_pipeline

    cfg = load_config()
    opts = RunOptions(
        mode=(mode.value if mode else cfg.get("mode", "full")),
        lang=lang if lang is not None else cfg.get("lang"),
        output_dir=output or cfg.get("output", "transcripts"),
        timestamps=timestamps if timestamps is not None else bool(cfg.get("timestamps", False)),
        front_matter=front_matter if front_matter is not None else bool(cfg.get("front_matter", False)),
        yes=yes,
        dry_run=dry_run,
        limit=limit,
        all=all_,
        filter=filter_,
        match=match,
        latest=latest,
        since=since,
        until=until,
        cookies_from_browser=cookies_from_browser,
        open_finder=open_finder,
        no_open=no_open,
        theme=cfg.get("theme") or load_last_theme(),
        caption_workers=int(cfg.get("caption_workers", 8)),
    )
    raise typer.Exit(code=run_pipeline(url, opts))


def app() -> None:
    """console_scripts entry point."""
    typer.run(main)
