"""The published-artwork list is read as a full query document (issue #88).

The 15-minute artworks sweep and `--sync-artworks` used to read the owner's published
artworks with a saved (hash-only) request. PixAI stopped recognizing it, the read swallowed
the error and returned None, and every sweep logged a bare "page 1 fetch failed" with no
reason while titles, likes and tags stopped refreshing. They now read the list with the
app's ad-hoc full-document road (`gql_adhoc`, a query), and say why a read failed.

What is pinned:

  * the document NEVER selects `views` (reading a view count registers a view on every work
    the query returns, and this read runs every fifteen minutes), and it selects exactly
    what the readers consume -- so a column cannot silently go blank, and a field cannot be
    added without a test noticing;
  * the walk still pages BACKWARD from the newest end (last / before), to the last page,
    and still stops at the page cap, with an incomplete walk never stamping the sweep;
  * a read that fails is said ONCE, in plain words, with its reason (folder paths hidden),
    and the sweep stays unfinished; `--sync-artworks` ends with a plain error;
  * the retired saved-request constants are gone.

NO REAL PIXAI: a FakePixAI answers the one `artworks` operation, exactly as
dev/tests/test_living_library.py drives the sweep.
"""
import inspect
import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from moonglade import backup as core
from moonglade import gallery as g
from moonglade.gallery import CATALOG_FIELDS, load_catalog, save_catalog

from tests.fake_pixai import FakePixAI

REPO = Path(__file__).resolve().parents[2]
DAY = 86400.0
NOW = 1_800_000_000.0            # 2027-01-15; the rows below are far older than 90 days
VIEWS = re.compile(r"\bviews\b")


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _node(mid, aid, likes=0, title="t"):
    """A node shaped like the document's selection, and nothing more."""
    return {"id": aid, "mediaId": mid, "videoMediaId": None, "title": title,
            "visibility": "PUBLIC", "isNsfw": False, "isSensitive": False,
            "likedCount": likes, "commentCount": 0, "aesScore": 6.0,
            "tacks": [{"codeName": "wolf", "displayName": "Wolf"}], "extra": {}}


def _refusal(code="GRAPHQL_VALIDATION_FAILED", message="PixAI said no to the request"):
    """The error the real client raises for a GraphQL refusal: the message text plus the
    structured list riding on `graphql_errors`."""
    errors = [{"message": message, "extensions": {"code": code}}]
    err = core.PixAIError("GraphQL error: " + json.dumps(errors))
    err.graphql_errors = errors
    return err


class _Library:
    """The owner's published list behind PixAI's one `artworks` operation: pages walked
    BACKWARD by the `before` cursor, newest page first, as PixAI's Relay connection is.
    The bulk view-count pass shares the operation name, so it is answered (empty) here
    too, and every document sent is kept for the tests to read."""

    def __init__(self, pages):
        self.pages = pages
        self.documents = []
        self.variables = []
        self.fetched = 0
        self.refuse_from = None          # page index from which reads raise
        self.refusal = None

    def __call__(self, call):
        self.documents.append(call.document)
        if VIEWS.search(call.document):
            return {"artworks": {"edges": [], "pageInfo": {"hasNextPage": False}}}
        self.variables.append(dict(call.variables or {}))
        before = (call.variables or {}).get("before")
        i = int(before) if before else 0
        self.fetched += 1
        if self.refuse_from is not None and i >= self.refuse_from:
            raise self.refusal
        nodes = self.pages[i] if i < len(self.pages) else []
        return {"artworks": {
            "edges": [{"node": n} for n in nodes],
            "pageInfo": {"hasPreviousPage": i + 1 < len(self.pages),
                         "startCursor": str(i + 1)}}}


class _Endless:
    """A list whose pageInfo never says "no more", to meet the page cap."""

    def __init__(self):
        self.fetched = 0

    def __call__(self, call):
        before = (call.variables or {}).get("before")
        i = int(before) if before else 0
        self.fetched += 1
        return {"artworks": {
            "edges": [{"node": _node("e%d" % i, "ea%d" % i)}],
            "pageInfo": {"hasPreviousPage": True, "startCursor": str(i + 1)}}}


