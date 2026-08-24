"""moonglade_similar: the CLIP visual-similarity sidecar. Pixeltable + torch are heavy and the
UDF needs a GPU, so every test mocks the table handle (_get_table) and, where needed,
indexed_ids — the logic under test (dedup, the row-by-row fallback, self-exclusion) is
pure Python around those. Importing the module pulls in pixeltable but no torch/model
(the model is lazy) and never touches Postgres."""
import pytest

pytest.importorskip("pixeltable")  # optional heavy dep, not in requirements.txt -- skip
# cleanly (not a collection error) for anyone who hasn't installed it, e.g. a fresh clone
# running plain `pytest`. CLAUDE.md's --ignore=tests/test_similar.py flag is still the
# documented way to exclude this file explicitly; this is the fallback for someone who
# doesn't know that yet.
import moonglade_similar as S


# --- fakes ---------------------------------------------------------------------

class FakeTable:
    """Records inserted rows. A batch insert aborts if it contains a media_id in
    fail_on (mimics Pixeltable aborting a batch on a corrupt image / PK clash); a
    single-row insert of a fail_on id raises (mimics the per-row retry hitting it)."""
    def __init__(self, fail_on=()):
        self.rows = []
        self.fail_on = set(fail_on)

    def insert(self, rows, on_error=None):
        if len(rows) > 1 and any(r["media_id"] in self.fail_on for r in rows):
            raise RuntimeError("batch aborted")
        for r in rows:
            if r["media_id"] in self.fail_on:
                raise RuntimeError("bad row")
            self.rows.append(r)

    def count(self):
        return len(self.rows)


class _Query:
    def __init__(self, rows):
        self._rows, self._n = rows, None

    def limit(self, n):
        self._n = n
        return self

    def select(self, *a, **k):
        return self

    def collect(self):
        return self._rows[: self._n] if self._n is not None else self._rows


class _Col:
    def similarity(self, **kw):        # image=... / string=...
        return object()


class FakeSimTable:
    media_id = object()

    def __init__(self, rows):
        self.img = _Col()
        self._rows = rows

    def order_by(self, *a, **k):
        return _Query(self._rows)


# --- sync: dedup + fault tolerance ---------------------------------------------

def test_sync_dedups_within_scan_and_vs_indexed(tmp_path, monkeypatch):
    f = tmp_path / "x.png"
    f.write_bytes(b"x")
    ft = FakeTable()
    monkeypatch.setattr(S, "_get_table", lambda: ft)
    monkeypatch.setattr(S, "indexed_ids", lambda: {"already"})

    # "already" is pre-indexed; "dup" appears in two files in one scan; "new" is fresh
    n = S.sync([("already", f), ("dup", f), ("dup", f), ("new", f)])

    assert [r["media_id"] for r in ft.rows] == ["dup", "new"]
    assert n == 2


def test_sync_skips_missing_files(tmp_path, monkeypatch):
    f = tmp_path / "x.png"
    f.write_bytes(b"x")
    ft = FakeTable()
    monkeypatch.setattr(S, "_get_table", lambda: ft)
    monkeypatch.setattr(S, "indexed_ids", lambda: set())

    n = S.sync([("here", f), ("gone", tmp_path / "nope.png")])

    assert [r["media_id"] for r in ft.rows] == ["here"]
    assert n == 1


def test_sync_row_by_row_fallback_skips_bad_row(tmp_path, monkeypatch):
    f = tmp_path / "x.png"
    f.write_bytes(b"x")
    ft = FakeTable(fail_on={"bad"})
    monkeypatch.setattr(S, "_get_table", lambda: ft)
    monkeypatch.setattr(S, "indexed_ids", lambda: set())

    # the whole batch aborts on "bad"; the fallback re-inserts row-by-row, dropping only it
    n = S.sync([("a", f), ("bad", f), ("b", f)], batch=400)

    assert [r["media_id"] for r in ft.rows] == ["a", "b"]
    assert S.sync.last_errors == 1
    assert n == 2


# --- scan_dir: quarantine exclusion ---------------------------------------------
# test_scan_dir_excludes_quarantine_dirs lived here (B11, audit 2026-07-21). It
# built a four-directory tmp tree and asserted scan_dir yielded only the live
# image. That is now the "similar.scan_dir" row of tests/test_library_scan.py's
# walker table, which asserts the same set on a fuller tree AND the two things
# this test could not see: the any-depth prune (a nested gallery/) and the
# narrower embeddable extension set. Deleted as a pure duplicate; scan_dir's
# remaining behaviour (the (media_id, path) shape, the cap) is exercised through
# sync/rebuild below.


