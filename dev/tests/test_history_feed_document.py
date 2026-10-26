"""The history feed is read as a full query document, everywhere (issue #89).

Sync now, `--sync`, `--update`, `--count`, `--probe`, the video sync and the deleted-reconcile
read the owner's history with `gql`, which used to replay a saved (hash-only) request. PixAI
answered that request from a cache part of the time and refused it the rest (about one read in
five on the owner's install on 2026-10-25), its own site no longer sends it, and one refusal
ended the run at that page. `gql` now POSTs the full document (`_HISTORY_PAGE_DOC`) through
`gql_adhoc`, as the Live Mirror's catch-up and the published-artworks sweep already did.

What is pinned:

  * the read is one ad-hoc POST of the document with the page variables, never a saved GET,
    and its answer feeds `find_connection`;
  * PixAI's passing "Internal server error" on a big page earns one wait (through
    `_history_wait`, recorded here) and one more ask, then one ask at 2,000 rows with the same
    `before`; any other GraphQL refusal is `HistoryPageRefused` at once, in plain words;
    network errors and a 401 raise untouched;
  * an answer with no page in it (a body that is not GraphQL) is that refusal too, never an
    empty history: the count prints no partial total, and the deleted-reconcile flags nothing
    after a walk that did not reach the oldest page;
  * each of the six readers reads through the document, and a walk carries on from the page's
    own `startCursor` even when the page came back smaller than asked;
  * `--count` asks 2,000 a page by default, and a refusal reaches the user as the sentence;
  * the retired saved request leaves nothing behind.

NO REAL PIXAI: a FakePixAI answers the document (keyed by its first root field, `user`), the
way dev/tests/test_artworks_adhoc.py drives the artwork list.
"""
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from moonglade import backup as core
from moonglade import gallery as g
from moonglade.gallery import CATALOG_FIELDS, load_catalog, save_catalog

from tests.fake_pixai import operation_name

REPO = Path(__file__).resolve().parents[2]
FEED = operation_name(core._HISTORY_PAGE_DOC)       # what the fake keys the document by


def _node(tid, mid=None, **kw):
    return {"id": tid, "status": "completed", "mediaId": mid or "m_" + tid,
            "batchMediaIds": [], "createdAt": "2024-01-01T00:00:00Z",
            "promptsPreview": "p " + tid, **kw}


def _answer(nodes, has_prev=False, cursor=""):
    """The document's answer shape: the connection under user.taskSummaries."""
    return {"user": {"id": "u-test", "taskSummaries": {
        "pageInfo": {"hasNextPage": False, "hasPreviousPage": has_prev,
                     "endCursor": "e", "startCursor": cursor},
        "edges": [{"node": n} for n in nodes]}}}


def _refusal(message, code="GRAPHQL_VALIDATION_FAILED"):
    """What the real client raises for a GraphQL answer: the message text plus the structured
    list riding on `graphql_errors` (PixAIClient._graphql_post)."""
    errors = [{"message": message, "path": ["user", "taskSummaries"],
               "extensions": {"code": code}}]
    err = core.PixAIError("GraphQL error: " + json.dumps(errors))
    err.graphql_errors = errors
    return err


def _internal():
    """PixAI's passing failure on a big page, as PROBE_2026-10-25 recorded it."""
    return _refusal("Internal server error", "INTERNAL_SERVER_ERROR")


class _History:
    """The owner's history behind the document: pages walked BACKWARD by the `before` cursor,
    newest page first. Page i answers `startCursor` "c<i+1>", and `before` "c<i>" asks for page
    i. `script` is a list of answers handed out first, one per ask (an exception is raised);
    once it is spent, the pages answer. Every ask's variables are kept."""

    def __init__(self, pages, script=()):
        self.pages = pages
        self.script = list(script)
        self.variables = []

    def __call__(self, call):
        assert call.verb == "query" and call.document == core._HISTORY_PAGE_DOC
        self.variables.append(dict(call.variables or {}))
        if self.script:
            a = self.script.pop(0)
            if isinstance(a, BaseException):
                raise a
            return a
        before = (call.variables or {}).get("before")
        i = int(before[1:]) if before else 0
        nodes = self.pages[i] if i < len(self.pages) else []
        return _answer(nodes, has_prev=i + 1 < len(self.pages), cursor="c%d" % (i + 1))