@pytest.fixture(autouse=True)
def _fresh_sweep_state():
    """The sweep's stamps and its once-only refusal latch are module-level; reset them
    around every test so one test's sweep cannot colour the next."""
    state, said = dict(g._artworks_state), dict(g._artworks_refusal)
    g._artworks_state.update({"at": 0.0, "deep_at": 0.0, "changed": 0, "pages": 0,
                              "kicks": 0})
    g._artworks_refusal.update(reported=False)
    yield
    g._artworks_state.update(state)
    g._artworks_refusal.update(said)


@pytest.fixture()
def pixai(monkeypatch):
    """The transport the sweep and the sync build for themselves, faked at the seam."""
    fake = FakePixAI(user_id="u-test")
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: fake)
    monkeypatch.setattr(g.time, "sleep", lambda *_a, **_k: None)   # no real pacing waits
    return fake


def _library(pixai, pages):
    lib = _Library(pages)
    pixai.on("artworks", lib)
    return lib


def _catalog(tmp_path, mids):
    """A catalog holding a local row for each media id, none claiming an artwork yet, so
    every page of works is one the sweep has something to write for."""
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id=m, filename="f_%s.png" % m, created_at="2024-01-01T00:00:00Z")
                  for m in mids])
    return tmp_path / "catalog.db"


def _sweep(tmp_path, db, **kw):
    return g.artworks_sweep(tmp_path, db, force=True, now=NOW, **kw)


def _sweep_lines(caplog, level=logging.WARNING):
    return [r.getMessage() for r in caplog.records
            if r.levelno >= level and r.name == "moonglade.gallery"
            and r.getMessage().startswith("artworks sweep")]


# =====================================================================================
# 1. THE DOCUMENT -- never `views`, and exactly what the readers consume
# =====================================================================================

def _selection(doc, opener):
    """The text inside the braces that follow `opener` in a GraphQL document."""
    start = doc.index(opener) + len(opener)
    depth, i = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(doc[i], 0)
        i += 1
    return doc[start:i - 1]


def test_the_document_pages_backward_from_the_newest_end():
    """`last` / `before` start at the NEWEST end and `hasPreviousPage` / `startCursor` lead
    to the older works (PROBE_2026-10-16); `first` / `after` start at the OLDEST end, which
    would hand the sweep's two-spent-pages stop the wrong end of the history."""
    doc = " ".join(core._ARTWORK_LIST_DOC.split())
    assert "artworks(authorId: $a, last: $n, before: $before)" in doc
    assert not re.search(r"\b(first|after)\b", doc)


def test_the_document_never_selects_views():
    assert not VIEWS.search(core._ARTWORK_LIST_DOC)
    assert core._is_mutation_document(core._ARTWORK_LIST_DOC) is False


def test_the_document_asks_for_exactly_what_the_readers_consume():
    """The node fields are tied to the code that reads them, not to a list written beside
    it: whatever extract_artwork_meta takes off a node (plus the animation id the sweep and
    the sync read) must be selected, and nothing else may be. A field the reader gains
    without the document selecting it would blank a column quietly; a field the document
    gains without a reader is, in the worst case, `views`."""
    node = _selection(core._ARTWORK_LIST_DOC, "node {")
    bare = re.sub(r"\([^)]*\)", "", node)                  # drop displayName(language: $lang)
    nested = {"codeName", "displayName"}                    # the inside of tacks { ... }
    selected = set(re.findall(r"[A-Za-z_]\w*", re.sub(r"\{[^}]*\}", "", bare)))
    read = set(re.findall(r'node\.get\("(\w+)"\)', inspect.getsource(core.extract_artwork_meta)))
    read.add("videoMediaId")
    assert selected == read, (selected - read, read - selected)
    assert set(re.findall(r"[A-Za-z_]\w*", _selection(bare, "tacks {"))) == nested
    page_info = set(re.findall(r"[A-Za-z_]\w*", _selection(core._ARTWORK_LIST_DOC, "pageInfo {")))
    assert page_info == {"hasPreviousPage", "startCursor"}   # what the two walks read


def test_nothing_the_sweep_or_the_sync_sends_for_the_list_selects_views(pixai, tmp_path):
    """Measured on the wire, through the real sweep and the real sync: every document that
    reads the LIST is free of `views`. (The sync's separate bulk pass is the one place a
    view count is asked for, on its own cadence and behind --no-views.)"""
    db = _catalog(tmp_path, ["m1", "m2", "m3"])
    lib = _library(pixai, [[_node("m1", "a1")], [_node("m2", "a2")], [_node("m3", "a3")]])
    _sweep(tmp_path, db)
    core.run_sync_artworks(SimpleNamespace(out=str(tmp_path), token=None, delay=0,
                                           no_views=True))
    assert lib.documents and not any(VIEWS.search(d) for d in lib.documents)
    lib.documents.clear()
    core.run_sync_artworks(SimpleNamespace(out=str(tmp_path), token=None, delay=0))
    listing = [d for d in lib.documents if not VIEWS.search(d)]
    bulk = [d for d in lib.documents if VIEWS.search(d)]
    assert len(listing) == 3 and len(bulk) == 1


