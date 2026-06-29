"""Orchestrator: selection → enrich → caption-first/ASR-fallback → write.

Per-video failures never abort the run (graceful runtime degradation); the run is
resumable via the manifest and prints a final summary."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import quote

import typer

from scribe import output, routing
from scribe import transcript as tr
from scribe.fmt import fmt_hms
from scribe.manifest import Manifest
from scribe.models import VideoMeta
from scribe.sources.base import InputKind
from scribe.sources.youtube import YouTubeSource


@dataclass
class RunOptions:
    mode: str = "full"
    lang: str | None = None
    output_dir: str = "transcripts"
    timestamps: bool = False
    front_matter: bool = False
    yes: bool = False
    dry_run: bool = False
    limit: int | None = None
    all: bool = False
    filter: str | None = None
    match: str | None = None
    latest: int | None = None
    since: str | None = None
    until: str | None = None
    cookies_from_browser: str | None = None
    open_finder: bool = False
    no_open: bool = False
    theme: str | None = None
    caption_workers: int = 8


def _file_uri(path: str) -> str:
    return "file://" + quote(os.path.abspath(path))


def _osc8(uri: str, text: str) -> str:
    """An OSC-8 terminal hyperlink — renders `text` as an actual clickable link."""
    return f"\033]8;;{uri}\033\\{text}\033]8;;\033\\"


def _interactive(kind: str, opts: RunOptions) -> bool:
    if kind == InputKind.VIDEO:
        return False
    selection_flags = any([opts.all, opts.filter, opts.match,
                           opts.latest is not None, opts.since, opts.until])
    return (not opts.yes) and (not selection_flags) and sys.stdout.isatty()


def _reveal_in_finder(path: str) -> None:
    # `open -R` reveals the file selected in a Finder window (folder if a dir).
    flag = "-R" if os.path.isfile(path) else None
    subprocess.run(["open"] + ([flag] if flag else []) + [path], check=False)


def apply_filters(videos: list[VideoMeta], opts: RunOptions) -> list[VideoMeta] | None:
    """Non-interactive selection. Returns None if no selection criterion given."""
    has_criterion = any([opts.all, opts.yes, opts.filter, opts.match,
                         opts.latest is not None, opts.since, opts.until])
    if not has_criterion:
        return None
    res = videos
    if opts.filter:
        sub = opts.filter.lower()
        res = [v for v in res if sub in v.title.lower()]
    if opts.match:
        pat = re.compile(opts.match, re.IGNORECASE)
        res = [v for v in res if pat.search(v.title)]
    if opts.since:
        res = [v for v in res if (v.upload_date or "") >= opts.since]
    if opts.until:
        res = [v for v in res if (v.upload_date or "") <= opts.until]
    if opts.latest is not None:
        res = res[: opts.latest]      # enumeration is newest-first
    return res


# ---- per-video work --------------------------------------------------------
def _write(t: tr.Transcript, v: VideoMeta, opts: RunOptions) -> str:
    content, ext = tr.render(t, opts.mode, opts.timestamps, opts.front_matter)
    path = output.output_path(opts.output_dir, v.channel, v.upload_date, v.title, ext)
    return output.write_no_clobber(path, content)


def _skip_reason(v) -> str:
    lang = routing.audio_language(v)
    if lang:
        return f"no captions; {lang} unsupported (v1 ASR is English-only)"
    return "no captions; language undetected — re-run with --lang en to transcribe"


def _do_caption(src, v, opts, manifest):
    """Returns (video, outcome, payload). outcome ∈ done|needs_asr|skip|error.
    Records the terminal status itself (file write + manifest record happen
    together in the worker) so an interrupt can't orphan a written file."""
    try:
        caps = src.fetch_captions(v, opts.lang)
        if not caps:
            if routing.is_english(v):
                return v, "needs_asr", None       # terminal status deferred to the ASR stage
            reason = _skip_reason(v)
            manifest.record(v.id, "skipped", reason=reason)
            return v, "skip", reason
        path = _write(tr.from_captions(caps, v), v, opts)
        manifest.record(v.id, "done", source="caption", path=path)
        return v, "done", ("caption", path)
    except Exception as e:  # noqa: BLE001 — isolate per-video failures
        manifest.record(v.id, "failed", error=str(e))
        return v, "error", str(e)


