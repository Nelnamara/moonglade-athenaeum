"""#80: the Live Mirror's catch-up read survives a saved history request PixAI does not
recognize, and says so once in plain words when PixAI stops recognizing it altogether.

Nothing here touches the network: the feed read (`core.gql`) and the full-document read
(`core.gql_adhoc`) are stubbed, and every collect is stubbed."""
import logging
import time

import pytest

from moonglade import backup as core

NOT_RECOGNIZED = "Persisted-query hash not recognized. Recapture the hash (see RECAPTURE)."
REFUSED_DOC = "Cannot query field taskSummaries on type User"


class _Sess:
    headers = {"Authorization": "Bearer sk-x"}


def _feed(*nodes):
    """The feed answer shape both roads return."""
    return {"user": {"id": "U1", "taskSummaries": {
        "pageInfo": {"hasNextPage": False, "endCursor": "c", "startCursor": "c"},
        "edges": [{"node": n} for n in nodes]}}}


# ---- the transport: the refusal is a named error -----------------------------------------
class _Resp:
    status_code = 200
    content = b"{}"
    text = "{}"

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


class _GetSession:
    def __init__(self, body):
        self.body = body
        self.calls = 0

    def get(self, *a, **k):
        self.calls += 1
        return _Resp(self.body)


def test_persisted_not_found_is_a_named_pixai_error():
    sess = _GetSession({"errors": [{"message": "PersistedQueryNotFound",
                                    "extensions": {"code": "PERSISTED_QUERY_NOT_FOUND"}}]})
    with pytest.raises(core.PersistedQueryNotRecognized) as ei:
        core.gql(sess, {"last": 1}, retries=0)
    assert isinstance(ei.value, core.PixAIError)                # every old catch site holds
    assert "hash not recognized" in str(ei.value)


def test_another_graphql_error_is_not_the_named_error():
    sess = _GetSession({"errors": [{"message": "Something else"}]})
    with pytest.raises(core.PixAIError) as ei:
        core.gql(sess, {"last": 1}, retries=0)
    assert not isinstance(ei.value, core.PersistedQueryNotRecognized)


# ---- history_page ------------------------------------------------------------------------
def test_history_page_reads_the_saved_request_first(monkeypatch):
    page = _feed({"id": "T1"})
    monkeypatch.setattr(core, "gql", lambda *a, **k: page)
    monkeypatch.setattr(core, "gql_adhoc",
                        lambda *a, **k: pytest.fail("the full document is for a refusal only"))
    data, via_document = core.history_page(_Sess(), {"last": 30, "userId": "U1"})
    assert data is page and via_document is False


def test_history_page_retries_once_through_the_full_document(monkeypatch):
    page = _feed({"id": "T1"})
    calls = []

    def refuse(*a, **k):
        calls.append("persisted")
        raise core.PersistedQueryNotRecognized(NOT_RECOGNIZED)

    def document(session, query, variables=None, **k):
        calls.append(("document", query, variables))
        return page

    monkeypatch.setattr(core, "gql", refuse)
    monkeypatch.setattr(core, "gql_adhoc", document)
    variables = {"last": 30, "userId": "U1", "before": "cur"}
    data, via_document = core.history_page(_Sess(), variables)
    assert data is page and via_document is True
    assert calls == ["persisted", ("document", core._HISTORY_PAGE_DOC, variables)]
    # the document is a query and names the three variables the feed carries
    assert core._is_mutation_document(core._HISTORY_PAGE_DOC) is False
    for name in ("$userId", "$last", "$before"):
        assert name in core._HISTORY_PAGE_DOC
    # find_connection reads either road's page
    assert len(core.find_connection(data)["edges"]) == 1


def test_history_page_does_not_retry_any_other_failure(monkeypatch):
    def boom(*a, **k):
        raise core.PixAIError("HTTP 500 error")

    monkeypatch.setattr(core, "gql", boom)
    monkeypatch.setattr(core, "gql_adhoc",
                        lambda *a, **k: pytest.fail("only a refusal earns the second road"))
    with pytest.raises(core.PixAIError, match="HTTP 500"):
        core.history_page(_Sess(), {})


