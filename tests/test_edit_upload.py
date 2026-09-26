"""Media upload (uploadMedia 3-step S3 handshake) + instruct editing
(createGenerationTask `chat` block). Pinned to the REAL captured shapes (2026-07-01).
Pure/mocked -- no live network, no credits."""
from types import SimpleNamespace

import pytest

import moonglade_backup as core


# ---- build_chat_edit_parameters (pinned to the captured Edit-Pro submit) ----

def test_build_chat_edit_parameters_matches_real_submit():
    p = core.build_chat_edit_parameters(
        "Change it to nighttime moonlight", ["738939216332293270"],
        model_id="2006468692917575683",
        resolution="1K", aspect_ratio="3:4", quality="medium")
    assert p == {"chat": {
        "prompts": "Change it to nighttime moonlight",
        "mediaId": "738939216332293270",
        "mediaIds": ["738939216332293270"],
        "modelId": "2006468692917575683",
        "modelConfig": {"resolution": "1K", "aspectRatio": "3:4", "quality": "medium"},
    }}
    # NEVER attach a free-card id by default (spend stays credit-gated + explicit)
    assert "kaisuukenId" not in p


def test_build_chat_edit_multi_reference():
    p = core.build_chat_edit_parameters("blend", ["10", "20", "30"])
    chat = p["chat"]
    assert chat["mediaId"] == "10"                 # first is the primary
    assert chat["mediaIds"] == ["10", "20", "30"]  # array => multi-image reference
    assert chat["modelId"] == core.EDIT_PRO_MODEL_ID


def test_build_chat_edit_requires_a_source():
    with pytest.raises(core.PixAIError):
        core.build_chat_edit_parameters("x", [])


# ---- _is_local_source: file => upload; numeric media_id => passthrough ----

def test_is_local_source_distinguishes_file_from_media_id(tmp_path):
    f = tmp_path / "pic.png"
    f.write_bytes(b"\x89PNG\r\n")
    assert core._is_local_source(str(f)) is True
    assert core._is_local_source("738939216332293270") is False
    assert core._is_local_source("") is False


# ---- upload_media: the 3-step S3 handshake ----

def test_upload_media_three_step_flow(tmp_path, monkeypatch):
    f = tmp_path / "pic.png"
    f.write_bytes(b"PNGDATA")

    calls = []

    def fake_gql(session, query, variables=None, retries=3):
        calls.append(variables["input"])
        if "externalId" not in variables["input"]:
            # phase 1: hand back a presigned target
            return {"uploadMedia": {"uploadUrl": "https://s3.example/put",
                                    "externalId": "uuid-1"}}
        # phase 3: register -> media id
        return {"uploadMedia": {"mediaId": "999", "media": {"id": "999"}}}

    put_calls = []

    def fake_put(url, data=None, headers=None, timeout=None):
        put_calls.append((url, data, headers))
        return SimpleNamespace(status_code=200, text="")

    monkeypatch.setattr(core.PixAIClient, "_graphql_post", fake_gql)
    monkeypatch.setattr(core.requests, "put", fake_put)

    mid = core.upload_media(object(), str(f))

    assert mid == "999"
    # phase 1 has no externalId; phase 3 carries the one from phase 1
    assert calls[0] == {"type": "IMAGE", "provider": "S3"}
    assert calls[1] == {"type": "IMAGE", "provider": "S3", "externalId": "uuid-1"}
    # the raw bytes were PUT to the presigned url (not through our API session)
    assert put_calls and put_calls[0][0] == "https://s3.example/put"
    assert put_calls[0][1] == b"PNGDATA"


def test_upload_media_missing_file(tmp_path):
    with pytest.raises(core.PixAIError):
        core.upload_media(object(), str(tmp_path / "nope.png"))


# ---- run_edit_image guards ----

def _edit_args(tmp_path, **kw):
    base = dict(out=str(tmp_path), token=None, edit_src=["100"], params_json="",
                prompt="make it night", edit_model="", edit_resolution="1K",
                edit_aspect="3:4", edit_quality="medium", confirm=False, task_id="",
                poll_timeout=300, name_length=60, name_sep="_")
    base.update(kw)
    return SimpleNamespace(**base)


def test_edit_previews_without_confirm(tmp_path, monkeypatch):
    # No --confirm => preview only: no upload, no network, spends nothing.
    def boom(*a, **k):
        raise AssertionError("network/upload must not run in preview")
    monkeypatch.setattr(core, "gql_adhoc", boom)
    monkeypatch.setattr(core, "upload_media", boom)
    res = core.run_edit_image(_edit_args(tmp_path))
    assert res == {"submitted": False}