@pytest.fixture()
def waits(monkeypatch):
    """Every wait gql takes after an internal-server failure, recorded instead of taken."""
    seen = []
    monkeypatch.setattr(core, "_history_wait", seen.append)
    return seen


def _history(pixai, pages, script=()):
    h = _History(pages, script)
    pixai.on(FEED, h)
    return h


def _catalog(tmp_path, rows):
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | r for r in rows])
    return tmp_path / "catalog.db"


# =====================================================================================
# 1. THE DOCUMENT -- a query, paged backward, the one road
# =====================================================================================

def test_the_document_is_a_query_paged_backward():
    doc = " ".join(core._HISTORY_PAGE_DOC.split())
    assert core._is_mutation_document(doc) is False
    assert "taskSummaries(last: $last, before: $before)" in doc
    for name in ("$userId", "$last", "$before"):
        assert name in doc
    assert "hasPreviousPage" in doc and "startCursor" in doc     # what every walk reads


def test_a_page_is_one_post_of_the_full_document():
    class Session:
        headers, cookies = {}, {}

        def __init__(self):
            self.calls = []

        def post(self, url, **kw):
            self.calls.append(("POST", url, kw))
            return SimpleNamespace(status_code=200, text="", content=b"{}",
                                   json=lambda: {"data": _answer([_node("T1")])})

        def get(self, url, **kw):
            raise AssertionError("the history feed is not a saved-request GET any more")

    s = Session()
    variables = core.page_variables(250, "u-wire", before="c9")
    data = core.gql(core.PixAIClient(s), variables)
    [(verb, url, kw)] = s.calls
    assert (verb, url) == ("POST", core.API_URL)
    assert kw["json"] == {"query": core._HISTORY_PAGE_DOC,
                          "variables": {"last": 250, "userId": "u-wire", "before": "c9"}}
    conn = core.find_connection(data)                        # the result shape feeds it
    assert [e["node"]["id"] for e in conn["edges"]] == ["T1"]


def test_through_the_fake_it_is_a_query_and_never_a_saved_request(pixai):
    h = _history(pixai, [[_node("T1")]])
    data = core.gql(pixai, core.page_variables(30, "u-test"))
    assert core.find_connection(data)["pageInfo"]["hasPreviousPage"] is False
    assert [c.verb for c in pixai.calls] == ["query"]
    assert h.variables == [{"last": 30, "userId": "u-test"}]


def test_the_read_never_rides_the_saved_request_or_a_mutation():
    src = inspect.getsource(core.gql)
    assert "gql_adhoc(" in src
    assert ".persisted(" not in src and "gql_mutate" not in src and ".mutate(" not in src


# =====================================================================================
# 2. A REFUSAL -- the passing internal-server failure, and everything else
# =====================================================================================

def test_an_internal_server_error_waits_five_seconds_and_asks_again(waits):
    """Through the real client's error shape: the answer carries `errors` with PixAI's own
    "Internal server error", and the identical request answers after the wait."""
    class Session:
        headers, cookies = {}, {}

        def __init__(self, bodies):
            self.bodies, self.sent = list(bodies), []

        def post(self, url, **kw):
            self.sent.append(kw["json"]["variables"])
            body = self.bodies.pop(0)
            return SimpleNamespace(status_code=200, text="", content=b"{}", json=lambda: body)

    failed = {"errors": [{"message": "Internal server error", "path": ["user", "taskSummaries"],
                          "extensions": {"code": "INTERNAL_SERVER_ERROR"}}], "data": None}
    s = Session([failed, {"data": _answer([_node("T1")])}])
    data = core.gql(core.PixAIClient(s), {"last": 5000, "userId": "u1"})
    assert waits == [5.0] == [core.HISTORY_RETRY_WAIT_S]
    assert s.sent == [{"last": 5000, "userId": "u1"}] * 2       # the same request, twice
    assert core.find_connection(data)["edges"][0]["node"]["id"] == "T1"


def test_a_second_failure_at_5000_asks_once_more_at_2000_with_the_same_before(pixai, waits):
    h = _history(pixai, [], script=[_internal(), _internal(), _answer([_node("T1")])])
    data = core.gql(pixai, {"last": 5000, "userId": "u-test", "before": "c7"})
    assert h.variables == [{"last": 5000, "userId": "u-test", "before": "c7"},
                           {"last": 5000, "userId": "u-test", "before": "c7"},
                           {"last": 2000, "userId": "u-test", "before": "c7"}]
    assert waits == [5.0]
    assert core.find_connection(data)["edges"][0]["node"]["id"] == "T1"


