"""tools/harvest_api_surface.py -- the build fingerprint and the per-crawl chunk cache.

Two defects measured 2026-08-16 and fixed together:

  1. `fetch` used to record the CDN path label (`app-1.0.2605`) as the build and `diff` treated
     a changed label as "new build". The label stayed put from 2026-07-25 to 2026-08-16 while
     902 of 967 content-hashed chunk filenames changed underneath it. The build is now the
     sorted set of chunk names the homepage references, and `diff` reports chunk churn.
  2. `extract` mined every *.js in a flat chunks/ that `fetch` never cleared, so the catalog
     became a union of >=3 builds and "first chunk wins" could keep a stale document. Chunks
     are now cached per crawl under chunks/<fingerprint>/ and `extract` reads only the crawl
     recorded in build.json.

Everything here runs against tmp_path: the module's OUT/CHUNKS/CATALOG/... constants are
monkeypatched, and `fetch` gets a fake `requests` module, so no test touches the real
private/harvest cache or the network."""
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "harvest_api_surface.py"
_spec = importlib.util.spec_from_file_location("harvest_api_surface", _TOOL)
h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h)


# ------------------------------------------------------------------ fixtures
@pytest.fixture
def out(tmp_path, monkeypatch):
    """Point every on-disk path the tool uses at this test's tmp_path."""
    root = tmp_path / "harvest"
    monkeypatch.setattr(h, "OUT", root)
    monkeypatch.setattr(h, "CHUNKS", root / "chunks")
    monkeypatch.setattr(h, "CATALOG", root / "operations.json")
    monkeypatch.setattr(h, "PREVIOUS", root / "operations.prev.json")
    monkeypatch.setattr(h, "BUILD_JSON", root / "build.json")
    monkeypatch.setattr(h, "LEGACY_BUILD_TXT", root / "build.txt")
    monkeypatch.setattr(h, "DELAY", 0)
    return root


def _chunk_js(op_name, field):
    """A JS chunk carrying one pre-parsed GraphQL Document literal (unquoted keys, exactly the
    shape the bundle uses) for a query named `op_name` that selects `field`."""
    return ('var q={kind:"Document",definitions:[{kind:"OperationDefinition",operation:"query",'
            'name:{kind:"Name",value:"%s"},variableDefinitions:[],directives:[],'
            'selectionSet:{kind:"SelectionSet",selections:[{kind:"Field",'
            'name:{kind:"Name",value:"%s"}}]}}]};export{q};' % (op_name, field))


def _write_crawl(chunks_root, fp, files):
    d = chunks_root / fp
    d.mkdir(parents=True)
    for name, text in files.items():
        (d / name).write_text(text, encoding="utf-8")
    return d


def _build_json(path, fp, label="app-1.0.2605"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"label": label, "fingerprint": fp, "referenced": []}),
                    encoding="utf-8")


def _catalog(build, ops):
    return {"site": h.SITE, "build": build, "derivation": "typename,no-newline",
            "hashes_proven": True,
            "operations": [{"name": n, "kind": "query", "variables": {}, "hash": hsh,
                            "chunk": "x.js", "document": "{ x }"} for n, hsh in ops]}


# ------------------------------------------------------------------ fingerprint
def test_fingerprint_is_the_chunk_set_not_the_label():
    a = h._fingerprint(["entry-AAAA.js", "shared-SSSS.js"])
    assert a == h._fingerprint(["shared-SSSS.js", "entry-AAAA.js", "entry-AAAA.js"]), \
        "order and duplicates must not matter"
    assert a != h._fingerprint(["entry-BBBB.js", "shared-SSSS.js"]), \
        "one re-hashed chunk is a different build"
    assert len(a) == 12 and int(a, 16) >= 0