def test_edit_preview_shows_local_files_without_uploading(tmp_path, monkeypatch, capsys):
    f = tmp_path / "pic.png"
    f.write_bytes(b"x")
    monkeypatch.setattr(core, "upload_media",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no upload in preview")))
    core.run_edit_image(_edit_args(tmp_path, edit_src=[str(f)]))
    out = capsys.readouterr().out
    assert "<upload:" in out and "PREVIEW" in out


def test_edit_requires_a_source(tmp_path):
    with pytest.raises(core.PixAIError):
        core.run_edit_image(_edit_args(tmp_path, edit_src=[], params_json="", task_id=""))


def test_edit_config_from_args_clamps_to_model_caps(tmp_path):
    """The CLI's own --edit-resolution/--edit-quality DEFAULTS (1K/medium) are exactly
    what used to reach the server unclamped -- a real model like reference-pro (no
    quality knob at all, 2K/4K only) rejects that combo. The web /api/edit path has
    run this same guard (clamp_edit_config) since the preset-mismatch bug; the CLI
    never did. Same expected values as test_clamp_edit_config_snaps_to_model_caps.

    Bite: remove the clamp_edit_config call from _edit_config_from_args and this
    fails -- cfg comes back with the raw, unclamped 1K/medium instead."""
    args = _edit_args(tmp_path, edit_model="1948514378441961474",
                      edit_resolution="1K", edit_aspect="21:9", edit_quality="medium")
    cfg = core._edit_config_from_args(args)
    assert cfg["resolution"] == "2K"
    assert cfg["quality"] == ""
    assert cfg["aspect_ratio"] == "21:9"


def test_edit_preview_shows_the_clamped_config_not_the_raw_defaults(tmp_path, capsys):
    """End-to-end: --edit-image's own preview output (what a real --confirm run would
    actually submit) reflects the clamped values, not the CLI's raw defaults."""
    args = _edit_args(tmp_path, edit_model="1948514378441961474",
                      edit_resolution="1K", edit_aspect="21:9", edit_quality="medium")
    core.run_edit_image(args)
    out = capsys.readouterr().out
    assert '"resolution": "2K"' in out
    assert '"quality"' not in out   # reference-pro exposes no quality knob at all


# ---- Auto aspect and the per-model defaults (SCOPE_2026-09-26 E1/E2) ----

REF_PRO = "1948514378441961474"


def test_auto_aspect_sends_no_aspect_ratio():
    """Reference Pro publishes no default aspect, so PixAI's own Edit sends NO aspectRatio
    (the owner's two Reference Pro edits on the wire: modelConfig {resolution: "2K"}, nothing
    else). "auto" is that choice; it must leave the key out entirely, never send "auto"."""
    p = core.build_chat_edit_parameters("x", ["10"], model_id=REF_PRO, resolution="2K",
                                        aspect_ratio="auto", quality="")
    assert p["chat"]["modelConfig"] == {"resolution": "2K"}


def test_an_unset_aspect_takes_the_models_own_default():
    """No aspect picked -> the model's table default, not a fixed 3:4: Reference Pro goes
    out as Auto (no aspectRatio), Edit Pro as 3:5. A model the table does not know keeps
    the pre-table 3:4 (its behaviour without one is unobserved)."""
    ref = core.build_chat_edit_parameters("x", ["10"], model_id=REF_PRO, resolution="2K",
                                          quality="")
    assert "aspectRatio" not in ref["chat"]["modelConfig"]
    ep = core.build_chat_edit_parameters("x", ["10"])
    assert ep["chat"]["modelConfig"]["aspectRatio"] == "3:5"
    other = core.build_chat_edit_parameters("x", ["10"], model_id="999")
    assert other["chat"]["modelConfig"]["aspectRatio"] == "3:4"


def test_clamp_keeps_auto_only_where_the_model_offers_it():
    assert core.clamp_edit_config(REF_PRO, "2K", "", "auto") == ("2K", "", "auto")
    # Edit Pro publishes a default, so Auto is not one of its values: it snaps to 3:5,
    # the same "leaving Auto takes the model's default" rule PixAI's own control follows.
    assert core.clamp_edit_config(core.EDIT_PRO_MODEL_ID, "1K", "medium", "auto") == \
        ("1K", "medium", "3:5")
    for a in ("3:5", "5:3"):              # Edit Pro's two new ratios are legal now
        assert core.clamp_edit_config(core.EDIT_PRO_MODEL_ID, "1K", "medium", a)[2] == a


def test_cli_with_no_edit_aspect_takes_the_models_default(tmp_path):
    """--edit-aspect defaults to "" now, so the chosen model decides."""
    cfg = core._edit_config_from_args(_edit_args(tmp_path, edit_model=REF_PRO, edit_aspect=""))
    assert cfg["aspect_ratio"] == "auto"
    cfg = core._edit_config_from_args(_edit_args(tmp_path, edit_model="", edit_aspect=""))
    assert cfg["aspect_ratio"] == "3:5"
    import inspect
    assert 'dest="edit_aspect", default=""' in inspect.getsource(core.main)


def test_web_payload_with_no_aspect_takes_the_models_default():
    rs = core.RequestResolver()
    ref = core._edit_parameters_from_payload(
        {"source": "55", "instruction": "x", "edit_model": "reference-pro"}, "", rs)
    assert ref["chat"]["modelConfig"] == {"resolution": "2K"}
    ep = core._edit_parameters_from_payload(
        {"source": "55", "instruction": "x", "edit_model": "edit-pro"}, "", rs)
    assert ep["chat"]["modelConfig"]["aspectRatio"] == "3:5"


def test_the_priced_auto_edit_is_the_submitted_one(tmp_path, monkeypatch):
    """The badge's /api/price and the /api/edit spend must build the SAME chat block for an
    Auto edit -- no aspectRatio on either, nothing else different (the owner's two wire edits
    paid the 2K price, 8,000, with no aspectRatio)."""
    from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog
    from tests.conftest import login_test_client
    save_catalog(tmp_path / "catalog.db", [dict({f: "" for f in CATALOG_FIELDS},
                                                media_id="1", filename="a_1.png")])
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "price_task", lambda s, params: seen.update(priced=params) or 8000)
    monkeypatch.setattr(core, "match_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(core, "submit",
                        lambda s, req, **k: seen.update(sent=req.parameters) or {"task_id": "t1"})
    cli = login_test_client(create_app(tmp_path))
    body = {"mode": "edit", "edit_model": "reference-pro", "source": "55",
            "instruction": "make it night", "resolution": "2K", "quality": "",
            "aspect": "auto"}
    cli.post("/api/price", json=body)
    assert cli.post("/api/edit", json=body).get_json().get("task_id") == "t1"
    assert seen["priced"]["chat"] == seen["sent"]["chat"]
    assert "aspectRatio" not in seen["sent"]["chat"]["modelConfig"]