def test_the_2000_row_ask_failing_too_is_a_refusal(pixai, waits):
    _history(pixai, [], script=[_internal(), _internal(), _internal()])
    with pytest.raises(core.HistoryPageRefused) as ei:
        core.gql(pixai, {"last": 5000, "userId": "u-test"})
    assert str(ei.value) == core.HISTORY_REFUSED
    assert len(pixai.calls) == 3


def test_a_second_failure_at_500_is_a_refusal_in_plain_words(pixai, waits):
    h = _history(pixai, [], script=[_internal(), _internal()])
    with pytest.raises(core.HistoryPageRefused) as ei:
        core.gql(pixai, {"last": 500, "userId": "u-test"})
    assert str(ei.value) == ("PixAI refused the history feed; nothing was changed -- try "
                             "again in a minute.")
    assert isinstance(ei.value, core.PixAIError)                # every catch site holds
    assert ei.value.__cause__.graphql_errors[0]["message"] == "Internal server error"
    assert len(h.variables) == 2 and waits == [5.0]             # no smaller page below 2000


def test_another_refusal_is_refused_at_once_with_no_retry(pixai, waits):
    cause = _refusal("Cannot query field \"taskSummaries\" on type \"User\".")
    h = _history(pixai, [], script=[cause])
    with pytest.raises(core.HistoryPageRefused) as ei:
        core.gql(pixai, {"last": 5000, "userId": "u-test"})
    assert ei.value.__cause__ is cause
    assert str(ei.value) == core.HISTORY_REFUSED
    assert len(h.variables) == 1 and waits == []


def test_a_different_refusal_after_the_wait_is_refused_too(pixai, waits):
    h = _history(pixai, [], script=[_internal(), _refusal("Cannot query field \"x\".")])
    with pytest.raises(core.HistoryPageRefused):
        core.gql(pixai, {"last": 5000, "userId": "u-test"})
    assert len(h.variables) == 2 and waits == [5.0]


@pytest.mark.parametrize("error", [requests.ConnectionError("connection reset by peer"),
                                   requests.HTTPError("HTTP 502")],
                         ids=["network", "5xx"])
def test_a_network_error_or_a_5xx_raises_untouched(pixai, waits, error):
    pixai.fail(FEED, error)
    with pytest.raises(type(error)) as ei:
        core.gql(pixai, {"last": 250, "userId": "u-test"})
    assert ei.value is error
    assert len(pixai.calls) == 1 and waits == []


def test_a_401_raises_untouched(pixai, waits):
    error = core.PixAIError("401 Unauthorized -- API key missing/expired.")
    pixai.fail(FEED, error)
    with pytest.raises(core.PixAIError) as ei:
        core.gql(pixai, {"last": 250, "userId": "u-test"})
    assert ei.value is error and not isinstance(ei.value, core.HistoryPageRefused)
    assert waits == []


@pytest.mark.parametrize("status", [200, 400, 403])
def test_an_answer_that_is_not_graphql_is_a_refusal_not_an_empty_history(status, waits):
    """`{"message": "Forbidden"}` -- an edge's or a stale credential's own JSON, with neither
    `data` nor `errors` -- comes back from the ad-hoc POST as {} at a 200, a 400 or a 403. With
    no page in it, every caller would read that as the end of the feed (a partial count
    printed as the whole library, a catch-up that saw nothing missed, a pull "caught up").
    It is a refusal, in the same plain words, after one ask."""
    class Session:
        headers, cookies = {}, {}

        def __init__(self):
            self.posts = 0

        def post(self, url, **kw):
            self.posts += 1
            return SimpleNamespace(status_code=status, text="", content=b"{}",
                                   json=lambda: {"message": "Forbidden"})

    s = Session()
    with pytest.raises(core.HistoryPageRefused) as ei:
        core.gql(core.PixAIClient(s), {"last": 250, "userId": "u1"})
    assert str(ei.value) == core.HISTORY_REFUSED
    assert "no history page" in str(ei.value.__cause__)
    assert s.posts == 1 and waits == []


