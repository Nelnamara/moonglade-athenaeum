"""LoRA training, Session J (2026-09-28): the advanced flow, runs, publish, a reused Basic set,
and the spend guards the adversarial review asked for
(../moonglade-internal/design/notes/training/BUILD-w3-train.md, sections 3 and 7).

What is pinned here, route by route:
  * every write refuses without the CSRF token and under READ_ONLY, and READ_ONLY is checked
    before any read on a confirm;
  * a paid confirm (describe, start, retry, Basic start) goes out ONCE, only with the fresh
    quote's number acknowledged -- never a stale number, never a bare `true` when there is a
    number to name -- and never while another request holds the run;
  * the spend guards: a second identical Basic start, a second retry of the same failed run and
    an unclear failure ("may have started") are refused, and the guards survive a restart;
  * the request shapes PixAI's own pages send (the advanced draft, the default options, the
    reused set as `trainingTaskId` with no images, publish, make public);
  * opening a draft, the runs list and the datasets list only read.

Fully offline: PixAI is the transport fake (tests/fake_pixai.py) or a stub."""
import inspect
import re
import threading

import pytest
import requests

import moonglade_backup as core
from moonglade_gallery import CATALOG_FIELDS, TrainGuard, create_app, save_catalog
from tests.conftest import login_test_client

T3 = "2024383379556065549"          # Tsubaki.3 (MMDIT26B), Recommended
T2 = "1983308862240288769"          # Tsubaki.2 (MMDIT26A)
SDXL = "1844843519625072849"
TRIGGER = "a moonlit night elf druid in the grove"      # over 30: DiT.2 / DiT.3 rule


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _app(tmp_path, rows=None):
    save_catalog(tmp_path / "catalog.db", rows or [_row(media_id="1", filename="a_1.png")])
    cli = login_test_client(create_app(tmp_path))
    csrf = cli.get("/api/panel/summary").get_json()["csrf"]

    def post(url, body=None, csrf_ok=True):
        return cli.post(url, json=dict(body or {}, **({"csrf": csrf} if csrf_ok else {})))
    return cli, post


def _task(tid="700", status="captionReady", n=12, mode="advanced", progress=None, msg=""):
    return {"trainingTask": {
        "id": tid, "status": status, "trainingMode": mode, "type": "LORA",
        "parameters": {"title": "Priestess set", "mediaIds": [str(900 + i) for i in range(n)],
                       "category": "character", "baseModelId": T3, "triggerWords": TRIGGER},
        "extra": {"progress": progress, "estimatedTotalTime": 1800000 if progress else None},
        "outputs": {"message": msg}}}


# ---------------------------------------------------------------- core writers

@pytest.mark.parametrize("call", [
    lambda s: core.create_advanced_training_draft(s, T3, "n", TRIGGER, "character"),
    lambda s: core.replace_training_media(s, "7", ["1"]),
    lambda s: core.start_training_captions(s, "7"),
    lambda s: core.save_training_caption(s, "7", "1", "text"),
    lambda s: core.submit_advanced_training(s, "7"),
    lambda s: core.retry_training(s, "7"),
    lambda s: core.publish_training(s, "7", "private", "decline"),
    lambda s: core.make_model_public(s, "7"),
    lambda s: core.join_lora_rebates(s, "7"),
])
def test_every_training_writer_checks_read_only_before_the_network(call, pixai, monkeypatch):
    monkeypatch.setattr(core, "_check_read_only",
                        lambda what: (_ for _ in ()).throw(core.PixAIError("READ_ONLY: " + what)))
    with pytest.raises(core.PixAIError, match="READ_ONLY"):
        call(pixai)
    assert pixai.calls == []


def test_the_advanced_draft_is_the_sites_own_call(pixai):
    pixai.on("createTrainingTask", {"createTrainingTask": {"id": "4242", "refId": None}})
    out = core.create_advanced_training_draft(pixai, T3, "  Priestess set ", "Moonlit Night ELF druid,, in the grove",
                                              "clothing")
    assert out == {"id": "4242"}
    (call,) = pixai.calls_for("createTrainingTask")
    assert call.verb == "mutate"
    assert call.variables == {"input": {
        "type": "LORA", "trainingMode": "advanced", "title": "Priestess set",
        "category": "clothing", "baseModelId": T3,
        "triggerWords": "moonlit night elf druid, in the grove"}}


def test_advanced_offers_tsubaki3_and_tsubaki2_only(pixai):
    assert [b["version_id"] for b in core.advanced_training_bases()] == [T3, T2]
    with pytest.raises(core.PixAIError, match="Tsubaki"):
        core.create_advanced_training_draft(pixai, SDXL, "n", TRIGGER, "character")
    with pytest.raises(core.PixAIError, match="at least 30"):
        core.create_advanced_training_draft(pixai, T3, "n", "too short", "character")
    assert pixai.calls == []


def test_the_start_sends_pixais_default_options_verbatim(pixai):
    """Spend review, findings 3 and 4: PixAI's page sends its defaults (its controls are inert)
    and its quote takes no length, so exactly that body goes, whatever a client asks."""
    pixai.on("/training-task/77/submit", {"trainingTaskId": "77", "status": "waiting"})
    assert core.submit_advanced_training(pixai, "77") == "waiting"
    (call,) = pixai.calls_for("/training-task/77/submit")
    assert call.body == {"trainingOptions": {"trainingSteps": 325, "learningRate": 0.0006,
                                             "rank": 64, "gradAccum": 2}}


