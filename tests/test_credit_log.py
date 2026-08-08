"""Credit Ledger (list_credit_log / run_credit_log). The REAL "spend history" behind
Membership & Credits -> Credit log -- ad-hoc GraphQL `user(id).quotaLogs`, backward-paginated
(last/before over hasPreviousPage/startCursor) like this codebase's other history listings,
NOT the same endpoint as kaisuuken_logs or extra_package_boosts. Verified live 2026-08-02.
Pure/mocked -- no live network (conftest blocks gql_adhoc), no spend."""
from types import SimpleNamespace

import moonglade_backup as core


def _node(ref_id="r-1", amount=-2100, type_="task_cost", extra=None,
          created="2026-08-01T22:08:00Z", updated="2026-08-01T22:08:00Z"):
    return {"refId": ref_id, "userId": "u-1", "amount": amount, "type": type_,
            "extra": extra, "createdAt": created, "updatedAt": updated}


def _resp(nodes, has_previous=False, start_cursor=None):
    return {"user": {"id": "u-1", "quotaLogs": {
        "pageInfo": {"hasNextPage": False, "hasPreviousPage": has_previous,
                     "startCursor": start_cursor, "endCursor": None},
        "edges": [{"cursor": "c-{}".format(i), "node": n} for i, n in enumerate(nodes)],
    }}}


# ---- list_credit_log: ad-hoc GraphQL user(id).quotaLogs, soft-fail ----

def test_list_credit_log_normalizes_real_shape_and_uses_user_id(monkeypatch):
    monkeypatch.setattr(core, "USER_ID", "u-1")
    seen = {}

    def fake_gql(session, query, variables=None):
        seen["variables"] = variables
        return _resp([_node()])

    monkeypatch.setattr(core, "gql_adhoc", fake_gql)
    result = core.list_credit_log(object(), last=30)
    assert seen["variables"] == {"userId": "u-1", "last": 30}
    row = result["entries"][0]
    assert row["ref_id"] == "r-1" and row["amount"] == -2100
    assert row["type"] == "task_cost" and row["label"] == "Generation Task"


def test_list_credit_log_unmapped_type_falls_back_to_raw(monkeypatch):
    monkeypatch.setattr(core, "USER_ID", "u-1")
    monkeypatch.setattr(core, "gql_adhoc",
                         lambda s, q, variables=None: _resp([_node(type_="mio2_gem_exchange")]))
    row = core.list_credit_log(object())["entries"][0]
    assert row["type"] == "mio2_gem_exchange" and row["label"] == "mio2_gem_exchange"


def test_list_credit_log_passes_reason_and_before(monkeypatch):
    monkeypatch.setattr(core, "USER_ID", "u-1")
    seen = {}

    def fake_gql(session, query, variables=None):
        seen["variables"] = variables
        return _resp([])

    monkeypatch.setattr(core, "gql_adhoc", fake_gql)
    core.list_credit_log(object(), last=10, before="cursor-past", reason="task_cost")
    assert seen["variables"] == {
        "userId": "u-1", "last": 10, "before": "cursor-past", "reason": "task_cost"}


def test_list_credit_log_backward_pagination_reads_previous_and_start_cursor(monkeypatch):
    """This connection pages BACKWARD (oldest direction is 'more') -- must read
    hasPreviousPage/startCursor, not hasNextPage/endCursor (the forward-pagination fields
    kaisuuken_logs/extra_package_boosts use), matching page_variables()'s own convention."""
    monkeypatch.setattr(core, "USER_ID", "u-1")
    monkeypatch.setattr(core, "gql_adhoc", lambda s, q, variables=None: _resp(
        [_node()], has_previous=True, start_cursor="cursor-older"))
    result = core.list_credit_log(object())
    assert result["has_more"] is True and result["next_cursor"] == "cursor-older"


def test_list_credit_log_fails_soft(monkeypatch):
    def boom(*a, **k):
        raise core.PixAIError("network down")
    monkeypatch.setattr(core, "gql_adhoc", boom)
    assert core.list_credit_log(object()) == {
        "entries": [], "has_more": False, "next_cursor": None}


# ---- run_credit_log display (list_credit_log stubbed) ----

def test_run_credit_log_empty(monkeypatch, capsys):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "list_credit_log", lambda s, **k: {
        "entries": [], "has_more": False, "next_cursor": None})
    res = core.run_credit_log(SimpleNamespace(
        token=None, credit_log_count=0, credit_log_reason="", credit_log_before=""))
    assert res == {"entries": 0}
    assert "No credit log entries" in capsys.readouterr().out


def test_run_credit_log_lists_signed_amounts_and_more_hint(monkeypatch, capsys):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "list_credit_log", lambda s, **k: {
        "entries": [
            {"ref_id": "r-1", "amount": 30000, "type": "daily", "label": "Daily Claim",
             "extra": None, "created_at": "2026-08-01T10:12:00Z", "updated_at": ""},
            {"ref_id": "r-2", "amount": -2100, "type": "task_cost",
             "label": "Generation Task", "extra": None,
             "created_at": "2026-08-01T10:08:00Z", "updated_at": ""},
        ], "has_more": True, "next_cursor": "cursor-older"})
    res = core.run_credit_log(SimpleNamespace(
        token=None, credit_log_count=0, credit_log_reason="", credit_log_before=""))
    out = capsys.readouterr().out
    assert res == {"entries": 2}
    assert "+30,000" in out and "Daily Claim" in out
    assert "-2,100" in out and "Generation Task" in out
    assert "cursor-older" in out                    # tells the caller how to page further