def test_a_user_with_no_generations_is_not_refused(pixai):
    """The empty history is still a page: a connection with no edges."""
    _history(pixai, [])
    data = core.gql(pixai, core.page_variables(250, "u-test"))
    assert core.find_connection(data)["edges"] == []
    assert core.find_connection(data)["pageInfo"]["hasPreviousPage"] is False


def test_the_sentence_never_speaks_of_a_hash():
    for stale in ("hash", "Recapture", "recapture", "config.json", "GraphQL"):
        assert stale not in core.HISTORY_REFUSED


# =====================================================================================
# 3. THE SIX READERS -- each reads through the document
# =====================================================================================

def test_the_quick_count_reads_through_the_document(pixai):
    h = _history(pixai, [[_node("T1"), _node("T2", batchMediaIds=["m_T2", "b1"])],
                         [_node("T3")]])
    assert core._quick_count(pixai, page_size=500) == 4
    assert [v.get("before") for v in h.variables] == [None, "c1"]
    assert all(v["last"] == 500 for v in h.variables)


def test_the_probe_reads_through_the_document(pixai, monkeypatch, capsys):
    _history(pixai, [[_node("T1", mid="M1"), _node("T2")]])
    monkeypatch.setattr(core, "resolve_media",
                        lambda s, mid: ("https://cdn/" + mid, {"width": 2, "height": 3}))
    core.run_probe(SimpleNamespace(token=None, page_size=250))
    out = capsys.readouterr().out
    assert "OK -- 2 items. hasPreviousPage=False" in out
    assert "First task: id=T1 media_ids=['M1']" in out
    assert [c.verb for c in pixai.calls] == ["query"]


def test_the_count_reads_through_the_document(pixai, tmp_path, capsys):
    """The mutation proof for the road: with `gql` back on the saved request, the fake has no
    answer for it and this fails."""
    h = _history(pixai, [[_node("T1"), _node("T2")], [_node("T3")]])
    core.run_count(SimpleNamespace(token=None, out=str(tmp_path), delay=0))
    out = capsys.readouterr().out
    assert "Total tasks (generations) : 3" in out and "Fetched in 2 request(s)." in out
    assert [c.verb for c in pixai.calls] == ["query", "query"]
    assert [v.get("before") for v in h.variables] == [None, "c1"]
    assert all(v["last"] == core.COUNT_PAGE_SIZE == 2000 for v in h.variables)


def test_the_count_walks_on_from_a_smaller_page_s_own_cursor(pixai, tmp_path, capsys, waits):
    """A 5000-row page PixAI fails twice comes back as a 2000-row page; the walk then asks
    for the page before THAT page's startCursor, at the size it was given -- it never assumes
    it got what it asked for."""
    h = _history(pixai, [[_node("T1")], [_node("T2")]],
                 script=[_internal(), _internal(), _answer([_node("T1")], True, "c1")])
    core.run_count(SimpleNamespace(token=None, out=str(tmp_path), delay=0,
                                   count_page_size=5000))
    assert [(v["last"], v.get("before")) for v in h.variables] == [
        (5000, None), (5000, None), (2000, None), (5000, "c1")]
    assert "Total tasks (generations) : 2" in capsys.readouterr().out


def test_the_video_sync_reads_through_the_document(pixai, tmp_path, monkeypatch, capsys):
    _catalog(tmp_path, [{"media_id": "m0", "filename": "a.png"}])
    h = _history(pixai, [[_node("T1"), _node("T2")],
                         [_node("V1", i2vProModel="v4.0.1")]])
    monkeypatch.setattr(core, "_parallel_map", lambda *a, **k: iter(()))   # no downloads
    res = core.run_sync_videos(SimpleNamespace(out=str(tmp_path), token=None, page_size=250,
                                               workers=1, delay=0))
    assert res == {"i2v_tasks": 1, "videos": 0}
    assert "Found 1 image-to-video task(s) across 3 generations." in capsys.readouterr().out
    assert [v.get("before") for v in h.variables] == [None, "c1"]