def _do_asr(src, asr, v, opts, tmp_dir, manifest):
    # Hard safety gate: never run an English-only model on non-English audio.
    lang = routing.audio_language(v)
    if not asr.supports(lang):
        reason = f"ASR language unsupported (v1 is English-only), language={lang or '?'}"
        manifest.record(v.id, "skipped", reason=reason)
        return v, "skip", reason
    wav = None
    try:
        wav = src.download_audio(v, tmp_dir)
        res = asr.transcribe(wav)
        path = _write(tr.from_asr(res, v), v, opts)
        manifest.record(v.id, "done", source="asr", path=path)
        return v, "done", ("asr", path)
    except Exception as e:  # noqa: BLE001
        manifest.record(v.id, "failed", error=str(e))
        return v, "error", str(e)
    finally:
        if wav and os.path.exists(wav):
            try:
                os.remove(wav)
            except OSError:
                pass


# ---- main flow -------------------------------------------------------------
def run_pipeline(url: str, opts: RunOptions) -> int:
    src = YouTubeSource(cookies_from_browser=opts.cookies_from_browser)
    kind = src.detect_kind(url)
    if kind == InputKind.UNKNOWN:
        typer.secho(f"Not a recognized YouTube URL/handle: {url!r}", fg="red", err=True)
        return 2

    interactive = _interactive(kind, opts)
    selection = _select(src, url, kind, opts)
    if selection is None:
        return 0
    if not selection:
        typer.secho("Nothing selected.", fg="yellow")
        return 0

    return _process(src, selection, opts, interactive=interactive)


def _select(src, url, kind, opts) -> list[VideoMeta] | None:
    if kind == InputKind.VIDEO:
        from scribe import urls
        c = urls.classify(url)
        return [VideoMeta(id=c.video_id or "", title="(video)", url=c.url)]

    if _interactive(kind, opts):
        from scribe.tui.app import run_picker
        sel = run_picker(loader=lambda: src.enumerate(url, limit=opts.limit),
                         source=src, lang=opts.lang, header=url, theme=opts.theme)
        if sel is None:
            typer.echo("Cancelled.")
            return None
        return sel

    typer.echo("Listing…")
    vids = list(src.enumerate(url, limit=opts.limit))
    typer.secho(f"Found {len(vids)} videos.", fg="green")
    sel = apply_filters(vids, opts)
    if sel is None:
        typer.secho(
            "Non-interactive: pass --all, --filter/--match, --latest, --since/--until, "
            "or run in a terminal for the picker.", fg="red", err=True)
        return []
    return sel


