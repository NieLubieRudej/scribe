"""Headless picker tests via Textual's Pilot — covers the 1000-row gate (G5),
the custom multi-select, fuzzy filter, sort, range, and confirm."""

import asyncio
import time

from scribe.models import VideoMeta
from scribe.tui.app import PickerApp


def _make(n: int) -> list[VideoMeta]:
    return [
        VideoMeta(
            id=f"id{i:04d}", title=f"Video {i} about topic {i % 10}", url=f"http://x/{i}",
            duration=60 + i, view_count=i * 100,
            upload_date=f"2026{(i % 12) + 1:02d}{(i % 28) + 1:02d}",
            caption_langs=(["en"] if i % 2 == 0 else []), language="en", enriched=True,
        )
        for i in range(n)
    ]


def run(coro):
    return asyncio.run(coro)


def test_mount_1000_and_select_bindings():
    app = PickerApp(videos=_make(1000))

    async def scenario():
        t0 = time.perf_counter()
        async with app.run_test(size=(120, 40)) as pilot:
            mount = time.perf_counter() - t0
            assert len(app.shown) == 1000, "all rows shown"
            assert mount < 5.0, f"mount too slow: {mount:.2f}s"
            await pilot.press("space")
            assert len(app.selected) == 1
            await pilot.press("a")
            assert len(app.selected) == 1000
            await pilot.press("n")
            assert len(app.selected) == 0
            print(f"\n[G5] mounted 1000 rows in {mount:.2f}s")

    run(scenario())


def test_fuzzy_filter_and_sort():
    app = PickerApp(videos=_make(500))

    async def scenario():
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("slash")          # focus filter
            await pilot.press("9")              # type into filter
            assert app._filter == "9"
            assert 0 < len(app.shown) < 500     # fuzzy filtered
            # clear filter, sort by duration ascending
            app._filter = ""
            app.action_sort("dur")
            assert app.shown[0].duration <= app.shown[-1].duration
            app.action_sort("dur")              # toggle → descending
            assert app.shown[0].duration >= app.shown[-1].duration

    run(scenario())


def test_range_select_and_confirm():
    app = PickerApp(videos=_make(50))

    async def scenario():
        async with app.run_test(size=(120, 40)) as pilot:
            app.table.move_cursor(row=2)
            app.action_range()                  # anchor at shown[2]'s id
            assert app._anchor_id == app.shown[2].id
            app.table.move_cursor(row=6)
            app.action_range()                  # select rows 2..6 inclusive
            assert len(app.selected) == 5
            await pilot.press("enter")          # confirm via the REAL key (DataTable RowSelected)
        assert app.result is not None and len(app.result) == 5

    run(scenario())


def test_mouse_single_click_toggles_row():
    app = PickerApp(videos=_make(10))

    async def scenario():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.click("#table", offset=(20, 2))   # one click selects
            await pilot.pause()
            assert len(app.selected) == 1
            await pilot.click("#table", offset=(20, 2))   # click again deselects
            await pilot.pause()
            assert len(app.selected) == 0

    run(scenario())


def test_header_click_sorts():
    app = PickerApp(videos=_make(10))

    async def scenario():
        async with app.run_test(size=(120, 30)) as pilot:
            assert app._sort_key is None
            await pilot.click("#table", offset=(50, 0))   # click a column header
            await pilot.pause()
            assert app._sort_key is not None

    run(scenario())


def test_header_click_reverses_sort():
    app = PickerApp(videos=_make(10))

    async def scenario():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.click("#table", offset=(12, 0))   # sort by a column
            await pilot.pause()
            first = app._sort_reverse
            await pilot.click("#table", offset=(12, 0))   # click again → reverse
            await pilot.pause()
            assert app._sort_reverse != first

    run(scenario())


def test_picker_persists_theme_on_exit(monkeypatch):
    import scribe.config as cfg
    saved = {}
    monkeypatch.setattr(cfg, "save_last_theme", lambda name: saved.__setitem__("t", name))
    app = PickerApp(videos=_make(3), theme="dracula", persist_theme=True)

    async def scenario():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()

    run(scenario())
    assert saved.get("t") == "dracula"


def test_enter_binding_is_not_priority():
    # A priority Enter binding hijacks the Ctrl+P command palette (and modals).
    app = PickerApp(videos=_make(3))
    for b in app.BINDINGS:
        key = b[0] if isinstance(b, tuple) else getattr(b, "key", None)
        if key == "enter":
            assert getattr(b, "priority", False) is False


def test_command_palette_enter_does_not_exit_picker():
    app = PickerApp(videos=_make(5))

    async def scenario():
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("ctrl+p")          # open the command palette
            await pilot.pause()
            await pilot.press("enter")           # must act in the palette, NOT confirm-exit
            await pilot.pause()
            assert app.is_running                 # picker still alive
            assert app.result is None

    run(scenario())


def test_enter_with_no_selection_transcribes_highlighted():
    app = PickerApp(videos=_make(10))

    async def scenario():
        async with app.run_test(size=(120, 40)) as pilot:
            app.table.move_cursor(row=3)
            assert len(app.selected) == 0
            await pilot.press("enter")          # smart: no ticks → use the highlighted row
        assert app.result is not None and len(app.result) == 1
        assert app.result[0].id == app.shown[3].id

    run(scenario())


def test_selection_order_is_preserved():
    app = PickerApp(videos=_make(10))

    async def scenario():
        async with app.run_test(size=(120, 40)) as pilot:
            for row in (5, 1, 8):
                app.table.move_cursor(row=row)
                app.action_toggle()
            await pilot.press("enter")
        ids = [v.id for v in app.result]
        assert ids == [app.shown[5].id, app.shown[1].id, app.shown[8].id]

    run(scenario())


def test_range_anchor_cleared_on_sort():
    app = PickerApp(videos=_make(50))

    async def scenario():
        async with app.run_test(size=(120, 40)) as pilot:
            app.table.move_cursor(row=2)
            app.action_range()
            assert app._anchor_id is not None
            app.action_sort("title")            # reorder must invalidate the stale anchor
            assert app._anchor_id is None

    run(scenario())


def test_loader_path_populates_in_background():
    # Exercises on_mount -> _load -> run_worker(thread) -> _set_videos (the
    # interactive enumeration path; previously untested).
    vids = _make(7)
    app = PickerApp(loader=lambda: iter(vids))

    async def scenario():
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(app.shown) == 7

    run(scenario())


def test_loader_error_does_not_hang_or_crash():
    def boom():
        raise RuntimeError("Sign in to confirm you're not a bot")

    app = PickerApp(loader=boom)

    async def scenario():
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(app.shown) == 0          # surfaced, not crashed/hung

    run(scenario())


def test_duplicate_ids_are_deduped():
    app = PickerApp(videos=_make(5) + _make(5))   # same ids twice → must not crash

    async def scenario():
        async with app.run_test(size=(120, 40)):
            assert len(app.shown) == 5

    run(scenario())


def test_none_is_scoped_to_shown():
    app = PickerApp(videos=_make(20))

    async def scenario():
        async with app.run_test(size=(120, 40)):
            app.action_all()
            assert len(app.selected) == 20
            app._filter = "9"
            app._refresh()
            shown_ids = {v.id for v in app.shown}
            assert 0 < len(shown_ids) < 20
            app.action_none()                   # clears only the filtered subset
            assert len(app.selected) == 20 - len(shown_ids)

    run(scenario())
