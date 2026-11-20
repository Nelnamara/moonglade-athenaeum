"""Change Emotion wiring: the staged-options list endpoint + the picked-emotion pass-through
into the panelplugin submit (and only for that one preset)."""
from moonglade import backup as core
from moonglade import cards as cards_mod
from moonglade import gallery as g
from moonglade import gen_params as gen_params_mod
from moonglade import gen_road as gen_road_mod
from tests.conftest import login_client
from moonglade import mirror as mirror_mod
from moonglade import branding as branding_mod


def _client(tmp_path):
    g.save_catalog(tmp_path / "catalog.db", [])
    return login_client(tmp_path)


def _stage(key):
    # Staged art lives in the CODED emotion dir (bundle-v2: paths built from the
    # role map, never retyped); the emitted URL stays the public role form.
    d = branding_mod._role_dir("emotion")
    d.mkdir(parents=True, exist_ok=True)
    (d / (key + ".webp")).write_bytes(b"fake-webp-bytes")   # endpoint lists by extension


def test_emotions_endpoint_self_populates_from_staged_art(tmp_path):
    cli = _client(tmp_path)
    assert cli.get("/api/enhance/emotions").get_json()["emotions"] == []   # none staged yet
    _stage("happy")
    _stage("aroused")
    _stage("sad-eyes")
    by = {e["key"]: e for e in cli.get("/api/enhance/emotions").get_json()["emotions"]}
    assert set(by) == {"happy", "aroused", "sad-eyes"}
    assert by["happy"]["label"] == "Happy" and by["sad-eyes"]["label"] == "Sad Eyes"
    assert by["happy"]["img"] == "/branding/bridge/emotion/happy.webp"
    # membership gating surfaces per PixAI's config: "happy" is free, "aroused" is gated,
    # an unknown custom stem defaults to not-gated.
    assert by["happy"]["membership"] is False
    assert by["aroused"]["membership"] is True
    assert by["sad-eyes"]["membership"] is False


def _arm(monkeypatch):
    calls = {"params": None}

    def _submit(session, params, **_kw):
        calls["params"] = params
        return "T-1"

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(mirror_mod, "mirror_enabled", lambda: True)
    monkeypatch.setattr(mirror_mod, "make_mirror_session", lambda *a, **k: object())
    monkeypatch.setattr(cards_mod, "_apply_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(gen_road_mod, "submit_enhance", _submit)     # the door's enhance (3.22)
    monkeypatch.setattr(core, "_cached_config", lambda key, **k: {"imageEnhancementPlugins": {
        "handfix": {"workflowName": "mymusise/hand-fix"},
        "face-detailer": {"workflowName": "kyo/face-detailer"},
        "emotion": {"workflowName": "kyo/emotionlab"},
        "background-remover": {"workflowName": "mymusise/39a2c67c"},
        "image-to-lineart": {"workflowName": "pixai-official/image-to-lineart"},
        "sketch-coloring": {"workflowName": "pixai-official/sketch-coloring-workflow"}}}
                        if key == "constants" else None)
    return calls


def test_picked_emotion_reaches_submit_only_for_the_emotion_preset(tmp_path, monkeypatch):
    cli = _client(tmp_path)
    calls = _arm(monkeypatch)
    # the emotion preset carries the pick into inputs
    cli.post("/api/enhance", json={"source": "srcABC",
                                   "workflow_name": gen_params_mod.ENHANCE_EMOTION_WORKFLOW,
                                   "emotion": "happy"})
    # the picked KEY is translated to emotionlab's danbooru TAG string, which rides the REST
    # route's `prompt` (3.22: {enhanceType: "emotion", mediaId, prompt})
    assert gen_params_mod.ENHANCE_EMOTION_ARG == "prompt"
    assert calls["params"]["enhanceType"] == "emotion"
    assert calls["params"].get("prompt") == "smile"
    assert gen_params_mod.ENHANCE_EMOTION_PROMPTS["happy"] == "smile"
    # a DIFFERENT preset never gets the stray arg, even if an emotion is sent
    calls["params"] = None
    cli.post("/api/enhance", json={"source": "srcABC",
                                   "workflow_name": "mymusise/hand-fix:v1", "emotion": "happy"})
    assert calls["params"]["enhanceType"] == "handfix" and "prompt" not in calls["params"]
