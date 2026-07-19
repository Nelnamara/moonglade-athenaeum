"""Regression for the stale/raced model-version submit bug.

The Generate drawer resolves a picked model_id -> version_id via an async fetch that was
unguarded, so a fast model switch could leave selected.version_id pointing at the WRONG
(previous) model's version. That got submitted verbatim, so the gen landed on PixAI as
'Unknown model' and never showed on the feed. Fix: /api/generate re-resolves the CURRENT
version server-side from the base model_id and ignores the client's cached version_id.
These lock that in. No network, no spend (everything mocked)."""
import pixai_gallery_backup as core

from tests.conftest import login_client


def test_generate_reresolves_current_version_over_stale_client_version(tmp_path, monkeypatch):
    RESOLVED = "1983308862240288769"   # the model's real current version
    STALE = "1861558740588989558"      # the raced version_id the drawer had cached

    # resolve_version_meta(model_id) -> RESOLVED, via its single /versions REST call
    monkeypatch.setattr(core, "_rest_get", lambda s, path, **k: [{"id": RESOLVED, "modelId": "M1"}])
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: None)
    seen = {}
    monkeypatch.setattr(core, "_gen_parameters",
                        lambda args: seen.update(model=args.model) or {"modelId": args.model})
    monkeypatch.setattr(core, "submit_generation",
                        lambda s, params: seen.update(submitted=params) or "task123")

    client = login_client(tmp_path)
    r = client.post("/api/generate", json={"model_id": "M1", "version_id": STALE, "prompt": "a cat"})
    assert r.status_code == 200, r.data
    assert r.get_json().get("task_id") == "task123"
    assert seen["model"] == RESOLVED        # submitted the re-resolved current version...
    assert seen["model"] != STALE           # ...NOT the stale client version_id
    assert seen["submitted"]["modelId"] == RESOLVED


def test_generate_without_model_id_uses_client_version(tmp_path, monkeypatch):
    """Backward compat: with no model_id sent, the client's version_id is used as-is."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: None)
    seen = {}
    monkeypatch.setattr(core, "_gen_parameters", lambda args: seen.update(model=args.model) or {})
    monkeypatch.setattr(core, "submit_generation", lambda s, params: "t")

    client = login_client(tmp_path)
    r = client.post("/api/generate", json={"version_id": "V-DIRECT", "prompt": "x"})
    assert r.status_code == 200, r.data
    assert seen["model"] == "V-DIRECT"
