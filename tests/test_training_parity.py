"""Basic LoRA training, held to PixAI's own trainer (SCOPE_2026-09-26 E7; probe findings
T04-T11 and SURF-13; owner ruling 4).

  * the base list, prices and image rule come from PixAI's own config key trainLoraModels,
    read live through the ONE /config reader (blocked in tests by conftest) with the
    2026-09-26 capture as fallback -- so Tsubaki.3 is offered and priced even offline;
  * the pre-selected base is the first SDXL row, never the first group's first model;
  * a run is free only for a MEMBER with quota (tier present, 0 counts), or with a matching
    training free card, which is checked with the site's own training shape and attached;
  * trigger words are normalized in the site's order, then validated (256 max, 30 min on
    DiT.2 / DiT.3), and the normalized string is what is submitted;
  * every image is held to the per-side size rule; a failing one refuses the run by name;
    an image of unknown size is listed as not checked;
  * the pause switch refuses a confirmed submit; a failed read proceeds as before.

Fully offline: every PixAI answer below is a stub or the transport fake."""
import datetime as _dt
import re
from pathlib import Path

import pytest

import moonglade_backup as core
from moonglade_gallery import CATALOG_FIELDS, create_app, media_dims, save_catalog
from tests.conftest import login_test_client

T3 = "2024383379556065549"          # Tsubaki.3, MMDIT26B_MODEL
T2 = "1983308862240288769"          # Tsubaki.2, MMDIT26A_MODEL
ILLUSTRIOUS = "1844843519625072849"  # the first SDXL row
ROOT = Path(__file__).resolve().parents[1]


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


# ------------------------------------------------------------------ the config

def test_a_failed_config_read_still_offers_and_prices_tsubaki3():
    """conftest blocks the /config reader, which is exactly a failed read: the snapshot
    answers, and it is the 2026-09-26 capture -- Tsubaki.3 at 100,000 included."""
    cfg = core.training_config()
    assert cfg["live"] is False
    assert any(m["version_id"] == T3 and m["model_type"] == "MMDIT26B_MODEL"
               for m in cfg["models"])
    assert core.training_price_for_version(T3) == 100000
    assert core.training_price_for_version(ILLUSTRIOUS) == 25000       # price, never originalPrice
    assert cfg["image_constraints"] == {"minWidth": 512, "minHeight": 512, "maxAspectRatio": 3}
    labels = [g["label"] for g in core.list_trainable_base_models()]
    assert labels[0] == "DiT.3"


_LIVE = {
    "models": [
        {"versionId": "900", "modelId": "901", "modelName": "New DiT", "usage": "animation",
         "modelType": "MMDIT26B_MODEL", "coverUrl": "https://images-ng.pixai.art/x"},
        {"versionId": "800", "modelId": "801", "modelName": "New XL", "usage": "animation",
         "modelType": "SDXL_MODEL", "coverUrl": ""},
        {"versionId": "700", "modelType": "SOMETHING_NEW_MODEL", "modelName": "Unlabelled"},
    ],
    "pricing": {"pricesByModelType": {
        "MMDIT26B_MODEL": {"price": 90000, "retrain": 60000, "reuse": 60000},
        "SDXL_MODEL": {"price": 30000, "originalPrice": 99000},
    }},
    "imageConstraints": {"minWidth": 256, "minHeight": 300, "maxAspectRatio": 4, "minImages": 10},
}


def _live_config(monkeypatch, answers):
    """Answer the /config reader per key, counting reads."""
    reads = []

    def _get(key, timeout=10):
        reads.append(key)
        ans = answers.get(key)
        if isinstance(ans, Exception):
            raise ans
        if ans is None:
            raise core.PixAIError("not stubbed: " + key)
        return ans
    monkeypatch.setattr(core, "_config_get", _get)
    return reads


