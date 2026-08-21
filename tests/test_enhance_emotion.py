"""Change Emotion wiring: the staged-options list endpoint + the picked-emotion pass-through
into the panelplugin submit (and only for that one preset)."""
import moonglade_backup as core
import moonglade_gallery as g
from tests.conftest import login_client


def _client(tmp_path):
    g.save_catalog(tmp_path / "catalog.db", [])
    return login_client(tmp_path)


def _stage(key):
    d = g.branding_root() / "bridge" / "emotion"
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

    def _submit(session, params):
        calls["params"] = params
        return "T-1"

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "mirror_enabled", lambda: True)
    monkeypatch.setattr(core, "make_mirror_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(core, "submit_generation", _submit)
    return calls


def test_picked_emotion_reaches_submit_only_for_the_emotion_preset(tmp_path, monkeypatch):
    cli = _client(tmp_path)
    calls = _arm(monkeypatch)
    # the emotion preset carries the pick into inputs
    cli.post("/api/enhance", json={"source": "srcABC",
                                   "workflow_name": core.ENHANCE_EMOTION_WORKFLOW,
                                   "emotion": "happy"})
    # the picked KEY is translated to emotionlab's danbooru TAG string on the `prompt` arg
    assert core.ENHANCE_EMOTION_ARG == "prompt"
    assert calls["params"]["inputs"].get(core.ENHANCE_EMOTION_ARG) == "smile"
    assert core.ENHANCE_EMOTION_PROMPTS["happy"] == "smile"
    # a DIFFERENT preset never gets the stray arg, even if an emotion is sent
    calls["params"] = None
    cli.post("/api/enhance", json={"source": "srcABC",
                                   "workflow_name": "mymusise/hand-fix:v1", "emotion": "happy"})
    assert core.ENHANCE_EMOTION_ARG not in calls["params"]["inputs"]