def test_a_description_is_1000_characters_at_most(pixai):
    pixai.on("PUT /training-task/7/captions/55", {"mediaId": "55"})
    assert core.save_training_caption(pixai, "7", "55", "  a " + "x" * 996) == "a " + "x" * 996
    with pytest.raises(core.PixAIError, match="1000 characters"):
        core.save_training_caption(pixai, "7", "55", "y" * 1001)
    with pytest.raises(core.PixAIError, match="empty"):
        core.save_training_caption(pixai, "7", "55", "   ")
    (call,) = [c for c in pixai.calls if c.verb == "rest_put"]
    assert call.body == {"text": "a " + "x" * 996}


def test_publish_refuses_rebates_on_a_private_lora_before_sending(pixai):
    with pytest.raises(core.PixAIError, match="public"):
        core.publish_training(pixai, "7", "private", "join")
    assert pixai.calls == []
    pixai.on("/training-task/7/publish", {"trainingTaskId": "7", "modelId": "m1", "versionId": "v1"})
    assert core.publish_training(pixai, "7", "public", "join") == {"model_id": "m1", "version_id": "v1"}
    assert pixai.calls_for("/training-task/7/publish")[0].body == {"visibility": "public",
                                                                   "loraRebate": "join"}


def test_the_eta_is_pixais_own_formula():
    assert core.training_eta(325) == {"min": 27, "max": 35}
    assert core.training_eta(50) == {"min": 4, "max": 5}


def test_a_refusal_and_an_unclear_failure_are_told_apart():
    assert core.definite_refusal(core.PixAIRestError("x", 403, {"code": "INSUFFICIENT_BALANCE"}))
    assert core.definite_refusal(core.PixAIError('GraphQL error: [{"message": "no"}]'))
    assert not core.definite_refusal(core.PixAIRestError("x", 502, {}))
    assert not core.definite_refusal(requests.ReadTimeout("slow"))
    assert not core.definite_refusal(requests.ConnectionError("dropped"))
    assert not core.definite_refusal(core.PixAIError("HTTP 200 non-JSON response"))


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.ok = 200 <= status < 300
        self.text = body if isinstance(body, str) else str(body)

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


class _Sess:
    def __init__(self, resp):
        self.resp = resp

    def get(self, *a, **k):
        return self.resp

    post = put = patch = get


def test_the_one_rest_error_serves_the_training_refusals_and_the_recipe_code():
    """Wave 3's merge seam: wave 2 (recipes) and this lane each added a `_rest_error`, and a
    plain merge kept both -- the later one shadowing the other, so no REST refusal would have
    been a PixAIRestError and definite_refusal would have called every PixAI 4xx on a spend
    "may have started". There is one now, on every /v2 verb, and it carries both vocabularies:
    status/code/data (the training refusals) and http_status/body (the recipe refusals)."""
    import moonglade_backup
    assert len(re.findall(r"^def _rest_error\(", inspect.getsource(moonglade_backup), re.M)) == 1
    body = {"code": "INSUFFICIENT_BALANCE", "data": {"mediaIds": ["5"]}}
    for verb in ("rest_get", "rest_post", "rest_put", "rest_patch"):
        client = core.PixAIClient(_Sess(_Resp(403, body)))
        call = getattr(client, verb)
        with pytest.raises(core.PixAIRestError) as ei:
            call("/training-task/1") if verb == "rest_get" else call("/training-task/1", {})
        e = ei.value
        assert e.status == e.http_status == 403 and e.body == body
        assert e.code == "INSUFFICIENT_BALANCE" and e.data == {"mediaIds": ["5"]}
        assert core.definite_refusal(e)
        assert core.training_error_words(e).startswith("there aren't enough credits")
    client = core.PixAIClient(_Sess(_Resp(502, "<html>bad gateway</html>")))
    with pytest.raises(core.PixAIRestError) as ei:
        client.rest_put("/training-task/1/media", {})
    assert ei.value.body is None and ei.value.code == "" and ei.value.data == {}
    assert not core.definite_refusal(ei.value)
    assert core.training_error_words(ei.value).startswith("REST PUT /training-task/1/media -> 502")


# ------------------------------------------------------------ the draft route

def test_the_draft_route_needs_csrf_and_refuses_read_only_before_anything(tmp_path, pixai,
                                                                          monkeypatch):
    _, post = _app(tmp_path)
    body = {"base_model_id": T3, "title": "Priestess set", "trigger_words": TRIGGER,
            "category": "character"}
    assert post("/api/train/advanced/draft", body, csrf_ok=False).status_code == 400
    reads = []
    monkeypatch.setattr(core, "training_pause", lambda: reads.append("pause"))
    monkeypatch.setattr(core, "_check_read_only",
                        lambda what: (_ for _ in ()).throw(core.PixAIError("READ_ONLY")))
    r = post("/api/train/advanced/draft", body)
    assert r.status_code == 502 and "READ_ONLY" in r.get_json()["error"]
    assert reads == [] and pixai.calls == []


def test_the_draft_route_creates_one_draft_and_a_pause_creates_none(tmp_path, pixai, monkeypatch):
    _, post = _app(tmp_path)
    body = {"base_model_id": T3, "title": "Priestess set", "trigger_words": TRIGGER,
            "category": "character"}
    monkeypatch.setattr(core, "training_pause", lambda: {"resumes_at": ""})
    r = post("/api/train/advanced/draft", body)
    assert r.status_code == 409 and pixai.mutations() == 0
    monkeypatch.setattr(core, "training_pause", lambda: None)
    pixai.on("createTrainingTask", {"createTrainingTask": {"id": "4242"}})
    assert post("/api/train/advanced/draft", body).get_json() == {"id": "4242"}
    assert pixai.mutations("createTrainingTask") == 1


# ------------------------------------------------------ opening only reads