def _process(src, selection, opts, interactive: bool = False) -> int:
    # De-duplicate by id (playlists can list the same video twice).
    selection = list({v.id: v for v in selection}.values())

    to_enrich = [v for v in selection if not v.enriched]
    if to_enrich:
        typer.echo(f"Probing {len(to_enrich)} videos (captions/metadata)…")
        src.enrich(to_enrich)

    # If the user explicitly declared English, treat caption-less videos whose
    # audio language YouTube didn't tag as English (so they get ASR'd instead of
    # skipped). We never override a *known* non-English language — that stays safe.
    if opts.lang and opts.lang.split("-")[0].lower() == "en":
        for v in selection:
            if v.language is None and not v.caption_langs:
                v.language = "en"

    def plan_line(est, label):
        typer.secho(
            f"{label}: {est.total} videos · {est.caption} captioned · {est.asr} ASR "
            f"(~{fmt_hms(est.asr_seconds)}, ~{est.temp_mb:.0f}MB temp)"
            + (f" · {est.skip} skipped (non-English, no captions)" if est.skip else ""),
            fg="cyan")

    if opts.dry_run:
        plan_line(routing.estimate(selection), "Plan")
        for v in selection:
            typer.echo(f"  [{routing.route(v):7}] {v.title[:70]}")
        typer.echo("(dry run — nothing written)")
        return 0

    manifest = Manifest(os.path.join(opts.output_dir, ".scribe-manifest.jsonl"))
    pending = [v for v in selection if not manifest.is_done(v.id)]
    already = len(selection) - len(pending)
    if already:
        typer.secho(f"Resuming: {already} already done, skipping.", fg="bright_black")
    plan_line(routing.estimate(pending), "To do")   # estimate the work that will actually run

    counts = {"done": 0, "skipped": 0, "failed": 0}
    failures: list[tuple[str, str]] = []
    written_paths: list[str] = []
    n = len(pending)
    done_i = 0

    caption_vs = [v for v in pending if routing.route(v) == "caption"]
    asr_vs = [v for v in pending if routing.route(v) == "asr"]
    skip_vs = [v for v in pending if routing.route(v) == "skip"]

    def report(v, outcome, payload):
        # Printing only — the worker already recorded the terminal status.
        nonlocal done_i
        done_i += 1
        prefix = f"[{done_i}/{n}]"
        if outcome == "done":
            src_label, path = payload
            counts["done"] += 1
            written_paths.append(path)
            typer.secho(f"{prefix} ✓ {src_label:7} {os.path.basename(path)}", fg="green")
        elif outcome == "skip":
            counts["skipped"] += 1
            typer.secho(f"{prefix} – skip    {v.title[:60]} ({payload})", fg="yellow")
        else:  # error
            counts["failed"] += 1
            failures.append((v.title, payload))
            typer.secho(f"{prefix} ✗ FAIL    {v.title[:60]} ({payload})", fg="red")

    # Captions: I/O-bound → fetched concurrently, but reported in the chosen
    # order (submit everything, then collect in submission order).
    fallback_asr: list[VideoMeta] = []
    if caption_vs:
        with ThreadPoolExecutor(max_workers=opts.caption_workers) as ex:
            ordered = [(v, ex.submit(_do_caption, src, v, opts, manifest)) for v in caption_vs]
            for v, fut in ordered:
                rv, outcome, payload = fut.result()
                if outcome == "needs_asr":
                    fallback_asr.append(rv)
                    continue
                report(rv, outcome, payload)

    asr_vs = asr_vs + fallback_asr

    # ASR preflight: skip cleanly (with an actionable message) if the backend or
    # ffmpeg isn't available — captions already worked without either.
    if asr_vs:
        import importlib.util
        import shutil as _sh
        if importlib.util.find_spec("parakeet_mlx") is None:
            reason = "ASR backend unavailable (parakeet-mlx not installed — needs macOS Apple Silicon)"
            typer.secho(f"  ⚠ {reason}", fg="yellow")
            for v in asr_vs:
                manifest.record(v.id, "skipped", reason=reason)
                report(v, "skip", reason)
            asr_vs = []
        elif _sh.which("ffmpeg") is None:
            typer.secho("  ⚠ ffmpeg not found — needed for ASR. Install it:  brew install ffmpeg",
                        fg="yellow")
            for v in asr_vs:
                manifest.record(v.id, "skipped", reason="ffmpeg not installed (brew install ffmpeg)")
                report(v, "skip", "ffmpeg missing — brew install ffmpeg")
            asr_vs = []

    # ASR: compute-bound on one GPU → serial (avoid thermal throttling).
    if asr_vs:
        from scribe.asr.parakeet import ParakeetMLX
        asr = ParakeetMLX()
        tmp_dir = tempfile.mkdtemp(prefix="scribe-asr-")
        try:
            for v in asr_vs:
                report(*_do_asr(src, asr, v, opts, tmp_dir, manifest))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    for v in skip_vs:
        reason = _skip_reason(v)
        manifest.record(v.id, "skipped", reason=reason)
        report(v, "skip", reason)

    typer.secho(
        f"\nDone: {counts['done']} written · {counts['skipped']} skipped · "
        f"{counts['failed']} failed"
        + (f" · {already} already-done" if already else ""),
        fg="bright_white", bold=True)
    if failures:
        typer.secho("Failures:", fg="red")
        for title, err in failures[:20]:
            typer.echo(f"  - {title[:60]}: {err}")
    # Land the user right where the files are (the channel subfolder) — absolute so
    # the path/link is clickable and the copy-paste command works from any cwd.
    folder = os.path.abspath(os.path.dirname(written_paths[-1]) if written_paths else opts.output_dir)
    uri = _file_uri(folder)
    typer.echo(f"\nOutput: {folder}")
    if sys.stdout.isatty():
        # Show the file:// URL as the link text: terminals that linkify URLs (Warp,
        # iTerm, Terminal.app) make it clickable; OSC-8 also wraps it for the rest.
        typer.secho("  " + _osc8(uri, uri), fg="bright_blue")
    typer.secho(f'  open it:  open "{folder}"', fg="bright_black")

    # Auto-reveal in Finder after an interactive pick (or with --open), unless --no-open.
    if written_paths and (opts.open_finder or interactive) and not opts.no_open:
        _reveal_in_finder(written_paths[-1])
        typer.secho("  ✓ opened in Finder", fg="green")
    return 1 if counts["failed"] and not counts["done"] else 0