# =====================================================================================
# 2. THE READ -- one page, one ad-hoc POST, and every failure carries its reason
# =====================================================================================

def test_a_page_is_one_post_of_the_full_document():
    class Session:
        headers, cookies = {}, {}

        def __init__(self):
            self.calls = []

        def post(self, url, **kw):
            self.calls.append(("POST", url, kw))
            return SimpleNamespace(status_code=200, text="", content=b"{}", json=lambda: {
                "data": {"artworks": {"edges": [], "pageInfo": {"hasPreviousPage": False}}}})

        def get(self, url, **kw):
            self.calls.append(("GET", url, kw))
            raise AssertionError("the list is not a saved-request GET any more")

    s = Session()
    conn = core.artwork_list_gql(core.PixAIClient(s, user_id="u-wire"), before="c9", last=50)
    assert conn["pageInfo"] == {"hasPreviousPage": False}
    [(verb, url, kw)] = s.calls
    assert (verb, url) == ("POST", core.API_URL)
    assert kw["json"]["query"] == core._ARTWORK_LIST_DOC
    assert kw["json"]["variables"] == {"a": "u-wire", "n": 50, "lang": "en", "before": "c9"}


def test_the_first_page_sends_no_cursor_and_hands_back_the_connection(pixai):
    lib = _library(pixai, [[_node("m1", "a1")]])
    conn = core.artwork_list_gql(pixai, last=25)
    assert [e["node"]["id"] for e in conn["edges"]] == ["a1"]
    assert conn["pageInfo"]["hasPreviousPage"] is False
    assert lib.variables == [{"a": "u-test", "n": 25, "lang": "en"}]      # no `before`


def test_the_read_never_rides_the_saved_request_or_a_mutation():
    src = inspect.getsource(core.artwork_list_gql)
    assert "gql_adhoc(" in src
    assert ".persisted(" not in src and "gql_mutate" not in src and ".mutate(" not in src


def test_a_graphql_refusal_names_pixais_code_and_message(pixai):
    pixai.fail("artworks", _refusal("PERSISTED_QUERY_NOT_FOUND", "no such saved request"))
    with pytest.raises(core.ArtworkListRefused) as ex:
        core.artwork_list_gql(pixai)
    text = str(ex.value)
    assert "PERSISTED_QUERY_NOT_FOUND" in text and "no such saved request" in text
    assert text.startswith("PixAI refused the request (") and "GraphQL error" not in text


def test_a_network_failure_names_the_kind_of_failure(pixai):
    pixai.fail("artworks", requests.ConnectionError("connection reset by peer"))
    with pytest.raises(core.ArtworkListRefused) as ex:
        core.artwork_list_gql(pixai)
    assert "ConnectionError" in str(ex.value) and "connection reset" in str(ex.value)


def test_an_answer_without_a_list_is_a_refusal_too(pixai):
    pixai.on("artworks", {"somethingElse": {"ok": True}})
    with pytest.raises(core.ArtworkListRefused, match="no list of artworks"):
        core.artwork_list_gql(pixai)


def test_no_account_id_is_a_refusal_before_anything_is_sent():
    fake = FakePixAI(user_id="")
    with pytest.raises(core.ArtworkListRefused, match="account id"):
        core.artwork_list_gql(fake)
    assert fake.calls == []


# =====================================================================================
# 3. THE WALK -- to the end, stopping at the cap, never stamped when unfinished
# =====================================================================================

def test_the_sweep_walks_back_from_the_newest_page_to_the_last(pixai, tmp_path):
    db = _catalog(tmp_path, ["m1", "m2", "m3"])
    lib = _library(pixai, [[_node("m1", "a1")], [_node("m2", "a2")], [_node("m3", "a3")]])
    res = _sweep(tmp_path, db)
    assert res["pages"] == 3 and res["artworks"] == 3 and res["incomplete"] is False
    assert lib.fetched == 3
    assert [v.get("before") for v in lib.variables] == [None, "1", "2"]   # newest end first
    assert all(v["n"] == g.ARTWORKS_PAGE and v["a"] == "u-test" for v in lib.variables)
    assert {r["media_id"]: r["artwork_id"] for r in load_catalog(db)} == {
        "m1": "a1", "m2": "a2", "m3": "a3"}
    assert g._artworks_state["at"] == NOW, "a clean finish stamps the sweep"