def test_opening_a_draft_only_reads(tmp_path, pixai, monkeypatch):
    cli, _ = _app(tmp_path)
    pixai.on("trainingTask", _task(status="captionReady", n=2))
    pixai.on("/training-task/700/captions", {"items": [
        {"mediaId": "900", "source": "machine", "captionUrl": "https://c/900"},
        {"mediaId": "901", "source": "user", "captionUrl": "https://c/901u",
         "machineCaptionUrl": "https://c/901m", "userCaptionUrl": "https://c/901u"}]})
    pixai.on("/training-task/700/caption-price", {"imageCount": 0, "totalPrice": 0})
    pixai.on("/training-task/700/price", {"price": 100000})
    texts = {"https://c/900": "night elf, moonwell", "https://c/901u": "my words",
             "https://c/901m": "machine words"}
    monkeypatch.setattr(core, "fetch_caption_text", lambda url, limit=0: texts.get(url))
    d = cli.get("/api/train/advanced/700").get_json()
    assert d["task"]["media_ids"] == ["900", "901"] and d["quote"] == 100000
    assert d["captions"]["900"] == {"source": "machine", "text": "night elf, moonwell",
                                    "machine_text": "night elf, moonwell"}
    assert d["captions"]["901"]["machine_text"] == "machine words"
    assert d["caption_max"] == 1000
    assert pixai.mutations() == 0
    assert not [c for c in pixai.calls if c.verb in ("rest_post", "rest_put", "rest_patch")]


# ------------------------------------------------------------- describe (paid)

def _describe_fake(pixai, total=1800, count=12, status="draft", n=12):
    pixai.on("trainingTask", _task(status=status, n=n))
    pixai.on("/training-task/700/caption-price", {"imageCount": count, "totalPrice": total})
    pixai.on("/training-task/700/caption", {"trainingTaskId": "700", "status": "captioning"})


def test_describe_previews_pixais_own_quote(tmp_path, pixai):
    _, post = _app(tmp_path)
    _describe_fake(pixai, total=1800, count=12)
    d = post("/api/train/advanced/700/caption").get_json()
    assert d == {"preview": True, "image_count": 12, "total_price": 1800, "per_image": 150}
    assert not pixai.calls_for("/training-task/700/caption")


def test_describe_goes_once_only_with_the_fresh_total(tmp_path, pixai):
    _, post = _app(tmp_path)
    _describe_fake(pixai, total=1800)
    url = "/api/train/advanced/700/caption"
    assert post(url, {"confirm": True}).status_code == 402                     # nothing named
    assert post(url, {"confirm": True, "accept_credit_cost": True}).status_code == 409   # bare true
    r = post(url, {"confirm": True, "accept_credit_cost": 1200})               # the config's 100 x 12
    assert r.status_code == 409 and "1,800" in r.get_json()["error"]
    assert not pixai.calls_for("/training-task/700/caption")
    d = post(url, {"confirm": True, "accept_credit_cost": 1800}).get_json()
    assert d["started"] and d["charged"] == 1800
    assert len(pixai.calls_for("/training-task/700/caption")) == 1


@pytest.mark.parametrize("status, n, count, code", [
    ("captioning", 12, 12, 409),       # already describing
    ("waiting", 12, 12, 409),          # past that step
    ("draft", 9, 9, 400),              # fewer than 10 images
    ("captionReady", 12, 0, 409),      # nothing left to describe
])
def test_describe_refuses_what_pixai_would_or_what_costs_for_nothing(tmp_path, pixai, status,
                                                                      n, count, code):
    _, post = _app(tmp_path)
    _describe_fake(pixai, total=count * 150, count=count, status=status, n=n)
    r = post("/api/train/advanced/700/caption", {"confirm": True,
                                                 "accept_credit_cost": count * 150})
    assert r.status_code == code
    assert not pixai.calls_for("/training-task/700/caption")


def test_a_paid_confirm_is_refused_while_another_holds_the_run(tmp_path, pixai, monkeypatch):
    """Two tabs, or a phone and a desktop: the second paid request never sends."""
    _, post = _app(tmp_path)
    _describe_fake(pixai, total=1800)
    started, release = threading.Event(), threading.Event()
    real = core.start_training_captions

    def slow(session, tid):
        started.set()
        release.wait(5)
        return real(session, tid)
    monkeypatch.setattr(core, "start_training_captions", slow)
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("a", post(
        "/api/train/advanced/700/caption", {"confirm": True, "accept_credit_cost": 1800})))
    t.start()
    assert started.wait(5)
    second = post("/api/train/advanced/700/caption", {"confirm": True, "accept_credit_cost": 1800})
    release.set()
    t.join(5)
    assert second.status_code == 409 and "Nothing was sent" in second.get_json()["error"]
    assert out["a"].get_json()["started"]
    assert len(pixai.calls_for("/training-task/700/caption")) == 1


def test_describe_under_read_only_reads_nothing(tmp_path, pixai, monkeypatch):
    _, post = _app(tmp_path)
    monkeypatch.setattr(core, "_check_read_only",
                        lambda what: (_ for _ in ()).throw(core.PixAIError("READ_ONLY")))
    r = post("/api/train/advanced/700/caption", {"confirm": True, "accept_credit_cost": 1800})
    assert r.status_code == 502 and pixai.calls == []


# --------------------------------------------------------- the set, the edits