def test_the_live_config_drives_list_price_default_and_image_rule(monkeypatch):
    reads = _live_config(monkeypatch, {"trainLoraModels": _LIVE})
    cfg = core.training_config()
    assert cfg["live"] is True
    assert core.training_price_for_version("900") == 90000
    assert core.training_price_for_version("800") == 30000
    assert core.training_price_for_version(T3) is None          # not on the live list
    assert core.default_training_base() == "800"                # the first SDXL row
    groups = core.list_trainable_base_models()
    assert [g["label"] for g in groups] == ["DiT.3", "SDXL"]    # unlabelled arch left out
    assert cfg["image_constraints"]["minWidth"] == 256.0
    assert cfg["image_constraints"]["maxAspectRatio"] == 4.0
    assert reads == ["trainLoraModels"]                          # cached after the first read


def test_the_config_cache_holds_a_failure_for_a_minute_then_retries(monkeypatch):
    reads = _live_config(monkeypatch, {"trainLoraModels": core.PixAIError("down")})
    core.training_config()
    core.training_config()
    assert reads == ["trainLoraModels"]                          # the failure is cached
    at, val = core._config_cache["trainLoraModels"]
    core._config_cache["trainLoraModels"] = (at - core._CONFIG_FAIL_TTL - 1, val)
    core.training_config()
    assert reads == ["trainLoraModels", "trainLoraModels"]      # ...for a minute only


def test_the_config_reader_is_the_one_blocked_helper():
    """The /config road sits outside /v2, which conftest's REST block never covered. One
    named reader, blocked by an autouse fixture, is what keeps the suite offline."""
    with pytest.raises(core.PixAIError):
        core._config_get("trainLoraModels")
    src = (ROOT / "moonglade_backup.py").read_text(encoding="utf-8")
    assert src.count("CONFIG_API_BASE +") == 1, "a second /config reader appeared"
    conftest = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert '"_config_get"' in conftest and "_config_cache.clear()" in conftest


# ------------------------------------------------------------ the default base

def test_the_default_base_is_the_first_sdxl_row_never_the_first_groups_first():
    assert core.default_training_base() == ILLUSTRIOUS
    groups = core.list_trainable_base_models()
    assert groups[0]["models"][0]["version_id"] == T3       # what the old rule would pick


def test_with_no_sdxl_row_the_default_is_the_first_row(monkeypatch):
    live = {"models": [m for m in _LIVE["models"] if m["modelType"] != "SDXL_MODEL"]}
    _live_config(monkeypatch, {"trainLoraModels": live})
    assert core.default_training_base() == "900"


def test_the_train_panels_take_the_servers_default_base():
    """Source guard: TrainOverlay and TrainMobile pre-select the server's
    default_version_id and no longer the first group's first model -- with Tsubaki.3 sorting
    first, that rule would pre-select the 100,000-credit base."""
    for name in ("TrainOverlay.jsx", "TrainMobile.jsx"):
        src = (ROOT / "gallery" / "src" / "components" / name).read_text(encoding="utf-8")
        assert "defaultBase(gs, d.default_version_id" in src, name
        assert "setBaseModel(gs[0].models[0].version_id)" not in src, name
        assert "CANNOT quote" not in src and "check the price on PixAI" not in src, name


def test_the_models_route_names_the_default_and_offers_tsubaki3(tmp_path, monkeypatch):
    save_catalog(tmp_path / "catalog.db", [_row(media_id="1", filename="a_1.png")])
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    d = login_test_client(create_app(tmp_path)).get("/api/train/models").get_json()
    assert d["default_version_id"] == ILLUSTRIOUS
    dit3 = next(g for g in d["groups"] if g["label"] == "DiT.3")
    assert dit3["models"][0]["version_id"] == T3 and dit3["price"] == 100000
    assert d["pricing"]["MMDIT26B_MODEL"]["price"] == 100000


# ------------------------------------------------------------- free: tier + quota