def test_the_sweep_stops_at_the_page_cap_and_calls_itself_incomplete(
        pixai, tmp_path, monkeypatch):
    db = _catalog(tmp_path, ["e0", "e1", "e2", "e3"])
    lib = _Endless()
    pixai.on("artworks", lib)
    monkeypatch.setattr(g, "ARTWORKS_MAX_PAGES", 2)
    res = _sweep(tmp_path, db)
    assert lib.fetched == 2 and res["pages"] == 2 and res["incomplete"] is True
    assert g._artworks_state["at"] == 0.0 and g._artworks_state["deep_at"] == 0.0


def test_the_full_sync_walks_every_page_too(pixai, tmp_path):
    db = _catalog(tmp_path, ["m1", "m2", "m3"])
    lib = _library(pixai, [[_node("m1", "a1")], [_node("m2", "a2")], [_node("m3", "a3")]])
    res = core.run_sync_artworks(SimpleNamespace(out=str(tmp_path), token=None, delay=0,
                                                 no_views=True))
    assert res["artworks"] == 3 and res["matched"] == 3 and res["fail"] == 0
    assert [v.get("before") for v in lib.variables] == [None, "1", "2"]
    assert {r["media_id"]: r["artwork_id"] for r in load_catalog(db)} == {
        "m1": "a1", "m2": "a2", "m3": "a3"}


# =====================================================================================
# 4. A FAILED READ -- said once, with its reason; the sweep stays unfinished
# =====================================================================================

def test_a_refused_read_is_said_once_with_its_reason(pixai, tmp_path, caplog):
    db = _catalog(tmp_path, ["m1"])
    pixai.fail("artworks", _refusal("GRAPHQL_VALIDATION_FAILED", "PixAI would not take this"))
    with caplog.at_level(logging.DEBUG):
        results = [_sweep(tmp_path, db) for _ in range(3)]
    assert all(r["incomplete"] is True and r["pages"] == 0 for r in results)
    said = _sweep_lines(caplog)
    assert len(said) == 1, said                      # not a line every fifteen minutes
    assert "GRAPHQL_VALIDATION_FAILED" in said[0] and "PixAI would not take this" in said[0]
    assert "published artworks" in said[0]
    assert not any("fetch failed" in r.getMessage() for r in caplog.records)
    # ...and a refused sweep is not a finished one: no recent-guard, no 48-hour stamp
    assert g._artworks_state["at"] == 0.0 and g._artworks_state["deep_at"] == 0.0
    assert load_catalog(db)[0]["artwork_id"] == ""   # nothing was written


def test_it_is_said_again_once_a_read_has_worked_in_between(pixai, tmp_path, caplog):
    db = _catalog(tmp_path, ["m1"])
    with caplog.at_level(logging.DEBUG):
        pixai.fail("artworks", _refusal())
        _sweep(tmp_path, db)
        assert len(_sweep_lines(caplog)) == 1
        _library(pixai, [[_node("m1", "a1")]])               # PixAI answers again
        res = _sweep(tmp_path, db)
        assert res["incomplete"] is False
        again = _sweep_lines(caplog, logging.INFO)
        assert any("can be read from PixAI again" in m for m in again)
        pixai.fail("artworks", _refusal())                   # ...and refuses once more
        _sweep(tmp_path, db)
    assert len(_sweep_lines(caplog)) == 2


def test_a_later_page_that_cannot_be_read_keeps_the_earlier_pages(pixai, tmp_path, caplog):
    db = _catalog(tmp_path, ["m1", "m2"])
    lib = _library(pixai, [[_node("m1", "a1")], [_node("m2", "a2")]])
    lib.refuse_from, lib.refusal = 1, _refusal(message="page two was refused")
    with caplog.at_level(logging.DEBUG):
        res = _sweep(tmp_path, db)
    assert res["pages"] == 1 and res["changed"] == 1 and res["incomplete"] is True
    assert {r["media_id"]: r["artwork_id"] for r in load_catalog(db)} == {"m1": "a1", "m2": ""}
    [line] = _sweep_lines(caplog)
    assert "page 2" in line and "page two was refused" in line
    assert g._artworks_state["at"] == 0.0