# ------------------------------------------------------------------ extract
def test_extract_mines_only_the_current_crawl(out, capsys):
    """Two crawl dirs side by side -- the current one and a stale one that ALSO defines
    listUserBookmarks (differently) plus an operation the current build no longer ships.
    Only the current crawl may reach the catalog."""
    chunks = out / "chunks"
    _write_crawl(chunks, "aaaaaaaaaaaa", {
        "utils-NEW1.js": _chunk_js("listUserBookmarks", "currentField"),
        "page-NEW2.js": _chunk_js("getMyInfo", "id"),
    })
    _write_crawl(chunks, "bbbbbbbbbbbb", {           # sorts FIRST -- would win under the old code
        "utils-OLD1.js": _chunk_js("listUserBookmarks", "staleField"),
        "gone-OLD2.js": _chunk_js("staleOnlyOperation", "id"),
    })
    # A loose leftover of the pre-partition flat layout must be ignored too.
    (chunks / "utils-LOOSE.js").write_text(_chunk_js("looseOnlyOperation", "id"), encoding="utf-8")
    _build_json(out / "build.json", "aaaaaaaaaaaa")

    h.cmd_extract(types.SimpleNamespace())

    cat = json.loads((out / "operations.json").read_text(encoding="utf-8"))
    names = {o["name"]: o for o in cat["operations"]}
    assert set(names) == {"listUserBookmarks", "getMyInfo"}
    assert "currentField" in names["listUserBookmarks"]["document"]
    assert "staleField" not in names["listUserBookmarks"]["document"]
    assert names["listUserBookmarks"]["chunk"] == "utils-NEW1.js"
    # The catalog's build block is the fingerprint + the chunk list of THIS crawl only.
    assert cat["build"]["fingerprint"] == "aaaaaaaaaaaa"
    assert cat["build"]["label"] == "app-1.0.2605"
    assert cat["build"]["chunks"] == ["page-NEW2.js", "utils-NEW1.js"]
    assert "mining 2 chunks from crawl aaaaaaaaaaaa" in capsys.readouterr().out


def test_extract_flags_same_name_conflicts_inside_one_crawl(out, capsys):
    """Within ONE crawl, first chunk still wins -- but a same-name/different-document pair is
    now reported instead of silently swallowed."""
    _write_crawl(out / "chunks", "cccccccccccc", {
        "a-first.js": _chunk_js("listUserBookmarks", "fromFirst"),
        "b-second.js": _chunk_js("listUserBookmarks", "fromSecond"),
        "c-same.js": _chunk_js("listUserBookmarks", "fromFirst"),     # identical: not a conflict
    })
    _build_json(out / "build.json", "cccccccccccc")
    h.cmd_extract(types.SimpleNamespace())
    cat = json.loads((out / "operations.json").read_text(encoding="utf-8"))
    assert cat["operations"][0]["chunk"] == "a-first.js"
    assert "fromFirst" in cat["operations"][0]["document"]
    assert "1 same-name/different-document conflicts" in capsys.readouterr().out


def test_extract_refuses_a_flat_pre_partition_cache(out):
    """The old layout (loose *.js + build.txt, no build.json) is not silently mined as if it
    were a crawl -- the message says to run fetch."""
    (out / "chunks").mkdir(parents=True)
    (out / "chunks" / "utils-OLD.js").write_text(_chunk_js("listUserBookmarks", "x"),
                                                  encoding="utf-8")
    (out / "build.txt").write_text("app-1.0.2605\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        h.cmd_extract(types.SimpleNamespace())
    assert "run `fetch` first" in str(e.value)
    assert not (out / "operations.json").exists()


def test_extract_keeps_operations_prev_semantics(out):
    """operations.json -> operations.prev.json on every extract, exactly as before."""
    _write_crawl(out / "chunks", "dddddddddddd", {"u.js": _chunk_js("getMyInfo", "id")})
    _build_json(out / "build.json", "dddddddddddd")
    (out / "operations.json").write_text('{"marker": "older"}', encoding="utf-8")
    h.cmd_extract(types.SimpleNamespace())
    prev = json.loads((out / "operations.prev.json").read_text(encoding="utf-8"))
    assert prev == {"marker": "older"}
    assert "getMyInfo" in (out / "operations.json").read_text(encoding="utf-8")


# ------------------------------------------------------------------ fetch
class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


class _FakeSession:
    """Serves a canned homepage + chunk bodies; records every URL asked for."""
    def __init__(self, pages):
        self.pages, self.headers, self.calls = pages, {}, []

    def get(self, url, timeout=None):
        self.calls.append(url)
        return _Resp(self.pages[url]) if url in self.pages else _Resp("", 404)


CDN = "https://cdn.example/artifacts/app-1.0.2605"


def _site(session, entry, shared, lazy):
    """Homepage referencing `entry` + `shared`; `entry` lazily imports `lazy`. Same label always."""
    session.pages[h.SITE] = (
        '<link rel="modulepreload" href="{0}/assets/{1}">'
        '<link rel="modulepreload" href="{0}/assets/{2}">'.format(CDN, entry, shared))
    session.pages["{}/assets/{}".format(CDN, entry)] = 'import("./assets/{}");'.format(lazy)
    session.pages["{}/assets/{}".format(CDN, shared)] = _chunk_js("listUserBookmarks", "s")
    session.pages["{}/assets/{}".format(CDN, lazy)] = _chunk_js("getMyInfo", "id")


@pytest.fixture
def fake_requests(monkeypatch):
    session = _FakeSession({})
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(Session=lambda: session))
    return session