@pytest.mark.parametrize("me, expected", [
    ({"id": "1", "membership": {"tier": 3}, "quotaAmount": 10}, 10),
    ({"id": "1", "membership": {"tier": 0}, "quotaAmount": 2}, 2),       # tier 0 counts
    ({"id": "1", "membership": None, "quotaAmount": 5}, 0),              # not a member
    ({"id": "1", "membership": {"tier": None}, "quotaAmount": 5}, 0),
    ({"id": "1", "quotaAmount": 5}, 0),                                  # membership unread
    ({"id": "1", "membership": {"tier": 1}, "quotaAmount": None}, 0),
])
def test_free_quota_counts_only_for_a_member(pixai, me, expected):
    pixai.on("me", {"me": me})
    assert core.training_free_quota(pixai) == expected
    call = pixai.calls_for("me")[0]
    # ONE query reads both, so the tier and the quota can never come from different moments
    assert "membership { tier }" in call.document and "quotaAmount" in call.document


def test_a_failed_quota_read_is_not_free(pixai):
    pixai.fail("me", core.PixAIError("boom"))
    assert core.training_free_quota(pixai) == 0


# ------------------------------------------------------------ the training card

def test_the_card_check_uses_the_sites_training_shape(pixai):
    pixai.on("/kaisuuken/check", lambda call: {"matches": [
        {"templateId": "tpl", "total": 1, "consumeAmount": 1,
         "kaisuukens": [{"id": "K1", "expiresAt": "2026-12-01T00:00:00Z"}]}]})
    pixai.on("/kaisuuken/summary", {"kaisuukens": []})
    best = core.match_training_kaisuuken(pixai, T3)
    body = pixai.calls_for("/kaisuuken/check")[0].body
    assert body == {"type": "training-task", "baseModelId": T3, "version": 2}
    assert best["id"] == "K1" and core.card_covers(best)


def test_the_generation_check_is_unchanged(pixai):
    pixai.on("/kaisuuken/check", {"matches": []})
    core.match_kaisuuken(pixai, {"modelId": "5"})
    body = pixai.calls_for("/kaisuuken/check")[0].body
    assert body == {"type": "generation-task", "parameters": {"modelId": "5"}, "version": 2}


# -------------------------------------------------------------- trigger words

@pytest.mark.parametrize("raw, want", [
    ("  nel   druid  ", "nel druid"),
    ("Nel\r\nDruid", "nel, druid"),
    ("A\n\n\nB", "a, b"),
    ("a,, ,b", "a, b"),
    (",, x ,,", "x"),
    ("Hatsune Miku,  , Aqua Hair\n", "hatsune miku, aqua hair"),
    ("\t tab\tand  space ", "tab and space"),
    (None, ""),
])
def test_trigger_words_normalize_in_the_sites_order(raw, want):
    assert core.normalize_trigger_words(raw) == want


_OK = dict(media_ids=[str(i) for i in range(10)], title="t", category="character")


def _validate(base, trigger):
    return core.validate_training(base, _OK["media_ids"], _OK["title"], trigger,
                                  _OK["category"])


def test_trigger_word_limits():
    with pytest.raises(core.PixAIError, match="required"):
        _validate(ILLUSTRIOUS, " , ,\n ")
    with pytest.raises(core.PixAIError, match="too long"):
        _validate(ILLUSTRIOUS, "x" * 257)
    assert len(_validate(ILLUSTRIOUS, "x" * 256)) == 256     # 201..256 was refused before
    assert _validate(ILLUSTRIOUS, "Short") == "short"          # SDXL: no 30-character floor
    for base in (T3, T2):                                       # DiT.3 and DiT.2
        with pytest.raises(core.PixAIError, match="at least 30"):
            _validate(base, "x" * 29)
        assert _validate(base, "x" * 30) == "x" * 30
    # the rule reads the NORMALIZED length: padding does not buy characters
    with pytest.raises(core.PixAIError, match="at least 30"):
        _validate(T3, "   " + "y" * 25 + "   \n\n  ")


def test_the_normalized_trigger_words_are_what_is_submitted(monkeypatch):
    sent = {}
    monkeypatch.setattr(core, "gql_mutate", lambda s, q, v: sent.update(v) or
                        {"createTrainingTask": {"id": "t", "refId": "m"}})
    core.submit_training(object(), ILLUSTRIOUS, _OK["media_ids"], "t",
                         "Nel\nDruid,,  Moon", "character", kaisuuken_id="K9")
    assert sent["input"]["triggerWords"] == "nel, druid, moon"
    assert sent["input"]["kaisuukenId"] == "K9"