def test_history_page_names_a_refusal_of_both_roads(monkeypatch):
    """PixAI refusing the full document too is HistoryPageRefused, chained from what
    gql_adhoc really raises (a plain PixAIError "GraphQL error: ...")."""
    real = core.PixAIError("GraphQL error: " + REFUSED_DOC)
    monkeypatch.setattr(core, "gql", lambda *a, **k: (_ for _ in ()).throw(
        core.PersistedQueryNotRecognized(NOT_RECOGNIZED)))
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: (_ for _ in ()).throw(real))
    with pytest.raises(core.HistoryPageRefused) as ei:
        core.history_page(_Sess(), {})
    assert isinstance(ei.value, core.PixAIError)
    assert ei.value.__cause__ is real
    assert REFUSED_DOC in str(ei.value)
    assert not isinstance(ei.value, core.PersistedQueryNotRecognized)


def test_history_page_leaves_a_non_refusal_retry_failure_alone(monkeypatch):
    """A 401 or a network failure on the retry is not "PixAI said no twice": it raises as it
    would from gql_adhoc, so the sweep reports it every time."""
    monkeypatch.setattr(core, "gql", lambda *a, **k: (_ for _ in ()).throw(
        core.PersistedQueryNotRecognized(NOT_RECOGNIZED)))
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: (_ for _ in ()).throw(
        core.PixAIError("401 Unauthorized -- API key missing/expired.")))
    with pytest.raises(core.PixAIError, match="401") as ei:
        core.history_page(_Sess(), {})
    assert not isinstance(ei.value, core.HistoryPageRefused)


def test_gql_adhoc_raises_a_plain_error_for_a_graphql_refusal():
    """Pins what the stubs below imitate: a GraphQL error answer to the full document is a
    plain PixAIError, never the named persisted-query error."""
    class _PostSession:
        def post(self, *a, **k):
            return _Resp({"errors": [{"message": REFUSED_DOC}]})

    with pytest.raises(core.PixAIError) as ei:
        core.gql_adhoc(_PostSession(), core._HISTORY_PAGE_DOC, {"last": 1}, retries=0)
    assert str(ei.value).startswith("GraphQL error")
    assert type(ei.value) is core.PixAIError


# ---- the sweep ---------------------------------------------------------------------------
def _sweep_app(monkeypatch, tmp_path, *, gql, adhoc):
    """A real create_app whose sweep reads through the given stubs; returns (sweep, collected,
    present). One finished task, absent from the catalog until the stubbed collect adds it."""
    from moonglade import gallery as mg
    from moonglade.gallery import create_app

    app = create_app(tmp_path)
    present = set()
    collected = []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: _Sess())
    monkeypatch.setattr(core, "page_variables", lambda *a, **k: {"last": 30, "userId": "U1"})
    monkeypatch.setattr(core, "gql", gql)
    monkeypatch.setattr(core, "gql_adhoc", adhoc)
    monkeypatch.setattr(mg, "get_row",
                        lambda db_path, m: ({"media_id": m} if m in present else None))
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)

    def collect(s, tid, out, **k):
        collected.append(str(tid))
        present.add("M_new")
        return {"saved": 1}

    monkeypatch.setattr(core, "collect_generation", collect)
    return app.extensions["mg_watch_catchup"], collected, present


_TASK = {"id": "T_new", "status": "completed", "mediaId": "M_new", "batchMediaIds": None}


def test_catchup_converges_when_the_saved_request_is_refused_once(monkeypatch, tmp_path,
                                                                   caplog):
    state = {"n": 0}

    def gql(*a, **k):
        state["n"] += 1
        if state["n"] == 1:
            raise core.PersistedQueryNotRecognized(NOT_RECOGNIZED)
        return _feed(_TASK)

    sweep, collected, _present = _sweep_app(
        monkeypatch, tmp_path, gql=gql, adhoc=lambda *a, **k: _feed(_TASK))

    with caplog.at_level(logging.INFO):
        assert sweep("periodic") is True            # the refusal did not fail the sweep
        assert collected == ["T_new"]               # ...and the missed task came in once
        assert sweep("periodic") is True            # the next sweep reads the saved request
    assert collected == ["T_new"]                   # converged on ONE row, no second collect
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert not any("not recognize" in w or "Persisted-query" in w for w in warnings)
    assert not any("catch-up after periodic failed" in w for w in warnings)