def test_fetch_partitions_the_cache_per_crawl_and_reuses_by_name(out, fake_requests, capsys):
    """Two builds under the SAME CDN label: each gets its own chunks/<fingerprint>/ dir, the
    second one reuses the unchanged shared chunk from the first (no CDN request), and a loose
    pre-partition file with a matching name is adopted rather than re-downloaded."""
    args = types.SimpleNamespace(max_chunks=1500)
    chunks = out / "chunks"

    # --- build 1
    _site(fake_requests, "entry-AAAA.js", "shared-SSSS.js", "lazy-LLLL.js")
    h.cmd_fetch(args)
    b1 = json.loads((out / "build.json").read_text(encoding="utf-8"))
    fp1 = b1["fingerprint"]
    assert b1["label"] == "app-1.0.2605"
    assert fp1 == h._fingerprint(["entry-AAAA.js", "shared-SSSS.js"])
    assert sorted(p.name for p in (chunks / fp1).glob("*.js")) == [
        "entry-AAAA.js", "lazy-LLLL.js", "shared-SSSS.js"]
    assert b1["crawled"] == 3 and b1["referenced"] == ["entry-AAAA.js", "shared-SSSS.js"]

    # --- build 2: entry + lazy re-hashed, shared unchanged, label identical. Also plant a loose
    #     legacy copy of the new lazy chunk and a stale build.txt, as the pre-fix cache had.
    (chunks / "lazy-MMMM.js").write_text(_chunk_js("getMyInfo", "id"), encoding="utf-8")
    (out / "build.txt").write_text("app-1.0.2605\n", encoding="utf-8")
    fake_requests.pages.clear()
    fake_requests.calls.clear()
    _site(fake_requests, "entry-BBBB.js", "shared-SSSS.js", "lazy-MMMM.js")
    h.cmd_fetch(args)
    text = capsys.readouterr().out
    b2 = json.loads((out / "build.json").read_text(encoding="utf-8"))
    fp2 = b2["fingerprint"]

    assert fp2 != fp1 and b2["label"] == b1["label"], "same label, different build"
    assert "NEW BUILD" in text and "NOT a build fingerprint" in text
    # Both crawls intact, side by side; build 2 has exactly its own three chunks.
    assert sorted(p.name for p in (chunks / fp1).glob("*.js")) == [
        "entry-AAAA.js", "lazy-LLLL.js", "shared-SSSS.js"]
    assert sorted(p.name for p in (chunks / fp2).glob("*.js")) == [
        "entry-BBBB.js", "lazy-MMMM.js", "shared-SSSS.js"]
    # shared-SSSS came from the sibling crawl and lazy-MMMM from the loose file: neither hit
    # the CDN. Only the homepage and the genuinely new entry chunk were requested.
    asked = [u.rsplit("/", 1)[-1] for u in fake_requests.calls]
    assert asked == ["pixai.art", "entry-BBBB.js"], asked
    assert "reused-by-name 2" in text
    assert not (chunks / "lazy-MMMM.js").exists(), "loose legacy file is MOVED into the crawl"
    assert (chunks / fp1 / "shared-SSSS.js").exists(), "sibling's copy is left in place"
    assert not (out / "build.txt").exists(), "superseded label pointer is removed"