# --------------------------------------------------------------------- images

def test_the_per_side_image_rule():
    dims = {"ok": (1024, 1024), "square_min": (512, 512), "tall3": (512, 1536),
            "wide_short": (800, 400),       # passes the site's pixel count, fails per side
            "thin": (600, 1900), "tiny": (300, 300)}
    rejected, unchecked = core.check_training_images(
        list(dims) + ["nosize"], dims, {"minWidth": 512, "minHeight": 512, "maxAspectRatio": 3})
    assert {r["media_id"] for r in rejected} == {"wide_short", "thin", "tiny"}
    assert unchecked == ["nosize"]
    why = {r["media_id"]: r["why"] for r in rejected}
    assert "smaller" in why["wide_short"] and "longer" in why["thin"]


def test_the_live_image_rule_wins(monkeypatch):
    _live_config(monkeypatch, {"trainLoraModels": _LIVE})
    rejected, _ = core.check_training_images(["a"], {"a": (400, 280)})
    assert [r["media_id"] for r in rejected] == ["a"]            # height under the live 300
    rejected, _ = core.check_training_images(["c"], {"c": (300, 300)})
    assert rejected == []                                         # under 512, over the live 256/300
    rejected, _ = core.check_training_images(["b"], {"b": (300, 1200)})
    assert rejected == []                                         # ratio 4 allowed live


def test_media_dims_reads_only_known_positive_sizes(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="a", width="1024", height="768"),
                      _row(media_id="b", width="", height=""),
                      _row(media_id="c", width="0", height="512")])
    assert media_dims(db, ["a", "b", "c", "zz"]) == {"a": (1024, 768)}


# ------------------------------------------------------------------ the route

def _train_client(tmp_path, monkeypatch, rows=None, quota=0, card=None, card_error=None):
    save_catalog(tmp_path / "catalog.db", rows or [_row(media_id="1", filename="a_1.png")])
    calls = []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "training_free_quota", lambda s: quota)

    def _card(session, base, raise_on_error=False):
        calls.append(("card", base))
        if card_error is not None:
            raise card_error
        return card
    monkeypatch.setattr(core, "match_training_kaisuuken", _card)

    def _submit(session, *a, **kw):
        calls.append(("submit", a, kw))
        return {"id": "trn1", "refId": "model9"}
    monkeypatch.setattr(core, "submit_training", _submit)
    cli = login_test_client(create_app(tmp_path))
    csrf = cli.get("/api/panel/summary").get_json()["csrf"]
    return (lambda body: cli.post("/api/train/submit", json=dict(body, csrf=csrf))), calls


_BODY = {"base_model_id": ILLUSTRIOUS, "media_ids": [str(i) for i in range(12)],
         "title": "Nel test", "trigger_words": "nelnamara druid", "category": "character"}
_CARD = {"id": "K1", "name": "Training card", "expiresAt": "2026-12-01T00:00:00Z",
         "templateId": "tpl", "total": 1, "consumeAmount": 1, "covered": True}


def test_a_matching_training_card_makes_the_run_free_and_rides_the_submit(tmp_path, monkeypatch):
    post, calls = _train_client(tmp_path, monkeypatch, quota=0, card=_CARD)
    prev = post(_BODY).get_json()
    assert prev["is_free"] is True and prev["free_by"] == "card"
    assert "free card" in prev["cost_note"] and "Training card" in prev["cost_note"]
    d = post(dict(_BODY, confirm=True)).get_json()          # no accept_credit_cost needed
    assert d["submitted"] is True and d["used_card"] is True
    submit = [c for c in calls if c[0] == "submit"]
    assert len(submit) == 1 and submit[0][2]["kaisuuken_id"] == "K1"