def test_the_set_refuses_an_image_pixai_would_reject_by_name(tmp_path, pixai):
    rows = [_row(media_id=str(i), filename="a%d.png" % i, width="1024", height="1024")
            for i in range(11)] + [_row(media_id="99", filename="s.png", width="400", height="400")]
    _, post = _app(tmp_path, rows)
    r = post("/api/train/advanced/700/media", {"media_ids": [str(i) for i in range(11)] + ["99"]})
    assert r.status_code == 400 and r.get_json()["rejected_ids"] == ["99"]
    assert pixai.calls == []
    pixai.on("PUT /training-task/700/media", lambda call: {"trainingTaskId": "700",
                                                           "mediaIds": call.body["mediaIds"]})
    d = post("/api/train/advanced/700/media", {"media_ids": ["1", "2", "1", "3"]}).get_json()
    assert d["media_ids"] == ["1", "2", "3"]                     # de-duplicated, in order


def test_pixais_own_image_refusal_names_its_images(tmp_path, pixai):
    _, post = _app(tmp_path)
    pixai.fail("PUT /training-task/700/media", core.PixAIRestError(
        "REST PUT -> 400", 400, {"code": "TRAINING_IMAGE_REJECTED",
                                 "data": {"mediaIds": ["5"], "minWidth": 512, "minHeight": 512,
                                          "maxAspectRatio": 3}}))
    r = post("/api/train/advanced/700/media", {"media_ids": ["5", "6"]})
    assert r.status_code == 400 and r.get_json()["rejected_ids"] == ["5"]
    assert "won't train" in r.get_json()["error"]


def test_a_description_save_is_bounded_and_one_put(tmp_path, pixai):
    _, post = _app(tmp_path)
    assert post("/api/train/advanced/700/captions/55", {"text": "z" * 1001}).status_code == 400
    pixai.on("PUT /training-task/700/captions/55", {"mediaId": "55"})
    assert post("/api/train/advanced/700/captions/55", {"text": " moonlit "}).get_json() == {
        "text": "moonlit"}
    assert len([c for c in pixai.calls if c.verb == "rest_put"]) == 1


# ------------------------------------------------------------- start (paid)

def _start_fake(pixai, price=100000, described=12, n=12):
    pixai.on("trainingTask", _task(status="captionReady", n=n))
    pixai.on("/training-task/700/captions", {"items": [
        {"mediaId": str(900 + i), "source": "machine", "captionUrl": "https://c"}
        for i in range(described)]})
    pixai.on("/training-task/700/price", {"price": price})
    pixai.on("/training-task/700/submit", {"trainingTaskId": "700", "status": "waiting"})
    pixai.on("me", {"me": {"id": "1", "membership": None, "quotaAmount": 0}})


def test_start_refuses_until_every_image_is_described(tmp_path, pixai):
    _, post = _app(tmp_path)
    _start_fake(pixai, described=10)
    r = post("/api/train/advanced/700/submit", {"confirm": True, "accept_credit_cost": 100000})
    assert r.status_code == 409 and "2 remaining images" in r.get_json()["error"]
    assert not pixai.calls_for("/training-task/700/submit")


def test_start_goes_once_with_the_fresh_quote(tmp_path, pixai):
    _, post = _app(tmp_path)
    _start_fake(pixai, price=100000)
    url = "/api/train/advanced/700/submit"
    prev = post(url).get_json()
    assert prev["price"] == 100000 and prev["eta"] == {"min": 27, "max": 35}
    assert post(url, {"confirm": True, "accept_credit_cost": True}).status_code == 409
    assert post(url, {"confirm": True, "accept_credit_cost": 70000}).status_code == 409
    assert not pixai.calls_for("/training-task/700/submit")
    # a client cannot change the options: anything it sends is ignored, the defaults go
    d = post(url, {"confirm": True, "accept_credit_cost": 100000,
                   "training_steps": 800, "trainingOptions": {"trainingSteps": 800}}).get_json()
    assert d["submitted"] is True
    (call,) = pixai.calls_for("/training-task/700/submit")
    assert call.body["trainingOptions"]["trainingSteps"] == 325
    assert "kaisuukenId" not in call.body                     # PixAI's page attaches no card


# ------------------------------------------------------------- retry (paid, a new run)

def _retry_fake(pixai, price=100000):
    pixai.on("trainingTask", _task(tid="800", status="failed", msg="out of memory"))
    pixai.on("/training-task/800/price", {"price": price})


def test_a_failed_run_is_retried_once_and_the_guard_survives_a_restart(tmp_path, pixai):
    _, post = _app(tmp_path)
    _retry_fake(pixai)
    pixai.on("/training-task/800/retry", {"trainingTaskId": "801", "originTaskId": "800",
                                          "status": "waiting"})
    url = "/api/train/runs/800/retry"
    assert post(url).get_json()["price"] == 100000
    assert post(url, {"confirm": True, "accept_credit_cost": True}).status_code == 409
    d = post(url, {"confirm": True, "accept_credit_cost": 100000}).get_json()
    assert d == {"retried": True, "id": "801", "price": 100000}
    r = post(url, {"confirm": True, "accept_credit_cost": 100000})
    assert r.status_code == 409 and "retried already" in r.get_json()["error"]
    _, post2 = _app(tmp_path)                                  # a restart: a new app
    assert post2(url, {"confirm": True, "accept_credit_cost": 100000}).status_code == 409
    assert len(pixai.calls_for("/training-task/800/retry")) == 1


def test_an_unclear_retry_failure_keeps_the_guard_and_a_refusal_clears_it(tmp_path, pixai):
    _, post = _app(tmp_path)
    _retry_fake(pixai)
    url = "/api/train/runs/800/retry"
    pixai.fail("/training-task/800/retry", requests.ReadTimeout("no answer"))
    r = post(url, {"confirm": True, "accept_credit_cost": 100000})
    assert r.status_code == 502 and r.get_json()["maybe_started"] is True
    assert post(url, {"confirm": True, "accept_credit_cost": 100000}).status_code == 409
    assert len(pixai.calls_for("/training-task/800/retry")) == 1
    # a definite refusal leaves it free to try again
    TrainGuard(tmp_path / "train_guard.json").retry_resolve("800", "refused")
    pixai.fail("/training-task/800/retry", core.PixAIRestError(
        "x", 403, {"code": "INSUFFICIENT_BALANCE"}))
    r = post(url, {"confirm": True, "accept_credit_cost": 100000})
    assert r.status_code == 403 and "credits" in r.get_json()["error"]
    assert TrainGuard(tmp_path / "train_guard.json").retry_state("800") is None


