"""The interactive multi-select picker (Textual).

DataTable for columnar + sortable display (virtualized → smooth at 1000+ rows),
a custom selection layer (DataTable has no native multi-select), a live fuzzy
filter (textual.fuzzy), and background enrichment that fills the captions/views
columns for the rows you can actually see (capped) plus everything you select."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Input, Static

from scribe import routing
from scribe.fmt import fmt_date, fmt_duration, fmt_hms, fmt_views
from scribe.models import VideoMeta

# CC badge text + style per route.
_BADGE = {
    "caption": ("cc", "green"),
    "asr": ("asr", "yellow"),
    "skip": ("—", "dim"),
    "unknown": ("·", "dim"),
}

_SORT_KEYS: dict[str, Callable[[VideoMeta], object]] = {
    "date": lambda v: v.upload_date or "",
    "dur": lambda v: v.duration or 0,
    "views": lambda v: v.view_count if v.view_count is not None else -1,
    "cc": lambda v: routing.route(v),
    "title": lambda v: v.title.lower(),
}

# How many on-screen rows to auto-enrich (caption/views) in the background. Bounds
# the work for huge channels; the rest fill in as you scroll or select them.
_AUTO_ENRICH_CAP = 80


class _SelectTable(DataTable):
    """DataTable tuned for the picker:
    - Enter confirms the picker (own binding → never hijacks the Ctrl+P palette).
    - A single mouse click on a row toggles it (Textual's default needs a second
      click on the already-highlighted row before it selects).
    - A click on a column header sorts by that column."""

    def action_select_cursor(self) -> None:
        self.app.action_confirm()

    async def _on_click(self, event) -> None:
        meta = event.style.meta
        row = meta.get("row")
        col = meta.get("column")
        if row is not None and row >= 0:        # data row → move cursor + toggle (1 click)
            self.move_cursor(row=row)
            self.app.action_toggle()
            event.stop()
        elif row == -1 and col is not None:     # column header → sort by it (exactly once)
            try:
                key = str(self.ordered_columns[col].key.value)
            except Exception:
                key = ""
            if key in _SORT_KEYS:
                self.app.action_sort(key)
            event.stop()
        else:
            await super()._on_click(event)


class PickerApp(App):
    CSS = """
    #header {
        dock: top; height: 1; padding: 0 2;
        background: $primary; color: $text; text-style: bold;
    }
    #filter { dock: top; background: $surface; }
    #filter:focus { background: $boost; }
    #status {
        dock: bottom; height: 1; padding: 0 2;
        background: $panel; color: $text-muted;
    }
    DataTable { height: 1fr; padding: 0 1; background: $background; }
    DataTable > .datatable--header { text-style: bold; color: $accent; }
    """
    BINDINGS = [
        ("space", "toggle", "Select"),
        ("a", "all", "All"),
        ("n", "none", "None"),
        ("i", "invert", "Invert"),
        ("v", "range", "Range"),
        ("slash", "filter", "Filter"),
        ("d", "sort('date')", "Date"),
        ("u", "sort('dur')", "Duration"),
        ("w", "sort('views')", "Views"),
        ("c", "sort('cc')", "Captions"),
        ("t", "sort('title')", "Title"),
        # Enter is handled by _SelectTable.action_select_cursor when the table is
        # focused; this app-level binding is just for the footer label (NOT
        # priority — priority would hijack the Ctrl+P command palette's Enter).
        ("enter", "confirm", "Transcribe"),
        ("escape", "focus_table", "Leave filter"),
        ("q", "cancel", "Quit"),
    ]

    def __init__(self, videos: list[VideoMeta] | None = None,
                 loader: Callable[[], Iterable[VideoMeta]] | None = None,
                 source=None, lang: str | None = None,
                 header: str | None = None, theme: str | None = None,
                 persist_theme: bool = False,
                 title: str = "scribe — pick videos") -> None:
        super().__init__()
        self._theme = theme or "nord"
        self._persist_theme = persist_theme
        # De-dup by id: DataTable row keys must be unique (playlists repeat videos).
        self.videos: list[VideoMeta] = list({v.id: v for v in (videos or [])}.values())
        self.by_id: dict[str, VideoMeta] = {v.id: v for v in self.videos}
        self.selected: set[str] = set()
        self._order: list[str] = []           # selection order (the order you chose)
        self.shown: list[VideoMeta] = []
        self._loader = loader
        self._source = source
        self._lang = lang
        self._filter = ""
        self._sort_key: str | None = None
        self._sort_reverse = False
        self._anchor_id: str | None = None
        self._executor = None
        self._enriching: set[str] = set()    # in-flight enrich ids (dedup submissions)
        self._alive = True
        self._header_label = header or "scribe"
        self.result: list[VideoMeta] | None = None
        self.title = title

    # ---- layout ----------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        yield Input(placeholder="Type to filter by title…  (Esc/Enter = back to list)", id="filter")
        yield _SelectTable(id="table", cursor_type="row", zebra_stripes=True)
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.theme = self._theme            # users can switch live via Ctrl+P
        except Exception:
            pass
        t = self.table
        t.cell_padding = 2                       # breathing room between columns
        t.add_column(" ", key="mark", width=3)
        t.add_column("Date", key="date", width=10)
        t.add_column("Dur", key="dur", width=7)
        t.add_column("Views", key="views", width=7)
        t.add_column("CC", key="cc", width=5)
        t.add_column("Title", key="title")
        t.focus()
        if self._source is not None:
            from concurrent.futures import ThreadPoolExecutor
            self._executor = ThreadPoolExecutor(max_workers=8)
        self._update_header()
        if self.videos:
            self._refresh()
        elif self._loader is not None:
            self._set_status("Loading…")
            self._load()

    def on_unmount(self) -> None:
        self._alive = False
        if self._persist_theme:                  # remember a live theme change (Ctrl+P)
            try:
                from scribe.config import save_last_theme
                save_last_theme(self.theme)
            except Exception:
                pass
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    # ---- convenience -----------------------------------------------------
    @property
    def table(self) -> DataTable:
        return self.query_one("#table", DataTable)

    def _mark_cell(self, v: VideoMeta) -> Text:
        return (Text("◉", style="bold green") if v.id in self.selected
                else Text("◯", style="dim"))

    def _title_cell(self, v: VideoMeta) -> Text:
        return Text(v.title, style="bold green" if v.id in self.selected else "")

    def _cc_cell(self, v: VideoMeta) -> Text:
        label, style = _BADGE[routing.route(v)]
        return Text(label, style=style)

    def _row_cells(self, v: VideoMeta) -> tuple:
        muted = "dim" if v.id not in self.selected else "green"
        return (self._mark_cell(v),
                Text(fmt_date(v.upload_date), style=muted),
                Text(fmt_duration(v.duration), justify="right", style=muted),
                Text(fmt_views(v.view_count), justify="right", style=muted),
                self._cc_cell(v),
                self._title_cell(v))

    # ---- data flow -------------------------------------------------------
    def _visible(self) -> list[VideoMeta]:
        rows = self.videos
        if self._filter:
            from textual.fuzzy import Matcher
            m = Matcher(self._filter)
            rows = [v for v in rows if m.match(v.title) > 0]
        if self._sort_key:
            rows = sorted(rows, key=_SORT_KEYS[self._sort_key], reverse=self._sort_reverse)
        return rows

    def _refresh(self) -> None:
        self._anchor_id = None          # any reorder/filter invalidates a pending range
        t = self.table
        t.clear()
        self.shown = self._visible()
        for v in self.shown:
            t.add_row(*self._row_cells(v), key=v.id)
        self._auto_enrich()
        self._update_status()
        self._update_header()

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def _update_status(self) -> None:
        sel = [self.by_id[i] for i in self.selected if i in self.by_id]
        est = routing.estimate(sel)
        parts = [f"{est.total} selected",
                 f"{est.caption} captioned (instant)",
                 f"{est.asr} ASR (~{fmt_hms(est.asr_seconds)}, ~{est.temp_mb:.0f}MB)"]
        if est.skip:
            parts.append(f"{est.skip} skip(non-EN)")
        if est.unknown:
            parts.append(f"{est.unknown} probing…")
        self._set_status("  ·  ".join(parts))

    def _update_header(self) -> None:
        bits = [f"scribe — {self._header_label}",
                f"{len(self.shown)}/{len(self.videos)}",
                f"◉ {len(self.selected)} selected"]
        if self._sort_key:
            bits.append(f"sort {self._sort_key} {'▼' if self._sort_reverse else '▲'}")
        if self._filter:
            bits.append(f"filter “{self._filter}”")
        self.query_one("#header", Static).update("  ·  ".join(bits))

    # ---- background enrichment -------------------------------------------
    def _enqueue_enrich(self, metas: list[VideoMeta]) -> None:
        if self._executor is None:
            return
        for m in metas:
            if m.enriched or m.id in self._enriching:
                continue
            self._enriching.add(m.id)
            self._executor.submit(self._enrich_one, m)

    def _auto_enrich(self) -> None:
        # Fill captions/views for the rows the user can actually see (capped).
        self._enqueue_enrich(self.shown[:_AUTO_ENRICH_CAP])

    def _enrich_one(self, m: VideoMeta) -> None:
        try:
            self._source.enrich([m])
        except Exception:
            m.enriched = True
            m.caption_langs = m.caption_langs or []
        if not self._alive:
            return
        try:
            self.call_from_thread(self._on_enriched, m)
        except RuntimeError:
            pass

    def _on_enriched(self, m: VideoMeta) -> None:
        self._enriching.discard(m.id)
        if any(v.id == m.id for v in self.shown):
            self._repaint_row(m)
        self._update_status()

    # ---- selection actions ----------------------------------------------
    def _cursor_meta(self) -> VideoMeta | None:
        try:
            i = self.table.cursor_row          # may be gone during teardown
        except Exception:
            return None
        if 0 <= i < len(self.shown):
            return self.shown[i]
        return None

    def _repaint_row(self, v: VideoMeta) -> None:
        for key, cell in zip(("mark", "date", "dur", "views", "cc", "title"),
                             self._row_cells(v)):
            try:
                self.table.update_cell(v.id, key, cell)
            except Exception:
                pass

    def _select_id(self, vid: str) -> None:
        if vid not in self.selected:
            self.selected.add(vid)
            self._order.append(vid)

    def _deselect_id(self, vid: str) -> None:
        self.selected.discard(vid)
        if vid in self._order:
            self._order.remove(vid)

    def _toggle(self, v: VideoMeta) -> None:
        if v.id in self.selected:
            self._deselect_id(v.id)
        else:
            self._select_id(v.id)
            self._enqueue_enrich([v])
        self._repaint_row(v)
        self._update_status()
        self._update_header()

    def action_toggle(self) -> None:
        v = self._cursor_meta()
        if v is not None:
            self._toggle(v)

    def action_all(self) -> None:
        newly = [v for v in self.shown if v.id not in self.selected]
        for v in self.shown:
            self._select_id(v.id)
        self._enqueue_enrich(newly)
        self._refresh()

    def action_none(self) -> None:
        for v in list(self.shown):
            self._deselect_id(v.id)
        self._refresh()

    def action_invert(self) -> None:
        newly = []
        for v in self.shown:
            if v.id in self.selected:
                self._deselect_id(v.id)
            else:
                self._select_id(v.id)
                newly.append(v)
        self._enqueue_enrich(newly)
        self._refresh()

    def action_range(self) -> None:
        cur = self.table.cursor_row
        if self._anchor_id is None:
            m = self._cursor_meta()
            if m is not None:
                self._anchor_id = m.id
                self._set_status(f"Range anchor at row {cur + 1} — press v again at the other end.")
            return
        lo_idx = next((i for i, v in enumerate(self.shown) if v.id == self._anchor_id), None)
        self._anchor_id = None
        if lo_idx is None:
            return
        lo, hi = sorted((lo_idx, cur))
        span = self.shown[lo:hi + 1]
        newly = [v for v in span if v.id not in self.selected]
        for v in span:
            self._select_id(v.id)
        self._enqueue_enrich(newly)
        self._refresh()

    # ---- sort / filter / nav --------------------------------------------
    def action_sort(self, key: str) -> None:
        self._sort_reverse = not self._sort_reverse if self._sort_key == key else False
        self._sort_key = key
        self._refresh()

    def action_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_focus_table(self) -> None:
        self.table.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._filter = event.value.strip()
        self._refresh()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.table.focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        # Fill captions/views for rows scrolled into focus beyond the initial cap.
        if not self._alive:
            return
        m = self._cursor_meta()
        if m is not None:
            self._enqueue_enrich([m])


    # ---- finish ----------------------------------------------------------
    def action_confirm(self) -> None:
        if isinstance(self.focused, Input):     # Enter in the filter = back to list
            self.table.focus()
            return
        if self.selected:                        # honor the order you selected in
            self.result = [self.by_id[i] for i in self._order if i in self.by_id]
        else:                                    # nothing ticked → transcribe the highlighted one
            m = self._cursor_meta()
            self.result = [m] if m else []
        self.exit(self.result)

    def action_cancel(self) -> None:
        self.result = None
        self.exit(None)

    # ---- background load -------------------------------------------------
    def _load(self) -> None:
        def worker() -> None:
            try:
                collected: list[VideoMeta] = list(self._loader())
            except Exception as e:  # noqa: BLE001 — surface listing failures, don't hang on "Loading…"
                if self._alive:
                    try:
                        self.call_from_thread(
                            self._set_status, f"Failed to list videos: {e}  (press q to quit)")
                    except RuntimeError:
                        pass
                return
            if self._alive:
                try:
                    self.call_from_thread(self._set_videos, collected)
                except RuntimeError:
                    pass

        # run_worker takes a plain callable; the @work decorator expects a method
        # (it reads args[0] as self) and crashes on a zero-arg closure.
        self.run_worker(worker, thread=True, name="enumerate")

    def _set_videos(self, vids: list[VideoMeta]) -> None:
        self.videos = list({v.id: v for v in vids}.values())
        self.by_id = {v.id: v for v in self.videos}
        # Use the real channel name in the header once we have it.
        if self.videos and self.videos[0].channel:
            self._header_label = self.videos[0].channel
        self._refresh()
        if not self.videos:
            self._set_status("No videos found (press q to quit).")


def run_picker(videos=None, loader=None, source=None, lang=None, header=None,
               theme=None) -> list[VideoMeta] | None:
    """Run the picker; return the selected videos, or None if cancelled."""
    app = PickerApp(videos=videos, loader=loader, source=source, lang=lang,
                    header=header, theme=theme, persist_theme=True)
    return app.run()
