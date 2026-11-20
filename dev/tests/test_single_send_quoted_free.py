"""A single web send carries what its cost badge showed (2026-11-18).

The gallery's own Generate / Edit / AI preset / Video sends match the free card again at send
time (_apply_kaisuuken). When the card the quote found is gone by then (used elsewhere,
expired), that step attaches nothing and the send used to go out at full price, with only a
server-console line ("no matching free card -> this will spend credits") to say so. A send whose
badge said FREE now carries `expect_free`, and the server refuses it before anything is sent,
with an {error} the drawer shows -- the rule the Loom's own Render has had since Session P (F13).
A send whose badge showed a PRICE carries nothing and goes out exactly as before (issue #15: a
card that covers only part still spends, the full price stated).

No network: the PixAI transport is the `pixai` fake, the card check and the create are the real
code paths (_apply_kaisuuken -> match_kaisuuken -> POST /kaisuuken/check; submit_generation ->
gql_mutate createGenerationTask), so "nothing was sent" is read off the fake's own record of
create mutations, not off a stub of the function under test."""
import pytest

from moonglade import backup as core
from moonglade import gen_params as gen_params_mod
from moonglade import gen_road as gen_road_mod
from tests.conftest import login_client

V = "1983308862240288769"
CARD_ID = "kaisuuken-1"
_CARD = {"matches": [{"templateId": "tpl-1", "total": 3, "consumeAmount": 1,
                      "kaisuukens": [{"id": CARD_ID, "expiresAt": "2026-12-01T00:00:00.000Z"}]}],
         "total": 3}
_NO_CARD = {"matches": [], "total": 0}


@pytest.fixture
def gen(tmp_path, monkeypatch, pixai):
    """A signed-in client whose /api/generate builds offline and sends through the real card
    step and the real create, both answered by the fake."""
    def _rest_get(session, path, **k):
        if "kaisuuken" in path:
            return {"kaisuukens": []}
        return [{"id": V, "modelId": "M1"}]
    monkeypatch.setattr(core, "_rest_get", _rest_get)
    monkeypatch.setattr(gen_params_mod, "_gen_parameters",
                        lambda args: {"modelId": args.model, "prompt": "a cat", "width": 512,
                                      "height": 512})
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    pixai.on("createGenerationTask", {"createGenerationTask": {"id": "task-1"}})
    return {"cli": login_client(tmp_path), "pixai": pixai}


def _body(**extra):
    b = {"model_id": "M1", "version_id": V, "prompt": "a cat"}
    b.update(extra)
    return b


def _created(g):
    return g["pixai"].calls_for("createGenerationTask")


def test_quoted_free_card_gone_is_refused_and_nothing_is_created(gen):
    gen["pixai"].on("/kaisuuken/check", _NO_CARD)
    r = gen["cli"].post("/api/generate", json=_body(expect_free=True))
    d = r.get_json()
    assert r.status_code == 200 and not d.get("task_id")
    assert "free card" in d["error"] and "Nothing was sent" in d["error"]
    assert gen["pixai"].mutations("createGenerationTask") == 0
    assert _created(gen) == []
    # The card step did run (the refusal is about ITS answer, not a skipped check).
    assert gen["pixai"].calls_for("/kaisuuken/check")


def test_quoted_free_card_present_sends_with_the_card(gen):
    gen["pixai"].on("/kaisuuken/check", _CARD)
    d = gen["cli"].post("/api/generate", json=_body(expect_free=True)).get_json()
    assert d.get("task_id") == "task-1", d
    assert gen["pixai"].mutations("createGenerationTask") == 1
    sent = _created(gen)[0].variables["parameters"]
    assert sent["kaisuukenId"] == CARD_ID
    assert "expect_free" not in sent


def test_a_priced_quote_sends_and_spends_as_before(gen):
    """No expect_free (the badge showed a price): no card is found and it goes out paid --
    the owner's issue-#15 ruling, unchanged."""
    gen["pixai"].on("/kaisuuken/check", _NO_CARD)
    d = gen["cli"].post("/api/generate", json=_body()).get_json()
    assert d.get("task_id") == "task-1", d
    assert gen["pixai"].mutations("createGenerationTask") == 1
    assert "kaisuukenId" not in _created(gen)[0].variables["parameters"]


