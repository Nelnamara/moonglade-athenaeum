"""The contest board's settled-row cache and newest-first walk (3.22, design 6).

Offline: a fake board serves pages from a list (page size 2, so a short list is many pages) and
counts which pages were read. Only a settled row is ever served from the cache, an unsettled
cached row is re-read wherever new contests have pushed it, and the cache is written atomically
through moonglade.paths."""
import json
import os

import pytest

from moonglade import contests as c
from moonglade import contest_sync


def raw(i, settled=True, updated="u1", **kw):
    r = {"id": str(i), "title": {"en": "C%s" % i}, "slug": "c%s" % i, "type": "community",
         "runtimeStatus": "ended" if settled else "running",
         "rewardStatus": "distributed" if settled else "pending_distribute",
         "updatedAt": updated, "description": {"en": "d%s" % i},
         "descriptionForApp": {"en": "d%s" % i}, "mediaId": ""}
    r.update(kw)
    return r


class Board:
    """The upstream board, newest-first, served two rows a page."""
    def __init__(self, rows):
        self.rows, self.reads = list(rows), []

    def page(self, session, page):
        self.reads.append(page)
        n = c._CONTEST_PAGE_SIZE
        chunk = self.rows[(page - 1) * n: page * n]
        return {"data": chunk, "page": page, "pageSize": n,
                "totalPage": max(1, -(-len(self.rows) // n)), "totalCount": len(self.rows)}


@pytest.fixture()
def rig(monkeypatch, tmp_path):
    monkeypatch.setattr(c, "_CONTEST_PAGE_SIZE", 2)
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    path = tmp_path / "cache" / "contest_board.json"

    class Rig:
        cache = path

        def use(self, board):
            self.board = board
            monkeypatch.setattr(c, "_board_page", board.page)
            return board

        def read(self, **kw):
            self.board.reads.clear()
            meta = {}
            rows = c.list_contests(object(), cache_path=path, meta=meta, **kw)
            return rows, meta, list(self.board.reads)
    return Rig()


def ids(rows):
    return [r["id"] for r in rows]


def test_the_first_read_is_a_full_walk_and_writes_the_cache(rig):
    rig.use(Board([raw(i) for i in range(10, 0, -1)]))
    rows, meta, reads = rig.read()
    assert reads == [1, 2, 3, 4, 5] and meta["mode"] == "full"
    assert ids(rows) == [str(i) for i in range(10, 0, -1)]
    saved = json.loads(rig.cache.read_text(encoding="utf-8"))
    assert set(saved["rows"]) == {str(i) for i in range(1, 11)}
    assert saved["rows"]["10"]["row"]["description"] == "d10"
    assert "descriptionForApp" not in json.dumps(saved)         # the copy is never kept
    assert not [f for f in os.listdir(rig.cache.parent) if ".tmp-" in f]


def test_the_cache_lives_under_moonglade_paths():
    from moonglade import paths
    assert c.contest_cache_path() == paths.cache_dir() / "contest_board.json"


def test_settled_pages_come_from_the_cache_and_an_unsettled_row_is_re_read_T_F8(rig):
    rows = [raw(i) for i in range(12, 0, -1)]            # six pages, all settled...
    rows[8] = raw(rows[8]["id"], settled=False)          # ...but the row on page 5
    rig.use(Board(rows))
    rig.read()
    rows, _meta, reads = rig.read()
    assert reads == [1, 5, 6]                            # page 1 clean -> jump to page 5; it is not clean, so 6 follows
    assert not {2, 3, 4} & set(reads)                    # the settled pages come from the cache
    assert len(rows) == 12


def test_unsettled_rows_are_never_served_from_the_cache(rig):
    board = rig.use(Board([raw(9), raw(8), raw(7, settled=False), raw(6), raw(5)]))
    rig.read()
    board.rows[2] = raw(7, settled=True, updated="u2", title={"en": "Renamed"})   # it ended
    rows, _m, reads = rig.read()
    assert 2 in reads
    assert [r["title"] for r in rows if r["id"] == "7"] == ["Renamed"]


def test_new_contests_shifting_an_unsettled_row_down_do_not_hide_it_T_V4(rig):
    base = [raw(i) for i in range(20, 8, -1)]            # ids 20..9, six pages
    base[3] = raw(17, settled=False)                     # unsettled at the end of page 2
    board = rig.use(Board(base))
    rig.read()
    # Three new contests land on top; the unsettled row slides from page 2 to page 3.
    board.rows = [raw(23, settled=False), raw(22, settled=False), raw(21, settled=False)] + board.rows
    board.rows[3 + 3] = raw(17, settled=False, updated="u9", title={"en": "Fresh"})
    rows, _m, reads = rig.read()
    assert 3 in reads                                    # re-read from its NEW page
    got = {r["id"]: r for r in rows}
    assert got["17"]["title"] == "Fresh"                 # fresh, not the cached copy
    assert {"21", "22", "23"} <= set(got)


def test_a_row_that_moved_off_the_pages_the_map_names_is_still_found(rig):
    base = [raw(i) for i in range(12, 0, -1)]
    base[1] = raw(11, settled=False)                     # page 1
    board = rig.use(Board(base))
    rig.read()
    # It sinks to the far end (a re-sort): the walk must keep reading until it sees it.
    moved = board.rows.pop(1)
    board.rows.append(moved)
    rows, _m, reads = rig.read()
    assert "11" in ids(rows) and reads[-1] == 6


def test_an_unsettled_row_gone_upstream_drops_off_after_a_full_read(rig):
    base = [raw(i) for i in range(8, 0, -1)]
    base[5] = raw(3, settled=False)
    board = rig.use(Board(base))
    rig.read()
    del board.rows[5]
    rows, _m, reads = rig.read()
    assert "3" not in ids(rows) and sorted(set(reads)) == [1, 2, 3, 4]


def test_pending_distribute_is_unsettled_and_cancelled_is_settled():
    assert not c._raw_settled(raw(1, settled=False))
    assert not c._raw_settled({"runtimeStatus": "ended", "rewardStatus": "pending_distribute"})
    assert c._raw_settled({"runtimeStatus": "running", "lifecycleStatus": "cancelled"})
    assert c._raw_settled({"runtimeStatus": "ended", "rewardStatus": "distributed"})


def test_a_settled_row_whose_updatedat_moved_is_read_again(rig):
    board = rig.use(Board([raw(i) for i in range(10, 0, -1)]))
    rig.read()
    board.rows[0] = raw(10, updated="u2")
    _rows, _m, reads = rig.read()
    assert reads == [1, 2]                               # page 1 changed: read on; page 2 is clean and nothing later can change


def test_a_full_walk_runs_on_refresh_and_once_a_day(rig, monkeypatch):
    rig.use(Board([raw(i) for i in range(10, 0, -1)]))
    rig.read()
    assert rig.read()[2] == [1]                          # nothing can change: page 1 only
    assert rig.read(full=True)[2] == [1, 2, 3, 4, 5]     # Refresh
    real = c.time.time
    monkeypatch.setattr(c.time, "time", lambda: real() + c.CONTEST_FULL_WALK_S + 5)
    assert rig.read()[1]["mode"] == "full"


def test_the_hundred_page_ceiling_bounds_the_walk_and_says_so(rig):
    rig.use(Board([raw(i) for i in range(210, 0, -1)]))   # 105 pages
    rows, meta, reads = rig.read()
    assert len(reads) == 100 and meta["truncated"] is True and meta["total_page"] == 105
    assert c._CONTEST_MAX_PAGES == 100


def test_the_running_view_is_filtered_locally_from_the_cached_board(rig):
    rig.use(Board([raw(6, settled=False), raw(5), raw(4, settled=False), raw(3)]))
    rig.read()
    rows, _m, _r = rig.read(active_only=True)
    assert ids(rows) == ["6", "4"]


def test_a_missing_or_corrupt_cache_is_just_a_full_walk(rig):
    rig.use(Board([raw(i) for i in range(4, 0, -1)]))
    rig.cache.parent.mkdir(parents=True)
    rig.cache.write_text("{not json", encoding="utf-8")
    assert rig.read()[1]["mode"] == "full"


def test_the_mapper_reads_descriptionforapp_when_description_is_absent():
    r = raw(1)
    del r["description"]
    assert c._contest_row(r)["description"] == "d1"
    r2 = raw(2, description={"en": "own"})
    assert c._contest_row(r2)["description"] == "own"


def test_the_board_read_goes_through_the_cache(monkeypatch):
    seen = {}
    monkeypatch.setattr(c, "list_contests", lambda s, **k: seen.update(k) or [])
    contest_sync._contests_cache.clear()
    contest_sync.contest_board(None, object(), full=True)
    assert seen["cache_path"] == c.contest_cache_path() and seen["full"] is True
    contest_sync._contests_cache.clear()