def _js_edit_caps():
    """editCore.js's EDIT_CAPS, read off the source text: {key: (aspects, default)}."""
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "gallery" / "src" / "gen" / "editCore.js"
           ).read_text(encoding="utf-8").replace("\r\n", "\n")
    consts = dict(re.findall(r'export const (\w+) = "([^"]*)";', src))

    def _val(tok):
        tok = tok.strip()
        return tok.strip('"') if tok.startswith('"') else consts[tok]   # e.g. EDIT_ASPECT_AUTO
    body = src[src.index("export const EDIT_CAPS = {"):]
    body = body[:body.index("\n};")]
    out = {}
    for key, block in re.findall(r'"([\w-]+)": \{(.*?)\n  \}', body, re.S):
        aspects = [_val(t) for t in
                   re.search(r"aspects: \[([^\]]*)\]", block).group(1).split(",") if t.strip()]
        d = re.search(r"def: \{([^}]*)\}", block).group(1)
        out[key] = (aspects, {k: _val(v) for k, v in re.findall(r"(\w+): ([^,]+)", d)})
    return out


def test_edit_caps_and_edit_models_agree():
    """The two hand-kept tables (core.EDIT_MODELS and editCore.js EDIT_CAPS) must list the
    same aspects, in the same order, and the same defaults -- otherwise the drawer offers or
    pre-selects an aspect the server then snaps away (SCOPE_2026-09-26 E2)."""
    js = _js_edit_caps()
    assert set(js) == set(core.EDIT_MODELS)
    for key, spec in core.EDIT_MODELS.items():
        aspects, dflt = js[key]
        assert aspects == spec["aspects"], key
        assert dflt == spec["default"], key