def test_the_quota_wins_before_any_card_check(tmp_path, monkeypatch):
    # A DELIBERATE DIFFERENCE from PixAI's basic trainer, which runs the card check whatever
    # the quota and attaches a matching card even when the quota covers the run. The scope
    # (E7, ruling 4) checks a card "before a paid run"; api_train_submit says so at the check,
    # and DECISIONS records it with the other differences. Changing it is the owner's call.
    post, calls = _train_client(tmp_path, monkeypatch, quota=3, card=_CARD)
    prev = post(_BODY).get_json()
    assert prev["free_by"] == "quota"
    assert not [c for c in calls if c[0] == "card"]
    post(dict(_BODY, confirm=True))
    assert [c for c in calls if c[0] == "submit"][0][2]["kaisuuken_id"] == ""


def test_a_short_card_is_not_free(tmp_path, monkeypatch):
    post, calls = _train_client(tmp_path, monkeypatch, quota=0,
                                card=dict(_CARD, total=0, consumeAmount=1, covered=False))
    prev = post(_BODY).get_json()
    assert prev["is_free"] is False and "25,000" in prev["cost_note"]
    assert post(dict(_BODY, confirm=True)).status_code == 402


def test_a_failed_card_check_refuses_the_confirm_and_is_said_in_the_preview(
        tmp_path, monkeypatch):
    post, calls = _train_client(tmp_path, monkeypatch, quota=0,
                                card_error=core.PixAIError("blip"))
    prev = post(_BODY).get_json()
    assert prev["is_free"] is False and "couldn't be checked" in prev["cost_note"]
    r = post(dict(_BODY, confirm=True, accept_credit_cost=True))
    assert r.status_code == 502 and "nothing was spent" in r.get_json()["error"]
    assert not [c for c in calls if c[0] == "submit"]


def test_read_only_refuses_the_confirm_before_the_card_check_or_the_pause_read(
        tmp_path, monkeypatch):
    """The confirm's new reads (the card check, the pause switch) must not reach the account
    for a submit READ_ONLY is going to refuse -- the rule core.submit follows."""
    post, calls = _train_client(tmp_path, monkeypatch, quota=0, card=_CARD)
    reads = _live_config(monkeypatch, {"trainLoraStatus": {"state": "OPEN"}})
    monkeypatch.setattr(core, "READ_ONLY", True)
    assert post(_BODY).get_json()["preview"] is True          # the preview still answers
    del calls[:]
    r = post(dict(_BODY, confirm=True, accept_credit_cost=True))
    assert r.status_code == 502 and "READ_ONLY" in r.get_json()["error"]
    assert calls == [] and "trainLoraStatus" not in reads


def test_a_non_member_with_quota_pays_and_must_accept(tmp_path, monkeypatch, pixai):
    """The whole of T09: quota left but no membership -> not free, and the paid confirm's
    acknowledgement applies."""
    pixai.on("me", {"me": {"id": "1", "membership": None, "quotaAmount": 5}})
    save_catalog(tmp_path / "catalog.db", [_row(media_id="1", filename="a_1.png")])
    monkeypatch.setattr(core, "match_training_kaisuuken", lambda *a, **k: None)
    submitted = []
    monkeypatch.setattr(core, "submit_training",
                        lambda *a, **k: submitted.append(1) or {"id": "t", "refId": "m"})
    cli = login_test_client(create_app(tmp_path))
    assert cli.get("/api/train/quota").get_json()["free_trainings"] == 0
    csrf = cli.get("/api/panel/summary").get_json()["csrf"]
    prev = cli.post("/api/train/submit", json=dict(_BODY, csrf=csrf)).get_json()
    assert prev["is_free"] is False
    r = cli.post("/api/train/submit", json=dict(_BODY, csrf=csrf, confirm=True))
    assert r.status_code == 402 and not submitted


def test_tsubaki3_is_quoted_at_its_real_price(tmp_path, monkeypatch):
    post, _ = _train_client(tmp_path, monkeypatch, quota=0)
    prev = post(dict(_BODY, base_model_id=T3,
                     trigger_words="a moonlit night elf druid in the grove")).get_json()
    assert prev["price"] == 100000 and "100,000" in prev["cost_note"]


