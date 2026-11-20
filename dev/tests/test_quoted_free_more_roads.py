"""The other roads a send shown as FREE can take (review of 52b91ed3, 2026-11-18).

- a single send through /api/generate/run (a template prompt that expands to one generation):
  it had no confirmed total, so no check; it now carries expect_free and is refused before its
  create when no card attaches;
- AI presets: the chip's "free" is card_covers (a short card is not free), and the cached
  verdicts are dropped after a send or a refusal, so a refused preset stops showing "free";
- the quote reads cards under the identity the send will use (the Mirror's sign-in when on).

No network: the run road uses test_generate_runs' counting rig, the rest the `pixai` fake."""
import json

from moonglade import backup as core
from moonglade import gen_road as gen_road_mod
from moonglade import pricing as pricing_mod
from tests.test_generate_runs import CARD as RUN_CARD
from tests.test_generate_runs import cli, rig, run  # noqa: F401  (fixtures + helper)
from tests.test_single_send_quoted_free import (  # noqa: F401  (fixture + helpers)
    CARD_ID, _CARD, _NO_CARD, _Req, _body, gen)


# ---- the run road's single send -------------------------------------------------------------

def test_a_single_run_quoted_free_whose_card_is_gone_is_refused_before_the_create(cli, rig):
    rig.card_default = None
    d = run(cli, prompt="{solo|} glade", var_mode="matrix", expect_free=True).get_json()
    assert rig.mutations == [], d
    assert "free card" in json.dumps(d)


def test_a_single_run_quoted_free_with_its_card_sends_with_it(cli, rig):
    rig.card_default = RUN_CARD
    d = run(cli, prompt="{solo|} glade", var_mode="matrix", expect_free=True).get_json()
    assert d["status"] == "sent" and len(rig.mutations) == 1
    assert rig.mutations[0]["kaisuukenId"] == "K1"


def test_a_single_run_without_the_flag_still_goes_out(cli, rig):
    """A badge that showed a price sends no flag: that single send is unchanged."""
    rig.card_default = None
    d = run(cli, prompt="{solo|} glade", var_mode="matrix").get_json()
    assert d["status"] == "sent" and len(rig.mutations) == 1


# ---- AI presets ---------------------------------------------------------------------------

def _armed(monkeypatch, fake):
    from moonglade import mirror as _mirror
    monkeypatch.setattr(_mirror, "mirror_enabled", lambda: True)
    monkeypatch.setattr(_mirror, "make_mirror_session", lambda *a, **k: fake)
    monkeypatch.setattr(_mirror, "_session_for_create", lambda s: fake)
    monkeypatch.setattr(pricing_mod, "price_task", lambda s, params: 1500)
    monkeypatch.setattr(gen_road_mod, "build_request", lambda payload, *a, **k: _Req("enhance"))


def _presets(g):
    return g["cli"].get("/api/enhance/presets").get_json()["presets"]


def test_a_preset_a_card_only_partly_covers_is_not_free(gen, monkeypatch):
    _armed(monkeypatch, gen["pixai"])
    short = {"matches": [{"templateId": "tpl-1", "total": 1, "consumeAmount": 3,
                          "kaisuukens": [{"id": CARD_ID, "expiresAt": None}]}], "total": 1}
    gen["pixai"].on("/kaisuuken/check", short)
    rows = _presets(gen)
    assert rows and not any(r["free_card"] for r in rows)



def _enhance_config(monkeypatch):
    """3.22 S3-enhance: the presets price on PixAI's enhance quote, their type read off the live
    config, answered here for every pinned preset; and an enhance sends through submit_enhance."""
    plugins = {t: {"workflowName": wn} for t, wn in (
        ("handfix", "mymusise/hand-fix"), ("face-detailer", "kyo/face-detailer"),
        ("emotion", "kyo/emotionlab"), ("background-remover", "mymusise/39a2c67c"),
        ("image-to-lineart", "pixai-official/image-to-lineart"),
        ("sketch-coloring", "pixai-official/sketch-coloring-workflow"))}
    monkeypatch.setattr(core, "_cached_config", lambda key, **k: {
        "imageEnhancementPlugins": plugins} if key == "constants" else None)
    monkeypatch.setattr(pricing_mod, "enhance_quote_session", lambda: object())
    monkeypatch.setattr(gen_road_mod, "submit_enhance", lambda *a, **k: "task-1")