def test_a_short_card_on_a_free_quote_is_refused(gen):
    """The card is still held but now covers only part (held < needed): _apply_kaisuuken
    attaches nothing, so a send the badge called FREE is refused rather than charged."""
    short = {"matches": [{"templateId": "tpl-1", "total": 1, "consumeAmount": 3,
                          "kaisuukens": [{"id": CARD_ID, "expiresAt": None}]}], "total": 1}
    gen["pixai"].on("/kaisuuken/check", short)
    d = gen["cli"].post("/api/generate", json=_body(expect_free=True)).get_json()
    assert "free card" in d["error"]
    assert gen["pixai"].mutations("createGenerationTask") == 0


# ---- the other single-send routes carry the same guard -----------------------------------

class _Req:
    """A built request with parameters, as build_request hands one to the route."""
    def __init__(self, mode):
        self.mode, self.parameters, self.unlimited, self.no_card = mode, {"modelId": V}, False, False
        self.adjusted, self.note, self.media_id, self.boxes = [], "", None, None
        self.lora_version_ids, self.model_version_id = [], V


@pytest.mark.parametrize("route,mode,body", [
    ("/api/edit", "edit", {"source": "1", "instruction": "make it night"}),
    ("/api/enhance", "enhance", {"source": "1", "workflow_id": "42"}),
])
def test_edit_and_ai_presets_refuse_a_free_quote_whose_card_is_gone(gen, monkeypatch, route, mode, body):
    from moonglade import mirror as _mirror
    monkeypatch.setattr(_mirror, "mirror_enabled", lambda: True)          # enhance's gate
    monkeypatch.setattr(_mirror, "make_mirror_session", lambda *a, **k: gen["pixai"])
    monkeypatch.setattr(_mirror, "_session_for_create", lambda s: s)
    seen = []
    monkeypatch.setattr(gen_road_mod, "build_request",
                        lambda payload, *a, **k: seen.append(dict(payload)) or _Req(mode))
    gen["pixai"].on("/kaisuuken/check", _NO_CARD)
    d = gen["cli"].post(route, json=dict(body, expect_free=True)).get_json()
    assert "free card" in d["error"], d
    assert gen["pixai"].mutations("createGenerationTask") == 0
    assert "expect_free" not in seen[0], "the flag is the route's, never the builder's"
    # The same send without the flag (a priced badge) goes out.
    d = gen["cli"].post(route, json=body).get_json()
    assert d.get("task_id") == "task-1", d


def test_the_gallery_video_tab_refuses_a_free_quote_whose_card_is_gone(gen, monkeypatch):
    """/api/loom/generate with no Loom keys is the gallery's own Video tab. It used to be held
    to expect_free only when the Loom's journal keys rode along."""
    gen["pixai"].on("/kaisuuken/check", _NO_CARD)
    body = {"mode": "I2V", "prompt": "x", "images": ["733917871331404290"], "duration": 5}
    d = gen["cli"].post("/api/loom/generate", json=dict(body, expect_free=True)).get_json()
    assert "free card" in d["error"], d
    assert gen["pixai"].mutations("createGenerationTask") == 0


def test_an_unlimited_mode_request_is_never_held_to_a_card(gen, monkeypatch):
    """A lane request is free by the entitlement and carries no card: the guard is not built
    for it even if a client sent expect_free (the badge's unlimited quote is free: true)."""
    req = _Req("edit")
    req.unlimited = True
    monkeypatch.setattr(gen_road_mod, "build_request", lambda payload, *a, **k: req)
    d = gen["cli"].post("/api/edit", json={"source": "1", "instruction": "x",
                                           "expect_free": True}).get_json()
    assert d.get("task_id") == "task-1", d
    assert gen["pixai"].mutations("createGenerationTask") == 1
    assert gen["pixai"].calls_for("/kaisuuken/check") == [], "a lane request is never card-checked"