# ------------------------------------------------------------------ diff
def test_diff_reports_chunk_churn_alongside_operations(out, capsys):
    old = _catalog({"label": "app-1.0.2605", "fingerprint": "111111111111",
                    "chunks": ["a-1.js", "b-1.js", "shared-S.js"]},
                   [("keepSame", "h1"), ("keepMoved", "h2"), ("removedOp", "h3")])
    new = _catalog({"label": "app-1.0.2605", "fingerprint": "222222222222",
                    "chunks": ["a-2.js", "b-2.js", "c-2.js", "shared-S.js"]},
                   [("keepSame", "h1"), ("keepMoved", "h2x"), ("addedOp", "h4")])
    out.mkdir(parents=True)
    (out / "operations.prev.json").write_text(json.dumps(old), encoding="utf-8")
    (out / "operations.json").write_text(json.dumps(new), encoding="utf-8")

    h.cmd_diff(types.SimpleNamespace())
    text = capsys.readouterr().out
    assert "BUILD CHANGED: app-1.0.2605 [111111111111] -> app-1.0.2605 [222222222222]" in text
    assert "same label -- the label is not a fingerprint" in text
    assert "chunks     (5 changed): 1 kept, 3 new, 2 gone   [4 now, 3 before]" in text
    assert "added      (1): addedOp" in text
    assert "removed    (1): removedOp" in text
    assert "hash moved (1): keepMoved" in text


def test_diff_same_fingerprint_says_so(out, capsys):
    b = {"label": "app-1.0.2605", "fingerprint": "333333333333", "chunks": ["a.js"]}
    same = json.dumps(_catalog(b, [("x", "h")]))
    out.mkdir(parents=True)
    (out / "operations.prev.json").write_text(same, encoding="utf-8")
    (out / "operations.json").write_text(same, encoding="utf-8")
    h.cmd_diff(types.SimpleNamespace())
    text = capsys.readouterr().out
    assert "build unchanged: app-1.0.2605 [333333333333]" in text
    assert "chunks     (0 changed): 1 kept, 0 new, 0 gone" in text


def test_diff_against_a_pre_fingerprint_catalog_degrades_honestly(out, capsys):
    """operations.prev.json from before 2026-08-16 has `build` as a bare label string and no
    chunk list. diff must neither crash nor claim the build is unchanged on label alone."""
    old = _catalog("app-1.0.2605", [("x", "h")])
    new = _catalog({"label": "app-1.0.2605", "fingerprint": "444444444444", "chunks": ["a.js"]},
                   [("x", "h")])
    out.mkdir(parents=True)
    (out / "operations.prev.json").write_text(json.dumps(old), encoding="utf-8")
    (out / "operations.json").write_text(json.dumps(new), encoding="utf-8")
    h.cmd_diff(types.SimpleNamespace())
    text = capsys.readouterr().out
    assert "app-1.0.2605 [no fingerprint] -> app-1.0.2605 [444444444444]" in text
    assert "label alone cannot say whether the build changed" in text
    assert "previous catalog carries no chunk list" in text
    assert "build unchanged" not in text and "BUILD CHANGED" not in text


def test_show_prints_label_and_fingerprint(out, capsys):
    out.mkdir(parents=True)
    (out / "operations.json").write_text(json.dumps(_catalog(
        {"label": "app-1.0.2605", "fingerprint": "555555555555", "chunks": []},
        [("getMyInfo", "h")])), encoding="utf-8")
    h.cmd_show(types.SimpleNamespace(grep=""))
    assert "build app-1.0.2605 [555555555555]   hashes PROVEN" in capsys.readouterr().out