def test_the_reason_leaves_folder_paths_out(pixai, tmp_path, caplog):
    db = _catalog(tmp_path, ["m1"])
    leaky = tmp_path / "certs" / "ca.pem"
    pixai.fail("artworks", requests.ConnectionError("cannot open {}".format(leaky)))
    with caplog.at_level(logging.DEBUG):
        _sweep(tmp_path, db)
    [line] = _sweep_lines(caplog)
    assert "ConnectionError" in line and "cannot open" in line
    assert str(tmp_path) not in line


def test_a_failed_first_page_ends_the_sync_with_a_plain_error(pixai, tmp_path):
    db = _catalog(tmp_path, ["m1"])
    pixai.fail("artworks", _refusal("GRAPHQL_VALIDATION_FAILED", "PixAI would not take this"))
    with pytest.raises(core.PixAIError) as ex:
        core.run_sync_artworks(SimpleNamespace(out=str(tmp_path), token=None, delay=0,
                                               no_views=True))
    text = str(ex.value)
    assert "published artworks" in text and "nothing was synced" in text
    assert "GRAPHQL_VALIDATION_FAILED" in text and "PixAI would not take this" in text
    for stale in ("ARTWORK_LIST_HASH", "recapture", "rotated", "config.json"):
        assert stale not in text
    assert load_catalog(db)[0]["artwork_id"] == ""


def test_a_failed_later_page_marks_the_sync_incomplete_and_says_why(pixai, tmp_path, capsys):
    db = _catalog(tmp_path, ["m1", "m2"])
    lib = _library(pixai, [[_node("m1", "a1")], [_node("m2", "a2")]])
    lib.refuse_from, lib.refusal = 1, _refusal(message="page two was refused")
    res = core.run_sync_artworks(SimpleNamespace(out=str(tmp_path), token=None, delay=0,
                                                 no_views=True))
    out = capsys.readouterr().out
    assert res["fail"] == 1 and res["artworks"] == 1
    assert "page two was refused" in out and "INCOMPLETE" in out
    assert {r["media_id"]: r["artwork_id"] for r in load_catalog(db)} == {"m1": "a1", "m2": ""}


# =====================================================================================
# 5. THE RETIRED SAVED REQUEST -- nothing is left behind
# =====================================================================================

def test_the_retired_saved_request_leaves_nothing_behind():
    assert not hasattr(core, "ARTWORK_LIST_HASH")
    assert not hasattr(core, "CLIENT_LIBRARY_ARTWORK")
    params = inspect.signature(core.PixAIClient.persisted).parameters
    assert "client_library" not in params and "headers" not in params
    assert "ARTWORK_LIST_HASH" not in (REPO / "config.example.json").read_text(encoding="utf-8")
    live_docs = [REPO / "README.md", REPO / "CLAUDE.md", REPO / "CONTRIBUTING.md",
                 *sorted((REPO / "wiki").glob("*.md"))]
    for doc in live_docs:
        assert "ARTWORK_LIST_HASH" not in doc.read_text(encoding="utf-8"), doc.name
    for module in (core, g):
        assert "ARTWORK_LIST_HASH" not in inspect.getsource(module)


def test_the_sweep_reads_each_page_once_and_the_command_keeps_the_retries(monkeypatch):
    """The fifteen-minute sweep makes one attempt per page (a stalled PixAI must not hold it for
    minutes; the next sweep is the retry), while --sync-artworks, run by hand, keeps gql_adhoc's
    default query retries."""
    import inspect
    from moonglade import backup as core
    from moonglade import gallery
    seen = []
    def fake_adhoc(session, query, variables=None, retries=None):
        seen.append(retries)
        return {"artworks": {"edges": [], "pageInfo": {"hasPreviousPage": False, "startCursor": None}}}
    monkeypatch.setattr(core, "gql_adhoc", fake_adhoc)
    monkeypatch.setattr(core, "_client_of", lambda s: type("C", (), {"user_id": "1"})())
    core.artwork_list_gql(object())
    assert seen == [None]
    src = inspect.getsource(gallery.artworks_sweep)
    assert "artwork_list_gql(session, before=before, last=ARTWORKS_PAGE, retries=0)" in src
