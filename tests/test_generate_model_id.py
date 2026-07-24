"""Regression for the stale/raced model-version submit bug, PLUS (picker-parity-round2,
problem 4) /api/generate honoring a deliberately-CHOSEN non-latest version.

The Generate drawer resolves a picked model_id -> version_id via an async fetch that was
unguarded, so a fast model switch could leave selected.version_id pointing at the WRONG
(previous) model's version. That got submitted verbatim, so the gen landed on PixAI as
'Unknown model' and never showed on the feed. Original fix: /api/generate re-resolved the
CURRENT (latest) version server-side from the base model_id and ignored the client's cached
version_id outright. Problem 4 sharpened that: the owner wanted a real version PICKER
(PixAI's own model/LoRA cards have one), so a client version_id is now honored IF it names
one of model_id's own real versions (validated server-side against core.list_model_versions
-- never trusted blind), and falls back to the newest exactly like before otherwise. No
network, no spend (everything mocked)."""
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


def test_generate_honors_an_explicitly_chosen_non_latest_version(tmp_path, monkeypatch):
    """Problem 4: the owner picked an OLDER release via the new version selector -- that
    real choice must actually be submitted, not silently overwritten back to latest."""
    LATEST, CHOSEN = "V-LATEST", "V-CHOSEN"
    monkeypatch.setattr(core, "_rest_get", lambda s, path, **k: [
        {"id": LATEST, "modelType": "SDXL_MODEL"},
        {"id": CHOSEN, "modelType": "SDXL_MODEL"},
    ])
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: None)
    seen = {}
    monkeypatch.setattr(core, "_gen_parameters",
                        lambda args: seen.update(model=args.model) or {"modelId": args.model})
    monkeypatch.setattr(core, "submit_generation",
                        lambda s, params: seen.update(submitted=params) or "task123")

    client = login_client(tmp_path)
    r = client.post("/api/generate", json={"model_id": "M1", "version_id": CHOSEN, "prompt": "a cat"})
    assert r.status_code == 200, r.data
    assert seen["model"] == CHOSEN          # the deliberately-picked release, not the latest
    assert seen["submitted"]["modelId"] == CHOSEN


def test_generate_still_falls_back_to_latest_when_client_version_belongs_elsewhere(tmp_path, monkeypatch):
    """The original anti-race guarantee must survive problem 4's change: a version_id that
    does NOT belong to model_id's own real version list (stale from a fast model switch, or
    just wrong) is NEVER trusted -- same outcome as before this feature existed."""
    LATEST = "V-LATEST"
    FOREIGN = "V-FROM-A-DIFFERENT-MODEL"
    monkeypatch.setattr(core, "_rest_get", lambda s, path, **k: [{"id": LATEST, "modelType": "SDXL_MODEL"}])
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: None)
    seen = {}
    monkeypatch.setattr(core, "_gen_parameters",
                        lambda args: seen.update(model=args.model) or {"modelId": args.model})
    monkeypatch.setattr(core, "submit_generation", lambda s, params: "task123")

    client = login_client(tmp_path)
    r = client.post("/api/generate", json={"model_id": "M1", "version_id": FOREIGN, "prompt": "a cat"})
    assert r.status_code == 200, r.data
    assert seen["model"] == LATEST
    assert seen["model"] != FOREIGN


def test_generate_falls_back_to_latest_when_model_has_no_versions_at_all(tmp_path, monkeypatch):
    """model_id resolves to nothing (deleted/private model) -- must not crash, and must not
    invent a version_id; args.model is left as whatever the client originally sent (matches
    the pre-problem-4 fallback, which also left args.model untouched when resolution failed)."""
    monkeypatch.setattr(core, "_rest_get", lambda s, path, **k: [])
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: None)
    seen = {}
    monkeypatch.setattr(core, "_gen_parameters", lambda args: seen.update(model=args.model) or {})
    monkeypatch.setattr(core, "submit_generation", lambda s, params: "task123")

    client = login_client(tmp_path)
    r = client.post("/api/generate", json={"model_id": "M1", "version_id": "V-WHATEVER", "prompt": "x"})
    assert r.status_code == 200, r.data
    assert seen["model"] == "V-WHATEVER"   # untouched, exactly like the no-model_id path


def test_model_version_all_param_lists_every_version(tmp_path, monkeypatch):
    """/api/model-version?all=1 (problem 4): the new list-mode, additive to the existing
    single-resolved-version default (unchanged, see the sibling tests above)."""
    monkeypatch.setattr(core, "_rest_get", lambda s, path, **k: [
        {"id": "V2", "modelType": "SDXL_MODEL", "createdAt": "2026-07-01T00:00:00Z"},
        {"id": "V1", "modelType": "SDXL_MODEL", "createdAt": ""},
    ])
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    client = login_client(tmp_path)
    r = client.get("/api/model-version?model_id=M1&all=1")
    assert r.status_code == 200, r.data
    d = r.get_json()
    assert "versions" in d and "version_id" not in d     # list shape, not the single shape
    assert [v["version_id"] for v in d["versions"]] == ["V2", "V1"]
    assert d["versions"][0]["is_latest"] is True and d["versions"][0]["label"].startswith("Latest")

    # default (no ?all) is UNCHANGED -- the single resolved-latest shape every existing
    # caller (bindPicker, onBasePick, the LoRA multi-picker's own resolve) already expects.
    r2 = client.get("/api/model-version?model_id=M1")
    assert r2.status_code == 200, r2.data
    d2 = r2.get_json()
    assert d2["version_id"] == "V2" and "versions" not in d2