def test_an_ai_preset_send_claiming_a_free_quote_is_refused_and_nothing_created(gen, monkeypatch):
    """3.22 S3-enhance (V9): an enhance never takes a card, so the chips never say FREE and a
    send that claims a FREE quote is refused with nothing sent."""
    _armed(monkeypatch, gen["pixai"])
    _enhance_config(monkeypatch)
    monkeypatch.setattr(pricing_mod, "price_enhance", lambda s, body: 1000)
    assert not any(r["free_card"] for r in _presets(gen))
    sent = []
    monkeypatch.setattr(gen_road_mod, "submit_enhance", lambda *a, **k: sent.append(a) or "t")
    d = gen["cli"].post("/api/enhance", json={"source": "1", "workflow_id": "42",
                                              "expect_free": True}).get_json()
    assert "never uses a free card" in d["error"] and d["state"] == "not_sent"
    assert sent == [] and gen["pixai"].calls_for("/kaisuuken/check") == []


def test_presets_read_the_price_again_after_a_send(gen, monkeypatch):
    _armed(monkeypatch, gen["pixai"])
    _enhance_config(monkeypatch)
    asked = []
    monkeypatch.setattr(pricing_mod, "price_enhance",
                        lambda s, body: asked.append(body) or 1000)
    _presets(gen)
    n = len(asked)
    _presets(gen)
    assert len(asked) == n, "a fully-priced answer is cached"
    d = gen["cli"].post("/api/enhance", json={"source": "1", "workflow_id": "42"}).get_json()
    assert d.get("task_id") == "task-1", d
    _presets(gen)
    assert len(asked) > n, "re-read after the send"


def test_the_enhance_tab_reads_prices_again_after_every_send():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "gallery/src/components/EnhanceTab.jsx"
           ).read_text(encoding="utf-8")
    assert "}, [armed, priceSeq]);" in src
    i = src.index('await submitTask("/api/enhance"')
    assert "setPriceSeq((n) => n + 1);" in src[i:i + 300]


# ---- the quote's identity -----------------------------------------------------------------

def test_the_quote_checks_cards_under_the_identity_the_send_will_use(gen, monkeypatch):
    """With the Mirror on, the send's card step reads on the Mirror's sign-in; so does the
    badge now. The API key's answer is not consulted for the card."""
    from moonglade import mirror as _mirror
    from tests.fake_pixai import FakePixAI
    mirror = FakePixAI()
    mirror.on("/kaisuuken/check", _CARD)
    gen["pixai"].on("/kaisuuken/check", _NO_CARD)
    monkeypatch.setattr(_mirror, "_session_for_create", lambda s: mirror)
    monkeypatch.setattr(pricing_mod, "price_task", lambda s, params: 400)
    q = gen["cli"].post("/api/price", json=dict(_body(), mode="image")).get_json()
    assert q.get("free") is True, q
    assert mirror.calls_for("/kaisuuken/check")
    assert gen["pixai"].calls_for("/kaisuuken/check") == []


def test_a_mirror_that_cannot_be_reached_still_quotes_on_the_api_key(gen, monkeypatch):
    from moonglade import mirror as _mirror

    def _down(s):
        raise core.PixAIError("Mirror to PixAI is ON but its website sign-in is expired")
    monkeypatch.setattr(_mirror, "_session_for_create", _down)
    gen["pixai"].on("/kaisuuken/check", _CARD)
    monkeypatch.setattr(pricing_mod, "price_task", lambda s, params: 400)
    q = gen["cli"].post("/api/price", json=dict(_body(), mode="image")).get_json()
    assert q.get("free") is True and "error" not in q, q
