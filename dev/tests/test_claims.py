"""Claimable rewards (/v2/claim): --claims lists (read-only), --claim is gated behind
--confirm and never fires on unclaimable rewards. Mocked -- conftest blocks live /v2."""
from types import SimpleNamespace

from moonglade import backup as core
from moonglade import account_api as account_api_mod

_REWARDS = [
    {"id": "pixai-daily-credits", "amount": 30000, "canClaim": False,
     "nextClaimableTime": 1783123200000},
    {"id": "agent-daily-stamina", "amount": 20, "canClaim": True, "nextClaimableTime": None},
]


def test_list_claims(monkeypatch):
    monkeypatch.setattr(core, "_rest_get", lambda s, path, **k: _REWARDS)
    assert account_api_mod.list_claims(object()) == _REWARDS


def test_list_claims_fails_soft(monkeypatch):
    monkeypatch.setattr(core, "_rest_get",
                        lambda *a, **k: (_ for _ in ()).throw(core.PixAIError("down")))
    assert account_api_mod.list_claims(object()) == []


def test_claim_reward_posts_to_id(monkeypatch):
    seen = {}
    def fake_post(s, path, body, **k):
        seen["path"] = path
        return {"id": "x", "canClaim": False}
    monkeypatch.setattr(core, "_rest_post", fake_post)
    account_api_mod.claim_reward(object(), "agent-daily-stamina")
    assert seen["path"] == "/claim/agent-daily-stamina"


def _args(**kw):
    base = dict(token=None, claims=False, claim="", confirm=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_run_claims_list_readonly(monkeypatch, capsys, pixai):
    monkeypatch.setattr(account_api_mod, "list_claims", lambda s: _REWARDS)
    res = account_api_mod.run_claims(_args(claims=True))
    out = capsys.readouterr().out
    assert res == {"rewards": 2, "ready": 1}
    assert "agent-daily-stamina" in out and "READY" in out


def test_run_claims_previews_without_confirm(monkeypatch, capsys, pixai):
    monkeypatch.setattr(account_api_mod, "list_claims", lambda s: _REWARDS)
    monkeypatch.setattr(account_api_mod, "claim_reward",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no claim in preview")))
    res = account_api_mod.run_claims(_args(claim="agent-daily-stamina"))
    assert res == {"claimed": 0, "preview": True}
    assert "Would claim" in capsys.readouterr().out


def test_run_claims_with_confirm(monkeypatch, pixai):
    monkeypatch.setattr(account_api_mod, "list_claims", lambda s: _REWARDS)
    calls = []
    monkeypatch.setattr(account_api_mod, "claim_reward", lambda s, cid: calls.append(cid) or {"id": cid})
    res = account_api_mod.run_claims(_args(claim="agent-daily-stamina", confirm=True))
    assert res == {"claimed": 1} and calls == ["agent-daily-stamina"]


def test_run_claims_unclaimable_guard(monkeypatch, capsys, pixai):
    monkeypatch.setattr(account_api_mod, "list_claims", lambda s: _REWARDS)
    monkeypatch.setattr(account_api_mod, "claim_reward",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not claim")))
    res = account_api_mod.run_claims(_args(claim="pixai-daily-credits", confirm=True))
    assert res == {"claimed": 0}
    assert "not claimable yet" in capsys.readouterr().out


def test_run_claims_all_claims_only_ready(monkeypatch, pixai):
    monkeypatch.setattr(account_api_mod, "list_claims", lambda s: _REWARDS)
    calls = []
    monkeypatch.setattr(account_api_mod, "claim_reward", lambda s, cid: calls.append(cid) or {})
    res = account_api_mod.run_claims(_args(claim="all", confirm=True))
    assert calls == ["agent-daily-stamina"]   # skips the not-yet-claimable daily credits
    assert res == {"claimed": 1}