def test_catchup_reports_a_request_pixai_no_longer_recognizes_once(monkeypatch, tmp_path,
                                                                    caplog):
    def gql(*a, **k):
        raise core.PersistedQueryNotRecognized(NOT_RECOGNIZED)

    sweep, collected, _present = _sweep_app(
        monkeypatch, tmp_path, gql=gql, adhoc=lambda *a, **k: _feed(_TASK))

    with caplog.at_level(logging.INFO):
        results = [sweep("periodic") for _ in range(8)]
    assert results == [True] * 8                    # every sweep still reads, via the document
    assert collected == ["T_new"]
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"
                and "saved history request" in r.getMessage()]
    assert len(warnings) == 1                       # said once, not on every sweep
    assert "Recapture" not in warnings[0] and "hash" not in warnings[0].lower()
    assert "nothing is missed" in warnings[0]

    # ...and when the saved request is recognized again it says so, and re-arms
    monkeypatch.setattr(core, "gql", lambda *a, **k: _feed())
    with caplog.at_level(logging.INFO):
        assert sweep("periodic") is True
    assert any("recognizes the app's saved history request again" in r.getMessage()
               for r in caplog.records)


def test_catchup_logs_a_total_refusal_once_and_carries_on(monkeypatch, tmp_path, caplog):
    def refuse(*a, **k):
        raise core.PersistedQueryNotRecognized(NOT_RECOGNIZED)

    def refuse_document(*a, **k):
        # what gql_adhoc really raises when PixAI answers the full document with an error
        raise core.PixAIError("GraphQL error: " + REFUSED_DOC)

    sweep, collected, _present = _sweep_app(monkeypatch, tmp_path, gql=refuse,
                                            adhoc=refuse_document)

    with caplog.at_level(logging.DEBUG):
        results = [sweep("periodic") for _ in range(6)]   # never raises
    assert results == [False] * 6                   # a failed read is not coverage
    assert collected == []
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "cannot read your recent generations" in warnings[0]
    assert "Persisted-query" not in warnings[0] and "Recapture" not in warnings[0]

    # a different failure is still reported every time it happens (nothing else is silenced)
    def other(*a, **k):
        raise core.PixAIError("HTTP 500 error")

    monkeypatch.setattr(core, "gql", other)
    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert sweep("periodic") is False
        assert sweep("periodic") is False
    assert len([r for r in caplog.records if "catch-up after periodic failed" in r.getMessage()]) == 2


def test_catchup_scattered_misses_never_add_up_to_a_warning(monkeypatch, tmp_path, caplog):
    """A refusal now and then, a good read between each, is the 2-in-100 pattern the logs show.
    Only misses IN A ROW count: scattered ones must not warn, and a warned run re-arms."""
    state = {"n": 0, "refuse": True}

    def gql(*a, **k):
        state["n"] += 1
        if state["refuse"] and state["n"] % 2 == 1:     # miss, ok, miss, ok, ...
            raise core.PersistedQueryNotRecognized(NOT_RECOGNIZED)
        return _feed()

    sweep, _collected, _present = _sweep_app(
        monkeypatch, tmp_path, gql=gql, adhoc=lambda *a, **k: _feed())

    def warned():
        return [r for r in caplog.records if r.levelname == "WARNING"
                and "saved history request" in r.getMessage()]

    with caplog.at_level(logging.INFO):
        assert all(sweep("periodic") for _ in range(12))    # six misses, never two in a row
        assert warned() == []
        state["refuse"] = False
        assert sweep("periodic") is True                    # a clean read between the runs
        monkeypatch.setattr(core, "gql", lambda *a, **k: (_ for _ in ()).throw(
            core.PersistedQueryNotRecognized(NOT_RECOGNIZED)))
        assert all(sweep("periodic") for _ in range(3))     # three in a row: the one warning
        assert len(warned()) == 1
        monkeypatch.setattr(core, "gql", lambda *a, **k: _feed())
        assert sweep("periodic") is True                    # recognized again: re-armed
        monkeypatch.setattr(core, "gql", lambda *a, **k: (_ for _ in ()).throw(
            core.PersistedQueryNotRecognized(NOT_RECOGNIZED)))
        assert all(sweep("periodic") for _ in range(3))
        assert len(warned()) == 2