# --- similar: self-exclusion + k limit -----------------------------------------

def test_similar_excludes_self_and_limits_k(monkeypatch):
    rows = [
        {"media_id": "self", "score": 1.0},   # the query's own row scores 1.0
        {"media_id": "a", "score": 0.91},
        {"media_id": "b", "score": 0.88},
        {"media_id": "c", "score": 0.80},
    ]
    monkeypatch.setattr(S, "_get_table", lambda: FakeSimTable(rows))

    res = S.similar("/any/path.png", k=2, exclude_media_id="self")

    assert [m for m, _ in res] == ["a", "b"]      # self dropped, capped at k=2
    assert all(isinstance(s, float) and s < 1.0 for _, s in res)


# --- the /api/similar Flask route (hydrate + fail-soft) ------------------------

def test_api_similar_route(tmp_path, monkeypatch):
    """Hydrates neighbours like /api/gallery-images, drops ids no longer in the catalog,
    and soft-404s an unknown media_id — the sidecar itself is mocked."""
    from moonglade_gallery import save_catalog, CATALOG_FIELDS
    from tests.conftest import login_client

    def row(**kw):
        return {f: "" for f in CATALOG_FIELDS} | kw

    save_catalog(tmp_path / "catalog.db", [
        row(media_id="q", filename="q.png", created_at="2025-01-01T00:00:00"),
        row(media_id="n1", filename="n1.png", created_at="2025-01-02T00:00:00"),
    ])
    (tmp_path / "q.png").write_bytes(b"x")   # so find_image_file resolves the query

    import moonglade_similar
    monkeypatch.setattr(moonglade_similar, "similar",
                        lambda p, k=24, exclude_media_id=None: [("n1", 0.9), ("gone", 0.8)])

    cli = login_client(tmp_path)
    d = cli.get("/api/similar/q").get_json()
    assert d["query"] == "q"
    assert [i["media_id"] for i in d["images"]] == ["n1"]        # "gone" not in catalog -> dropped
    assert d["images"][0]["score"] == 0.9
    assert d["images"][0]["thumb"] == "/thumbs/n1.jpg"
    assert cli.get("/api/similar/nope").status_code == 404       # unknown id, soft


# --- --sync-similar: the incremental entry point --------------------------------

def test_run_sync_similar_tops_up_and_never_rebuilds(tmp_path, monkeypatch):
    """--sync-similar must go through sync() and must NEVER drop the table.

    This is the whole point of the flag. Before it existed, the only way to reach the
    already-incremental sync() was rebuild(), which drops the table first -- so the single
    available action was also the most destructive one. On 2026-07-26 a machine-wide memory
    exhaustion killed a rebuild at 75%, and reaching for the only button on offer would have
    discarded the 26,400 rows that survived and cost ~38 min instead of ~12.

    rebuild is stubbed to RAISE rather than merely counted: if this entry point is ever rewired
    through it, the test fails loudly at the call instead of on a subtle assertion afterwards."""
    import moonglade_backup as core

    calls = []

    def fake_sync(items, progress=None, batch=400):
        calls.append("sync")
        return 8706
    fake_sync.last_errors = 0

    def never(*a, **k):
        raise AssertionError("--sync-similar must never call rebuild() -- it drops the table")

    monkeypatch.setattr(S, "is_available", lambda: True)
    monkeypatch.setattr(S, "scan_dir", lambda out: [("a", "p")])
    monkeypatch.setattr(S, "count", lambda: 26400)
    monkeypatch.setattr(S, "sync", fake_sync)
    monkeypatch.setattr(S, "rebuild", never)

    class Args:
        out = str(tmp_path)
        progress = None

    core.run_sync_similar(Args())

    assert calls == ["sync"]


def test_run_sync_similar_reports_an_already_complete_index(tmp_path, monkeypatch):
    """Adding nothing is a normal, successful outcome -- the index was already complete. It must
    read that way rather than looking like a job that silently did nothing, which is exactly how
    the empty-index bug hid for three days on the /api/similar route."""
    import moonglade_backup as core

    def fake_sync(items, progress=None, batch=400):
        return 0
    fake_sync.last_errors = 0

    monkeypatch.setattr(S, "is_available", lambda: True)
    monkeypatch.setattr(S, "scan_dir", lambda out: [])
    monkeypatch.setattr(S, "count", lambda: 35106)
    monkeypatch.setattr(S, "sync", fake_sync)

    class Args:
        out = str(tmp_path)
        progress = None

    core.run_sync_similar(Args())   # must not raise, must not sys.exit