def test_only_a_failed_advanced_run_can_be_retried(tmp_path, pixai):
    _, post = _app(tmp_path)
    pixai.on("trainingTask", _task(tid="800", status="running"))
    r = post("/api/train/runs/800/retry", {"confirm": True, "accept_credit_cost": 1})
    assert r.status_code == 409 and not pixai.calls_for("/training-task/800/retry")


# ------------------------------------------------------------- publish

def test_publish_needs_every_consequence_ticked(tmp_path, pixai):
    _, post = _app(tmp_path)
    pixai.on("/training-task/completed", {"tasks": [
        {"id": "900", "title": "Moonwell style", "baseModelId": T3, "mediaCount": 40,
         "modelId": None, "completedAt": "2026-09-28T00:00:00Z"}]})
    pixai.on("/training-task/900/publish", {"trainingTaskId": "900", "modelId": "m9",
                                            "versionId": "v9"})
    url = "/api/train/runs/900/publish"
    assert post(url, {"visibility": "public", "acknowledged": ["no_delete"]}).status_code == 400
    assert post(url, {"visibility": "private", "rebate": "join",
                      "acknowledged": ["no_delete"]}).status_code == 400
    assert not pixai.calls_for("/training-task/900/publish")
    d = post(url, {"visibility": "public", "rebate": "join",
                   "acknowledged": ["no_private", "no_delete"]}).get_json()
    assert d["published"] and d["model_id"] == "m9"
    assert pixai.calls_for("/training-task/900/publish")[0].body == {
        "visibility": "public", "loraRebate": "join"}


def test_a_published_run_is_not_published_twice(tmp_path, pixai):
    _, post = _app(tmp_path)
    pixai.on("/training-task/completed", {"tasks": [
        {"id": "900", "title": "x", "baseModelId": T3, "mediaCount": 40, "modelId": "m9",
         "completedAt": "2026-09-28T00:00:00Z"}]})
    r = post("/api/train/runs/900/publish", {"visibility": "private",
                                             "acknowledged": ["no_delete"]})
    assert r.status_code == 409 and not pixai.calls_for("/training-task/900/publish")


def test_make_public_is_the_sites_two_calls(tmp_path, pixai):
    _, post = _app(tmp_path)
    pixai.user_id = "u1"
    pixai.on("generationModel", {"generationModel": {"id": "9009", "authorId": "u1",
                                                     "isPrivate": True, "type": "LORA"}})
    pixai.on("upsertGenerationModel", {"upsertGenerationModel": {"id": "9009", "isPrivate": False}})
    pixai.on("/generation-model/9009/lora-rebate-eligibility", {
        "featureStatus": "enabled", "eligibility": "decline",
        "allowedTargetEligibilities": ["accept"]})
    pixai.on("PATCH /generation-model/9009/lora-rebate-eligibility", {"eligibility": "accept"})
    url = "/api/train/models/9009/make-public"
    r = post(url, {"rebate": "join", "acknowledged": []})
    assert r.status_code == 400 and "can't go back to private" in r.get_json()["error"]
    assert pixai.mutations() == 0
    d = post(url, {"rebate": "join", "acknowledged": ["no_private"]}).get_json()
    assert d == {"public": True, "rebate": True, "note": ""}
    (up,) = pixai.calls_for("upsertGenerationModel")
    assert up.variables == {"id": "9009", "input": {"isPrivate": False}}
    (patch,) = [c for c in pixai.calls if c.verb == "rest_patch"]
    assert patch.body == {"eligibility": "accept"}


# --------------------------------------------------------- runs, datasets

def _loras(pixai, nodes):
    pixai.on("generationModels", {"generationModels": {
        "pageInfo": {"hasPreviousPage": False, "startCursor": None},
        "edges": [{"node": n} for n in nodes]}})


def _basic_node(mid, tid, status, mode="standard", ids=12, progress=None, private=True):
    return {"id": mid, "title": "LoRA " + mid, "isPrivate": private, "visibilityType": "",
            "createdAt": "2026-09-2%sT00:00:00Z" % mid[-1], "mediaId": "5",
            "latestAvailableVersion": {"id": "v" + mid},
            "trainingTask": _task(tid=tid, status=status, mode=mode, n=ids,
                                  progress=progress)["trainingTask"]}


