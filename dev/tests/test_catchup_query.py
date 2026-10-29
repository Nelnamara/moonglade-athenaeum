"""The Live Mirror's catch-up reads the history feed on the one road (#80, then #89).

#80 taught the catch-up to read the feed again as a full document when PixAI did not
recognize the saved request, and to count those misses. Since #89 every reader of the feed
reads the full document first and only (`core.gql`), so the catch-up does too: there is no
saved request left to miss, and a failed read is one plain "catch-up after ... failed" line
that is not coverage.

Nothing here touches the network: the feed is answered by a FakePixAI (keyed by the
document's first root field) and every collect is stubbed. No saved operation remains (#92)."""
import inspect
import logging
import time

import pytest

from moonglade import backup as core
from moonglade import gallery as mg

from tests.fake_pixai import FakePixAI, operation_name

FEED = operation_name(core._HISTORY_PAGE_DOC)
REFUSED_DOC = "Cannot query field taskSummaries on type User"


def _feed(*nodes):
    """The document's answer shape."""
    return {"user": {"id": "U1", "taskSummaries": {
        "pageInfo": {"hasNextPage": False, "hasPreviousPage": False, "endCursor": "c",
                     "startCursor": "c"},
        "edges": [{"node": n} for n in nodes]}}}


# ---- the transport: a refusal of the document is a plain error ---------------------------
class _Resp:
    status_code = 200
    content = b"{}"
    text = "{}"

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def test_gql_adhoc_raises_a_plain_error_for_a_graphql_refusal():
    """Pins what `gql` reads a refusal off: a GraphQL error answer to the full document is a
    plain PixAIError carrying PixAI's list (the named saved-request error is gone, #92)."""
    class _PostSession:
        def post(self, *a, **k):
            return _Resp({"errors": [{"message": REFUSED_DOC}]})

    with pytest.raises(core.PixAIError) as ei:
        core.gql_adhoc(_PostSession(), core._HISTORY_PAGE_DOC, {"last": 1}, retries=0)
    assert str(ei.value).startswith("GraphQL error")
    assert type(ei.value) is core.PixAIError
    assert ei.value.graphql_errors == [{"message": REFUSED_DOC}]


# ---- the sweep ---------------------------------------------------------------------------
def _sweep_app(monkeypatch, tmp_path, fake):
    """A real create_app whose sweep reads through `fake`; returns (sweep, collected). One
    finished task, absent from the catalog until the stubbed collect adds it."""
    from moonglade.gallery import create_app

    app = create_app(tmp_path)
    present = set()
    collected = []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: fake)
    monkeypatch.setattr(mg, "get_row",
                        lambda db_path, m: ({"media_id": m} if m in present else None))
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)

    def collect(s, tid, out, **k):
        collected.append(str(tid))
        present.add("M_new")
        return {"saved": 1}

    monkeypatch.setattr(core, "collect_generation", collect)
    return app.extensions["mg_watch_catchup"], collected


_TASK = {"id": "T_new", "status": "completed", "mediaId": "M_new", "batchMediaIds": None}


def _failed_lines(caplog):
    return [r.getMessage() for r in caplog.records
            if "catch-up after periodic failed" in r.getMessage()]


def test_the_catchup_reads_the_document_and_converges(monkeypatch, tmp_path, caplog):
    fake = FakePixAI(user_id="U1").on(FEED, _feed(_TASK))
    sweep, collected = _sweep_app(monkeypatch, tmp_path, fake)

    with caplog.at_level(logging.INFO):
        assert sweep("periodic") is True
        assert collected == ["T_new"]                # the missed task came in once
        assert sweep("periodic") is True
    assert collected == ["T_new"]                    # converged on ONE row, no second collect
    feed = fake.calls_for(FEED)
    assert len(feed) == 2
    assert all(c.verb == "query" and c.document == core._HISTORY_PAGE_DOC for c in feed)
    assert feed[0].variables == {"last": 30, "userId": "U1"}      # one page of recent tasks
    assert not [c for c in fake.calls if c.verb == "persisted"]   # no saved request, ever
    assert _failed_lines(caplog) == []


def test_a_refused_read_is_logged_every_time_and_is_not_coverage(monkeypatch, tmp_path,
                                                                 caplog):
    """A refusal is the plain line the catch-up has always written for a failed read, on every
    sweep it happens in (there is no miss account to latch it), and never coverage."""
    refused = core.PixAIError("GraphQL error: " + REFUSED_DOC)
    fake = FakePixAI(user_id="U1").fail(FEED, refused)
    sweep, collected = _sweep_app(monkeypatch, tmp_path, fake)

    with caplog.at_level(logging.DEBUG):
        results = [sweep("periodic") for _ in range(3)]       # never raises
    assert results == [False] * 3
    assert collected == []
    lines = _failed_lines(caplog)
    assert len(lines) == 3
    assert "HistoryPageRefused" in lines[0] and core.HISTORY_REFUSED in lines[0]
    for stale in ("Recapture", "hash", "saved history request", "Updating the app"):
        assert not any(stale in r.getMessage() for r in caplog.records), stale


def test_an_answer_with_no_page_in_it_is_a_failed_read_not_coverage(monkeypatch, tmp_path,
                                                                    caplog):
    """A body that is not GraphQL ({"message": "Forbidden"}) comes back from the ad-hoc POST as
    {}. It used to read as an empty page -- "nothing missed", and True, so a failed read
    counted as coverage. It is a failed read."""
    fake = FakePixAI(user_id="U1").on(FEED, {})
    sweep, collected = _sweep_app(monkeypatch, tmp_path, fake)
    with caplog.at_level(logging.INFO):
        assert sweep("periodic") is False
    assert collected == []
    lines = _failed_lines(caplog)
    assert len(lines) == 1 and "HistoryPageRefused" in lines[0]
    assert not any("nothing missed" in r.getMessage() for r in caplog.records)


def test_any_other_failed_read_is_logged_the_same_way(monkeypatch, tmp_path, caplog):
    fake = FakePixAI(user_id="U1").fail(FEED, core.PixAIError("HTTP 500 error"))
    sweep, _collected = _sweep_app(monkeypatch, tmp_path, fake)
    with caplog.at_level(logging.INFO):
        assert sweep("periodic") is False
        assert sweep("periodic") is False
    lines = _failed_lines(caplog)
    assert len(lines) == 2 and "HTTP 500 error" in lines[0]


def test_the_miss_account_is_gone():
    """#80's saved-request accounting goes with the saved request: nothing is left to count
    or to warn about."""
    src = inspect.getsource(mg)
    for retired in ("_note_catchup_query", "_catchup_query", "WATCH_CATCHUP_QUERY_MISSES",
                    "via_document", "saved history request", "core.history_page"):
        assert retired not in src, retired
    assert not hasattr(core, "history_page")
