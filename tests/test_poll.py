"""The shared task-poll helper (_poll_task_status) used by generate / video / edit.
Mocked -- no live network, no sleeping (completed/failed return or raise before any
sleep; timeout=0 never enters the loop)."""
import pytest

import pixai_gallery_backup as core


def test_poll_returns_paid_credit_and_prints_cost(monkeypatch, capsys):
    monkeypatch.setattr(core, "gql_adhoc",
                        lambda *a, **k: {"task": {"status": "completed", "paidCredit": 27500}})
    paid = core._poll_task_status(object(), "t1", 300, label="video", fail_noun="video generation")
    assert paid == 27500
    assert "actual cost: 27,500 credits" in capsys.readouterr().out


def test_poll_completed_without_cost_returns_none(monkeypatch, capsys):
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: {"task": {"status": "succeeded"}})
    paid = core._poll_task_status(object(), "t2", 300, label="generate", fail_noun="generation")
    assert paid is None
    assert "actual cost" not in capsys.readouterr().out


def test_poll_raises_on_failure_with_noun(monkeypatch):
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: {"task": {"status": "failed"}})
    with pytest.raises(core.PixAIError) as e:
        core._poll_task_status(object(), "t3", 300, label="edit", fail_noun="edit")
    assert "edit ended with status: failed" in str(e.value)


def test_poll_raises_on_timeout(monkeypatch):
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: {"task": {"status": "running"}})
    with pytest.raises(core.PixAIError) as e:
        core._poll_task_status(object(), "t4", 0, label="generate", fail_noun="generation")
    assert "timed out" in str(e.value) and "t4" in str(e.value)