def test_runs_merge_both_flows_with_progress_and_one_action_each(tmp_path, pixai):
    cli, _ = _app(tmp_path)
    pixai.on("/training-task/in-progress", {"tasks": [
        {"id": "701", "status": "draft", "title": "Priestess set", "baseModelId": T3,
         "mediaCount": 24, "updatedAt": "2026-09-28T02:00:00Z"},
        {"id": "702", "status": "running", "title": "Nelnamara v3", "baseModelId": T3,
         "mediaCount": 38, "updatedAt": "2026-09-28T03:00:00Z"},
        {"id": "703", "status": "failed", "title": "Old druid", "baseModelId": T3,
         "mediaCount": 50, "updatedAt": "2026-09-27T01:00:00Z"}]})
    pixai.on("/training-task/completed", {"tasks": []})
    _loras(pixai, [_basic_node("m1", "501", "completed"),
                   _basic_node("m2", "502", "running", progress=40)])
    pixai.on("trainingTask", lambda call: _task(
        tid=call.variables["id"],
        status="running" if call.variables["id"] == "702" else "failed",
        progress=62 if call.variables["id"] == "702" else None,
        msg="out of memory"))
    d = cli.get("/api/train/runs").get_json()
    by = {r["id"]: r for r in d["runs"]}
    assert by["702"]["progress"] == 62 and by["702"]["eta_left_ms"] == int(1800000 * .38)
    assert by["703"]["status"] == "failed" and by["703"]["reason"] == "out of memory"
    assert by["701"]["step"] == "descriptions"
    assert by["501"]["mode"] == "basic" and by["501"]["status"] == "done"
    assert by["501"]["model_id"] == "m1" and by["501"]["visibility"] == "private"
    assert by["502"]["progress"] == 40
    assert [r["id"] for r in d["running"]] == ["702", "502"]
    assert d["runs"][0]["status"] == "running"
    assert pixai.mutations() == 0


def test_a_retried_run_carries_its_guard(tmp_path, pixai):
    TrainGuard(tmp_path / "train_guard.json").retry_resolve("703", "done", "704")
    cli, _ = _app(tmp_path)
    pixai.on("/training-task/in-progress", {"tasks": [
        {"id": "703", "status": "failed", "title": "x", "baseModelId": T3, "mediaCount": 10,
         "updatedAt": "2026-09-27T01:00:00Z"}]})
    pixai.on("/training-task/completed", {"tasks": []})
    _loras(pixai, [])
    pixai.on("trainingTask", _task(tid="703", status="failed"))
    r = cli.get("/api/train/runs").get_json()["runs"][0]
    assert r["retry"] == {"state": "done", "new_id": "704"}


def test_datasets_are_finished_basic_runs_only(tmp_path, pixai):
    cli, _ = _app(tmp_path)
    _loras(pixai, [_basic_node("m1", "501", "completed", ids=30),
                   _basic_node("m2", "502", "failed"),
                   _basic_node("m3", "503", "completed", mode="advanced")])
    d = cli.get("/api/train/datasets").get_json()["datasets"]
    assert [x["task_id"] for x in d] == ["501"] and d[0]["count"] == 30
    assert d[0]["trigger_words"] == TRIGGER and d[0]["category"] == "character"


# ------------------------------------------------ Basic: a reused set, double starts

def _basic_client(tmp_path, monkeypatch, pixai, quota=0):
    _, post = _app(tmp_path)
    monkeypatch.setattr(core, "training_free_quota", lambda s: quota)
    monkeypatch.setattr(core, "match_training_kaisuuken", lambda *a, **k: None)
    pixai.on("createTrainingTask", {"createTrainingTask": {"id": "trn1", "refId": "m7"}})
    return post


_REUSED = [str(900 + i) for i in range(12)]
_BASIC = {"base_model_id": T3, "media_ids": _REUSED, "title": "Tania v2",
          "trigger_words": TRIGGER, "category": "character", "dataset_task_id": "501"}


def test_a_whole_earlier_set_is_priced_and_sent_as_a_reuse(tmp_path, monkeypatch, pixai):
    post = _basic_client(tmp_path, monkeypatch, pixai)
    _loras(pixai, [_basic_node("m1", "501", "completed", ids=12)])
    prev = post("/api/train/submit", _BASIC).get_json()
    assert prev["reuse"] is True and prev["price"] == 70000 and prev["list_price"] == 100000
    assert prev["price_reason"] == "reusing a dataset"
    d = post("/api/train/submit", dict(_BASIC, confirm=True, accept_credit_cost=70000)).get_json()
    assert d["submitted"] and d["reuse"]
    (call,) = pixai.calls_for("createTrainingTask")
    assert call.variables["input"]["mediaIds"] == []
    assert call.variables["input"]["trainingTaskId"] == "501"


@pytest.mark.parametrize("node, ids", [
    (lambda: _basic_node("m1", "501", "completed", ids=12), _REUSED[:11]),        # one removed
    (lambda: _basic_node("m1", "501", "completed", ids=12), _REUSED + ["1"]),     # one added
    (lambda: _basic_node("m1", "501", "failed", ids=12), _REUSED),                # a failed run
    (lambda: _basic_node("m1", "501", "completed", mode="advanced", ids=12), _REUSED),
    (lambda: _basic_node("m1", "999", "completed", ids=12), _REUSED),             # not found
])
def test_anything_but_a_whole_finished_basic_set_is_a_fresh_run(tmp_path, monkeypatch, pixai,
                                                                node, ids):
    post = _basic_client(tmp_path, monkeypatch, pixai)
    _loras(pixai, [node()])
    prev = post("/api/train/submit", dict(_BASIC, media_ids=ids)).get_json()
    assert prev["reuse"] is False and prev["price"] == 100000
    d = post("/api/train/submit", dict(_BASIC, media_ids=ids, confirm=True,
                                       accept_credit_cost=100000)).get_json()
    assert d["submitted"]
    (call,) = pixai.calls_for("createTrainingTask")
    assert call.variables["input"]["mediaIds"] == ids
    assert "trainingTaskId" not in call.variables["input"]


def test_read_only_refuses_a_basic_confirm_before_the_reuse_read(tmp_path, monkeypatch, pixai):
    post = _basic_client(tmp_path, monkeypatch, pixai)
    monkeypatch.setattr(core, "_check_read_only",
                        lambda what: (_ for _ in ()).throw(core.PixAIError("READ_ONLY")))
    r = post("/api/train/submit", dict(_BASIC, confirm=True, accept_credit_cost=70000))
    assert r.status_code == 502 and pixai.calls == []