def test_a_rejected_image_refuses_the_run_by_name(tmp_path, monkeypatch):
    rows = [_row(media_id=str(i), filename="%d.png" % i, width="1024", height="1024")
            for i in range(12)]
    rows[4]["width"], rows[4]["height"] = "800", "400"
    post, calls = _train_client(tmp_path, monkeypatch, rows=rows, quota=3)
    r = post(_BODY)
    assert r.status_code == 400
    d = r.get_json()
    assert [x["media_id"] for x in d["rejected_images"]] == ["4"]
    assert "4 (800x400" in d["error"]
    assert post(dict(_BODY, confirm=True)).status_code == 400
    assert not [c for c in calls if c[0] == "submit"]


def test_an_image_of_unknown_size_is_listed_not_checked(tmp_path, monkeypatch):
    rows = [_row(media_id=str(i), filename="%d.png" % i, width="1024", height="1024")
            for i in range(10)]                               # "10" and "11" have no row
    post, calls = _train_client(tmp_path, monkeypatch, rows=rows, quota=3)
    prev = post(_BODY).get_json()
    assert prev["unchecked_images"] == ["10", "11"]
    assert "2 images could not be checked" in prev["image_note"]
    assert post(dict(_BODY, confirm=True)).get_json()["submitted"] is True


# ------------------------------------------------------------------ the pause

def _iso(hours):
    t = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=hours)
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


@pytest.mark.parametrize("status, refused, names_time", [
    ({"state": "PAUSED", "resumesAt": _iso(3)}, True, True),
    ({"state": "PAUSED", "resumesAt": _iso(-3)}, True, False),     # a past time is not named
    ({"state": "PAUSED", "resumesAt": "not a date"}, True, False),
    ({"state": "OPEN", "disabled": True}, True, False),
    ({"state": "OPEN"}, False, False),
    ([], False, False),                                             # not an object: open
])
def test_the_pause_switch(tmp_path, monkeypatch, status, refused, names_time):
    post, calls = _train_client(tmp_path, monkeypatch, quota=3)
    _live_config(monkeypatch, {"trainLoraStatus": status})
    assert post(_BODY).get_json()["preview"] is True           # the preview never refuses
    r = post(dict(_BODY, confirm=True))
    submitted = [c for c in calls if c[0] == "submit"]
    if refused:
        assert r.status_code == 409 and not submitted
        assert ("expects to be back around" in r.get_json()["error"]) is names_time
    else:
        assert r.get_json()["submitted"] is True and len(submitted) == 1


def test_a_failed_pause_read_proceeds_as_today(tmp_path, monkeypatch):
    post, calls = _train_client(tmp_path, monkeypatch, quota=3)   # conftest blocks /config
    assert post(dict(_BODY, confirm=True)).get_json()["submitted"] is True


def test_the_training_docs_no_longer_say_the_price_cannot_be_quoted():
    gallery = (ROOT / "moonglade_gallery.py").read_text(encoding="utf-8")
    backup = (ROOT / "moonglade_backup.py").read_text(encoding="utf-8")
    assert "this app CANNOT say how many" not in gallery
    assert not re.search(r"is NOT reachable through any documented endpoint", backup)


# ------------------------------------------------ review fixes (2026-09-26, E7)

def test_the_acknowledged_amount_must_be_this_runs_price(tmp_path, monkeypatch):
    """Quote on the SDXL default (25,000), tick "Spend 25,000 credits", then switch the base
    to Tsubaki.3 before pressing Start: the confirm carries the amount the box named, and a
    run that now costs 100,000 is refused with nothing submitted."""
    post, calls = _train_client(tmp_path, monkeypatch, quota=0)
    prev = post(_BODY).get_json()
    assert prev["price"] == 25000
    r = post(dict(_BODY, base_model_id=T3, trigger_words="a moonlit night elf druid in the grove",
                  confirm=True, accept_credit_cost=25000))
    assert r.status_code == 409 and "nothing was spent" in r.get_json()["error"].lower()
    assert "25,000" in r.get_json()["error"] and "100,000" in r.get_json()["error"]
    assert not [c for c in calls if c[0] == "submit"]
    # the amount that IS the price goes through; so does a bare true (no amount to name)
    assert post(dict(_BODY, confirm=True, accept_credit_cost=25000)).get_json()["submitted"]
    assert post(dict(_BODY, confirm=True, accept_credit_cost=True)).get_json()["submitted"]
    # a bool is never read as an amount (True == 1 in Python)
    assert len([c for c in calls if c[0] == "submit"]) == 2