def test_the_deleted_reconcile_reads_through_the_document(pixai, tmp_path):
    old = "2024-01-01T00:00:00"
    db = _catalog(tmp_path, [
        {"media_id": "a", "task_id": "LIVE1", "filename": "a.png", "created_at": old},
        {"media_id": "b", "task_id": "GONE", "filename": "b.png", "created_at": old},
        {"media_id": "c", "task_id": "LIVE2", "filename": "c.png", "created_at": old}])
    h = _history(pixai, [[_node("LIVE1")], [_node("LIVE2")]])
    res = core.run_reconcile_deleted(SimpleNamespace(out=str(tmp_path), token=None,
                                                     page_size=250))
    assert res == {"live": 2, "flagged": 1, "cleared": 0}
    assert {r["media_id"]: r["deleted_remote"] for r in load_catalog(db)} == {
        "a": "", "b": "1", "c": ""}
    assert [v.get("before") for v in h.variables] == [None, "c1"]


@pytest.mark.parametrize("second", [
    {},                                              # no page in the answer
    _answer([], has_prev=True, cursor="c2"),         # an empty page, older ones said to exist
    _refusal("Cannot query field \"x\"."),           # PixAI's refusal
], ids=["no-page", "empty-page-with-older", "refused"])
def test_a_reconcile_walk_that_ends_early_flags_nothing(pixai, tmp_path, second):
    """Every row missing from the walk's live set is flagged, so a walk that stopped before
    the oldest page must flag nothing: LIVE2 and LIVE3 still exist on PixAI, and the gallery
    offers flagged rows for a bulk local Delete under 'Deleted on PixAI'."""
    old = "2024-01-01T00:00:00"
    db = _catalog(tmp_path, [
        {"media_id": m, "task_id": t, "filename": m + ".png", "created_at": old}
        for m, t in (("a", "LIVE1"), ("b", "LIVE2"), ("c", "LIVE3"))])
    _history(pixai, [], script=[_answer([_node("LIVE1")], True, "c1"), second])
    with pytest.raises(core.PixAIError):
        core.run_reconcile_deleted(SimpleNamespace(out=str(tmp_path), token=None,
                                                   page_size=250))
    assert {r["media_id"]: r["deleted_remote"] for r in load_catalog(db)} == {
        "a": "", "b": "", "c": ""}


def test_an_empty_page_while_older_ones_exist_says_the_feed_ended_early(pixai, tmp_path):
    _catalog(tmp_path, [{"media_id": "a", "task_id": "LIVE1", "filename": "a.png",
                         "created_at": "2024-01-01T00:00:00"}])
    _history(pixai, [], script=[_answer([_node("LIVE1")], True, "c1"),
                                _answer([], has_prev=True, cursor="c2")])
    with pytest.raises(core.PixAIError, match="ended early -- nothing was flagged"):
        core.run_reconcile_deleted(SimpleNamespace(out=str(tmp_path), token=None,
                                                   page_size=250))


def _pull_args(out, **kw):
    base = dict(out=str(out), token=None, page_size=20, max=0, delay=0, name_length=40,
                name_sep="_", organize_live=False, convert=None, jpeg_quality=92,
                jpeg_bg="white", keep_webp=False, collect_only=False, full_meta=False,
                update=False, update_grace=2)
    base.update(kw)
    return SimpleNamespace(**base)


def _no_downloads(monkeypatch):
    monkeypatch.setattr(core, "_quick_count", lambda *a, **k: 3)
    monkeypatch.setattr(core, "resolve_media",
                        lambda s, mid: ("http://x/" + mid, {"width": "1", "height": "1"}))

    def fake_download(session, url, stem, **kw):
        dest = stem.with_suffix(".webp")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"img")
        return ("ok", dest)
    monkeypatch.setattr(core, "download", fake_download)


@pytest.mark.parametrize("workers", [1, 4], ids=["serial", "parallel"])
def test_the_pull_walks_back_with_before_and_ends_where_it_ended_before(
        pixai, tmp_path, monkeypatch, workers):
    _no_downloads(monkeypatch)
    h = _history(pixai, [[_node("T1")], [_node("T2")], [_node("T3")]])
    res = core.run_download(_pull_args(tmp_path, workers=workers))
    assert [v.get("before") for v in h.variables] == [None, "c1", "c2"]
    assert all(v["last"] == 20 and v["userId"] == "u-test" for v in h.variables)
    assert res["pages"] == 3 and res["reached_end"] is True and res["ok"] == 3
    assert core.walk_end_reached(tmp_path) is True               # the end was seen
    assert {r["media_id"] for r in load_catalog(tmp_path / "catalog.db")} == {
        "m_T1", "m_T2", "m_T3"}