def test_the_same_basic_start_twice_is_one_run(tmp_path, monkeypatch, pixai):
    post = _basic_client(tmp_path, monkeypatch, pixai)
    _loras(pixai, [])
    body = dict(_BASIC, dataset_task_id="", confirm=True, accept_credit_cost=100000)
    assert post("/api/train/submit", body).get_json()["submitted"]
    r = post("/api/train/submit", body)
    assert r.status_code == 409 and "just started" in r.get_json()["error"]
    assert pixai.mutations("createTrainingTask") == 1


def test_an_unclear_basic_failure_says_it_may_have_started_and_blocks_a_resend(
        tmp_path, monkeypatch, pixai):
    post = _basic_client(tmp_path, monkeypatch, pixai)
    _loras(pixai, [])
    pixai.fail("createTrainingTask", requests.ReadTimeout("no answer"))
    body = dict(_BASIC, dataset_task_id="", confirm=True, accept_credit_cost=100000)
    r = post("/api/train/submit", body)
    assert r.status_code == 502 and r.get_json()["maybe_started"] is True
    r = post("/api/train/submit", body)
    assert r.status_code == 409 and "may have gone through" in r.get_json()["error"]
    _, post2 = _app(tmp_path)                                   # a restart keeps it
    monkeypatch.setattr(core, "training_free_quota", lambda s: 0)
    assert post2("/api/train/submit", body).status_code == 409
    assert pixai.mutations("createTrainingTask") == 1


def test_a_definite_basic_refusal_leaves_the_start_free_to_try_again(tmp_path, monkeypatch,
                                                                     pixai):
    post = _basic_client(tmp_path, monkeypatch, pixai)
    _loras(pixai, [])
    pixai.fail("createTrainingTask", core.PixAIError('GraphQL error: [{"message": "nope"}]'))
    body = dict(_BASIC, dataset_task_id="", confirm=True, accept_credit_cost=100000)
    assert post("/api/train/submit", body).status_code == 502
    pixai.on("createTrainingTask", {"createTrainingTask": {"id": "trn2"}})
    assert post("/api/train/submit", body).get_json()["submitted"]


def test_two_basic_confirms_at_once_send_one(tmp_path, monkeypatch, pixai):
    post = _basic_client(tmp_path, monkeypatch, pixai)
    _loras(pixai, [])
    started, release = threading.Event(), threading.Event()
    real = core.submit_training

    def slow(*a, **k):
        started.set()
        release.wait(5)
        return real(*a, **k)
    monkeypatch.setattr(core, "submit_training", slow)
    body = dict(_BASIC, dataset_task_id="", confirm=True, accept_credit_cost=100000)
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("a", post("/api/train/submit", body)))
    t.start()
    assert started.wait(5)
    second = post("/api/train/submit", dict(body, title="A different run"))
    release.set()
    t.join(5)
    assert second.status_code == 409 and out["a"].get_json()["submitted"]
    assert pixai.mutations("createTrainingTask") == 1


# ------------------------------- waves 2+3 spend review: F1, F2, F4, F6

def _fake_for(what, pixai):
    (_start_fake if what == "submit" else _describe_fake)(pixai)


_PAID = {"submit": ("/api/train/advanced/700/submit", "/training-task/700/submit", 100000),
         "caption": ("/api/train/advanced/700/caption", "/training-task/700/caption", 1800)}


@pytest.mark.parametrize("what", ["submit", "caption"])
def test_an_unclear_paid_advanced_failure_arms_a_guard_so_a_second_confirm_sends_nothing(
        tmp_path, pixai, what):
    """F1: a read timeout on Start or Describe may have reached PixAI and charged. The answer
    says it may have started, and the next confirm is refused on disk -- through a restart --
    until the task's status moves on or the window lapses. Only one paid POST ever goes."""
    url, path, amount = _PAID[what]
    _, post = _app(tmp_path)
    _fake_for(what, pixai)
    pixai.fail(path, requests.ReadTimeout("no answer"))
    body = {"confirm": True, "accept_credit_cost": amount}
    r = post(url, body)
    assert r.status_code == 502 and r.get_json()["maybe_started"] is True
    r = post(url, body)
    assert r.status_code == 409 and r.get_json()["maybe_started"] is True
    assert "Nothing was sent" in r.get_json()["error"]
    _, post2 = _app(tmp_path)                                  # a restart keeps it
    assert post2(url, body).status_code == 409
    assert len(pixai.calls_for(path)) == 1
    # PixAI's status moved on: the guard clears, and the route's own status check answers.
    pixai.on("trainingTask", _task(status="waiting" if what == "submit" else "captioning"))
    r = post2(url, body)
    assert r.status_code == 409 and not r.get_json().get("maybe_started")
    assert "paid" in (tmp_path / "train_guard.json").read_text()
    assert "%s:700" % what not in (tmp_path / "train_guard.json").read_text()
    assert len(pixai.calls_for(path)) == 1


@pytest.mark.parametrize("what", ["submit", "caption"])
def test_a_definite_paid_advanced_refusal_does_not_arm_the_guard(tmp_path, pixai, what):
    """F1: a 4xx is PixAI saying no -- nothing was created or charged, so the next confirm
    is free to go."""
    url, path, amount = _PAID[what]
    _, post = _app(tmp_path)
    _fake_for(what, pixai)
    pixai.fail(path, core.PixAIRestError("x", 403, {"code": "INSUFFICIENT_BALANCE"}))
    body = {"confirm": True, "accept_credit_cost": amount}
    r = post(url, body)
    assert r.status_code == 403 and not r.get_json().get("maybe_started")
    _fake_for(what, pixai)
    r = post(url, body)
    assert r.status_code == 200, r.get_json()
    assert len(pixai.calls_for(path)) == 2