def test_the_panels_send_the_amount_and_drop_a_stale_quote():
    """Source guard: both panels send acceptCostField (the amount), and the desktop panel --
    whose base chips stay live under the confirm -- clears the quote on any form change."""
    for name in ("TrainOverlay.jsx", "TrainMobile.jsx"):
        src = (ROOT / "gallery" / "src" / "components" / name).read_text(encoding="utf-8")
        assert "...acceptCostField(ask, acceptCost)" in src, name
        assert "accept_credit_cost: acceptCost" not in src, name
    overlay = (ROOT / "gallery" / "src" / "components" / "TrainOverlay.jsx").read_text(
        encoding="utf-8")
    assert re.search(r"useEffect\(\(\) => \{ setAsk\(null\); setAcceptCost\(false\); \},\s*"
                     r"\[baseModel, archIdx, picked, trigger, name, category\]\);", overlay)


def test_a_card_of_unknown_balance_is_not_free(tmp_path, monkeypatch):
    """PixAI's own training check keeps only matches with consumeAmount <= total, so a card
    whose held count could not be read is not attached there -- and here it must not skip the
    paid acknowledgement on a 25,000-100,000 credit run."""
    post, calls = _train_client(tmp_path, monkeypatch, quota=0,
                                card=dict(_CARD, total=None, covered=True,
                                          balance_unknown=True))
    prev = post(_BODY).get_json()
    assert prev["is_free"] is False and prev["free_by"] is None
    assert post(dict(_BODY, confirm=True)).status_code == 402
    d = post(dict(_BODY, confirm=True, accept_credit_cost=25000)).get_json()
    assert d["submitted"] is True
    assert [c for c in calls if c[0] == "submit"][0][2]["kaisuuken_id"] == ""


def test_one_request_prices_off_the_config_it_validated_with(tmp_path, monkeypatch):
    """The route reads the training config once and prices from THAT read: a cache entry
    expiring between validation and pricing must not mix a live answer with the snapshot."""
    post, _ = _train_client(tmp_path, monkeypatch, quota=0)
    live = core.training_config()
    live["pricing"] = dict(live["pricing"], SDXL_MODEL={"price": 31000})
    snapshot = core.training_config()                  # SDXL at the snapshot's 25,000
    answers = iter([live])                             # the first read answers live...
    monkeypatch.setattr(core, "training_config", lambda: next(answers, snapshot))
    assert post(_BODY).get_json()["price"] == 31000    # ...and the price is that read's


@pytest.mark.parametrize("base, trigger, ok", [
    (ILLUSTRIOUS, "\U0001F319" * 128, True),        # 256 UTF-16 units: the limit exactly
    (ILLUSTRIOUS, "\U0001F319" * 129, False),       # 258 units: too long on PixAI (len() 129)
    (T3, "\U0001F319" * 15, True),                  # 30 units: long enough on DiT.3 (len() 15)
    (T3, "\U0001F319" * 14 + "a", False),           # 29 units
])
def test_trigger_words_are_counted_as_the_site_counts_them(base, trigger, ok):
    """JavaScript's `length` -- UTF-16 code units -- is what PixAI's own rule measures, so an
    emoji counts 2 on both limits."""
    if ok:
        assert _validate(base, trigger) == trigger
    else:
        with pytest.raises(core.PixAIError):
            _validate(base, trigger)
    assert core.trigger_word_length("\U0001F319a") == 3


def test_the_image_refusal_reads_right_for_one_image():
    one = core.describe_rejected_training_images(
        [{"media_id": "4", "width": 800, "height": 400, "why": "smaller than 512x512"}])
    assert one.startswith("PixAI won't train on 1 of these images — remove it and try again")
    two = core.describe_rejected_training_images(
        [{"media_id": str(i), "width": 300, "height": 300, "why": "smaller than 512x512"}
         for i in range(2)])
    assert "2 of these images — remove them" in two