def test_a_refused_page_ends_the_pull_without_claiming_the_end(pixai, tmp_path, monkeypatch):
    _no_downloads(monkeypatch)
    _history(pixai, [[_node("T1")], [_node("T2")]],
             script=[_answer([_node("T1")], True, "c1"), _refusal("Cannot query field \"x\".")])
    with pytest.raises(core.HistoryPageRefused):
        core.run_download(_pull_args(tmp_path))
    assert core.walk_end_reached(tmp_path) is False
    assert {r["media_id"] for r in load_catalog(tmp_path / "catalog.db")} == {"m_T1"}


# =====================================================================================
# 4. THE COMMAND -- --count end to end, and the sentence a refusal leaves
# =====================================================================================

def test_count_end_to_end_prints_its_count_and_asks_2000_a_page(
        pixai, tmp_path, monkeypatch, capsys):
    h = _history(pixai, [[_node("T1"), _node("T2", batchMediaIds=["m_T2", "b1"])],
                         [_node("T3")]])
    monkeypatch.setattr(core.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(sys, "argv", ["moonglade", "--count", "--out", str(tmp_path)])
    core.main()
    out = capsys.readouterr().out
    assert "Counting your whole library (page size 2000)" in out
    assert "Total tasks (generations) : 3" in out
    assert "Total images              : 4" in out
    assert [v["last"] for v in h.variables] == [2000, 2000]


def test_the_help_says_why_the_count_asks_2000(monkeypatch, capsys):
    monkeypatch.setenv("COLUMNS", "4000")
    monkeypatch.setattr(sys, "argv", ["moonglade", "--help"])
    with pytest.raises(SystemExit):
        core.main()
    text = " ".join(capsys.readouterr().out.split())
    assert "default 2000, because PixAI fails a 5000-row page" in text


@pytest.mark.parametrize("flag", ["--count", "--probe"])
def test_a_refusal_leaves_the_plain_sentence(pixai, tmp_path, monkeypatch, flag):
    """What the terminal and the Panel's job output show (the Panel reads the CLI's stdout and
    stderr together): the sentence, and no word of a hash to recapture."""
    pixai.fail(FEED, _refusal("Cannot query field \"taskSummaries\" on type \"User\"."))
    monkeypatch.setattr(sys, "argv", ["moonglade", flag, "--out", str(tmp_path)])
    with pytest.raises(SystemExit) as ex:
        core.main()
    assert ex.value.code == core.HISTORY_REFUSED


def test_a_count_that_meets_an_answer_with_no_page_exits_with_the_sentence(
        pixai, tmp_path, monkeypatch, capsys):
    """Page 1 answers; page 2 is {} (what the client hands back for a body that is not
    GraphQL). The count used to print page 1's tally as the whole library and exit 0."""
    _history(pixai, [], script=[_answer([_node("T1")], True, "c1"), {}])
    monkeypatch.setattr(core.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(sys, "argv", ["moonglade", "--count", "--out", str(tmp_path)])
    with pytest.raises(SystemExit) as ex:
        core.main()
    assert ex.value.code == core.HISTORY_REFUSED
    out = capsys.readouterr().out
    assert "page 1: 1 tasks so far" in out
    assert "LIBRARY TOTALS" not in out and "Total tasks" not in out


# =====================================================================================
# 5. THE RETIRED SAVED REQUEST -- nothing is left behind
# =====================================================================================

def test_the_retired_saved_request_leaves_nothing_behind():
    assert not hasattr(core, "PERSISTED_QUERY_HASH")
    assert not hasattr(core, "history_page")
    persisted = inspect.getsource(core.PixAIClient.persisted)
    assert "OPERATION_NAME" not in persisted and "PERSISTED_QUERY_HASH" not in persisted
    with pytest.raises(core.PixAIError, match="no persisted hash"):
        core.PixAIClient(object()).persisted(core.OPERATION_NAME, {})
    assert "PERSISTED_QUERY_HASH" not in (REPO / "config.example.json").read_text(
        encoding="utf-8")
    live_docs = [REPO / "README.md", REPO / "CLAUDE.md", REPO / "CONTRIBUTING.md",
                 *sorted((REPO / "wiki").glob("*.md"))]
    for doc in live_docs:
        assert "PERSISTED_QUERY_HASH" not in doc.read_text(encoding="utf-8"), doc.name
    for module in (core, g):
        assert "PERSISTED_QUERY_HASH" not in inspect.getsource(module)