def test_the_paid_guard_lapses_after_its_window_and_only_on_the_same_status(tmp_path):
    g = TrainGuard(tmp_path / "train_guard.json")
    g.paid_arm("submit", "700", "captionReady", now=1000.0)
    g.paid_resolve("submit", "700", "ambiguous", now=1000.0)
    assert g.paid_blocked("submit", "700", "captionReady", now=1000.0 + 60)
    assert not g.paid_blocked("caption", "700", "captionReady", now=1000.0 + 60)
    assert not g.paid_blocked("submit", "700", "captionReady",
                              now=1000.0 + TrainGuard.AMBIGUOUS_WINDOW + 1)
    g.paid_arm("submit", "700", "captionReady", now=2000.0)      # a crash mid-POST: "armed"
    assert g.paid_blocked("submit", "700", "captionReady", now=2001.0)
    g.paid_resolve("submit", "700", "done", now=2001.0)
    assert not g.paid_blocked("submit", "700", "captionReady", now=2002.0)


def _graphql_error(body):
    """The error the REAL transport raises for `body` (PixAIClient._graphql_post)."""
    client = core.PixAIClient(_Sess(_Resp(200, body)))
    with pytest.raises(core.PixAIError) as ei:
        client.mutate("mutation { createTrainingTask(input: {}) { id } }", {})
    return ei.value


def test_a_graphql_answer_with_data_and_errors_is_not_a_definite_refusal():
    """F2: GraphQL can answer `errors` beside a resolved `data` -- the run was created (and
    maybe charged) and something under it failed. That is not PixAI saying no."""
    partial = _graphql_error({"data": {"createTrainingTask": {"id": "trn9"}},
                              "errors": [{"message": "a nested field failed"}]})
    assert partial.graphql_data == {"createTrainingTask": {"id": "trn9"}}
    assert not core.definite_refusal(partial)
    for data in ({"createTrainingTask": None}, None):
        refused = _graphql_error({"data": data, "errors": [{"message": "nope"}]})
        assert core.definite_refusal(refused)


def test_a_partial_basic_success_keeps_the_double_start_guard(tmp_path, monkeypatch, pixai):
    """F2: the Basic start's guard stays armed on a data+errors answer, so the second
    confirm is refused (409) and only one createTrainingTask goes."""
    post = _basic_client(tmp_path, monkeypatch, pixai)
    _loras(pixai, [])
    pixai.fail("createTrainingTask", _graphql_error(
        {"data": {"createTrainingTask": {"id": "trn9"}},
         "errors": [{"message": "a nested field failed"}]}))
    body = dict(_BASIC, dataset_task_id="", confirm=True, accept_credit_cost=100000)
    r = post("/api/train/submit", body)
    assert r.status_code == 502 and r.get_json()["maybe_started"] is True
    r = post("/api/train/submit", body)
    assert r.status_code == 409 and "may have gone through" in r.get_json()["error"]
    assert pixai.mutations("createTrainingTask") == 1


def test_a_basic_refusal_before_the_network_is_definite_and_says_nothing_started(
        tmp_path, monkeypatch, pixai):
    """F4: READ_ONLY switched on between the route's own check and submit_training's is
    refused before anything is sent -- a LocalRefusal: no "may have started", no armed guard,
    and the next confirm (the switch off again) goes."""
    post = _basic_client(tmp_path, monkeypatch, pixai)
    _loras(pixai, [])
    real = core._check_read_only
    seen = {"n": 0}

    def second_call_refuses(what):
        seen["n"] += 1
        if seen["n"] == 2:
            raise core.PixAIError("READ_ONLY is set")
        return real(what)
    monkeypatch.setattr(core, "_check_read_only", second_call_refuses)
    body = dict(_BASIC, dataset_task_id="", confirm=True, accept_credit_cost=100000)
    r = post("/api/train/submit", body)
    assert r.status_code == 502 and not r.get_json().get("maybe_started")
    assert "READ_ONLY" in r.get_json()["error"]
    assert pixai.mutations("createTrainingTask") == 0
    assert post("/api/train/submit", body).get_json()["submitted"]
    assert pixai.mutations("createTrainingTask") == 1


def test_submit_training_validates_against_the_callers_config(pixai, monkeypatch):
    """F4: the route's config, not a re-read, so the confirm validates what was priced; a
    validation refusal is a LocalRefusal and sends nothing."""
    cfg = core.training_config()
    monkeypatch.setattr(core, "training_config",
                        lambda: (_ for _ in ()).throw(AssertionError("re-read the config")))
    pixai.on("createTrainingTask", {"createTrainingTask": {"id": "trn1"}})
    session = core._make_session()
    out = core.submit_training(session, T3, _REUSED, "Tania v2", TRIGGER, "character",
                               config=cfg)
    assert out == {"id": "trn1"}
    with pytest.raises(core.LocalRefusal):
        core.submit_training(session, T3, _REUSED, "Tania v2", "short", "character",
                             config=cfg)
    assert pixai.mutations("createTrainingTask") == 1


@pytest.mark.parametrize("accepted, goes", [(1800.5, False), (1800.9, False), (1799.9, False),
                                            (1800.0, True)])
def test_a_fractional_acknowledgement_is_never_the_quote(tmp_path, pixai, accepted, goes):
    """F6: int() would truncate 1800.9 onto a quote of 1800; the amount must be the number."""
    _, post = _app(tmp_path)
    _describe_fake(pixai, total=1800)
    r = post("/api/train/advanced/700/caption", {"confirm": True, "accept_credit_cost": accepted})
    assert (r.status_code == 200) is goes
    assert len(pixai.calls_for("/training-task/700/caption")) == (1 if goes else 0)
