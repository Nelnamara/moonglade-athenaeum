"""The one payload road: /api/price and every create route build ONE GenerationRequest.

These drive `core.build_request` / `core.price` / `core.submit` DIRECTLY -- the interface
is the test surface. The route tests (test_web_pick, test_video_gen, test_kaisuuken,
test_fix, test_enhance, test_upscale_boosters, test_gen_surface) still pin what each route
does with the result; what is pinned HERE is the property the road exists for and that no
single route can prove on its own:

  a quote and a spend read the SAME parameters object, so a cost badge cannot
  describe a job other than the one about to be paid for.

Before this, /api/price reached its params through the gallery's own `_params_and_nocard`
and the five create routes each reached theirs by a road of their own -- five chances for
the two to drift, on a path where drifting means charging for something else.

No network: every PixAI call is stubbed, and the READ_ONLY tests assert the refusal lands
BEFORE any of them is reachable.
"""
import pytest

import moonglade_backup as core


# --- the table ---------------------------------------------------------------
# One row per mode build_request supports. `payload` is a complete, buildable request;
# `missing` is the same road with the one thing it cannot do without taken away.
#
#   priceable  -- False only for enhance: a panelplugin task is priced by its workflow id,
#                 which is deliberately NOT in _PRICE_SCALARS, so pricing the workflow-less
#                 shape that survives the allowlist returns a confident WRONG number. No
#                 number is the honest answer, and price() must not reach the endpoint.
#   mutation   -- the ONE call this road's submit makes.
MODES = [
    ("image", {"version_id": "V1", "prompt": "a moonwell", "width": 512, "height": 512},
     {}, "pick a model", True, "submit_generation"),
    ("edit", {"mode": "edit", "source": "99", "instruction": "make it night"},
     {"mode": "edit"}, "pick an image to edit", True, "submit_generation"),
    ("fix", {"mode": "fix", "source": "99",
             "boxes": [{"x": 1, "y": 2, "width": 30, "height": 40, "tag": "hand"}]},
     {"mode": "fix"}, "pick an image to fix", True, "submit_fixer"),
    ("video", {"mode": "I2V", "images": ["77"], "prompt": "a slow pan", "duration": 5},
     {"mode": "I2V", "images": []}, "pick a source image", True, "submit_generation"),
    ("enhance", {"mode": "enhance", "source": "55", "workflow_id": "1794855217667308480"},
     {"mode": "enhance"}, "pick an image first", False, "submit_generation"),
]
_IDS = [row[0] for row in MODES]

CARD = {"id": "card-1", "name": "Tsubaki.2", "total": 3, "consumeAmount": 1,
        "covered": True, "templateId": "tpl-1", "expiresAt": "2026-12-31T00:00:00Z"}


class FakeSession:
    """Stands in for a requests.Session. Nothing may actually reach it -- if a test ever
    sees `used`, a real network call escaped the stubs."""

    def __init__(self):
        self.used = []

    def request(self, *a, **k):                              # pragma: no cover - guard
        self.used.append((a, k))
        raise AssertionError("a real network call escaped the stubs")


@pytest.fixture
def road(monkeypatch):
    """Records what each PixAI call is handed, so a test can compare the object the price
    saw with the object the submit sent."""
    seen = {"priced": [], "matched": [], "submitted": [], "fixed": []}

    monkeypatch.setattr(core, "_session_for_create", lambda s: s)
    monkeypatch.setattr(core, "price_task",
                        lambda s, params: seen["priced"].append(params) or 1200)
    monkeypatch.setattr(core, "match_kaisuuken",
                        lambda s, params, **k: seen["matched"].append(params) or dict(CARD))
    monkeypatch.setattr(core, "submit_generation",
                        lambda s, params: seen["submitted"].append(params) or "task-1")
    monkeypatch.setattr(core, "submit_fixer",
                        lambda s, mid, boxes: seen["fixed"].append((mid, boxes)) or "task-2")
    # _apply_kaisuuken is deliberately NOT stubbed: attaching the card is the one legal
    # difference between the priced dict and the submitted one, and the test asserts it is
    # the only one.
    return seen


def _build(payload):
    return core.build_request(payload, resolve=core.RequestResolver())


# --- (a) one object, quoted and spent ----------------------------------------

@pytest.mark.parametrize("mode,payload,_m,_n,priceable,mutation", MODES, ids=_IDS)
def test_price_and_submit_read_the_same_parameters_object(
        mode, payload, _m, _n, priceable, mutation, road):
    """THE property. One request, priced and then submitted: the dict handed to the
    pricing endpoint and the dict handed to the mutation are the SAME OBJECT, not two
    builds that happen to agree. Identity is the assertion on purpose -- deep equality
    would still pass if some future caller rebuilt the shape from the payload a second
    time, which is exactly the seam this closed."""
    sess = FakeSession()
    req = _build(payload)
    assert req.parameters is not None, "the table's payload should be buildable"

    quoted = core.price(sess, req)
    core.submit(sess, req)

    if mutation == "submit_fixer":
        # A Fix does not submit `parameters` at all -- POST /v2/task/fixer takes
        # {mediaId, boxes}. Same request, so the boxes that were PRICED are the boxes
        # that go out: build_fixer_price_parameters synthesizes the chat.fixer shape from
        # req.media_id/req.boxes, and submit sends those two directly.
        (sent_media, sent_boxes), = road["fixed"]
        assert sent_media == req.media_id and sent_boxes is req.boxes
        priced, = road["priced"]
        assert priced is req.parameters
        assert priced["mediaId"] == sent_media
        assert priced["chat"]["fixer"]["boxes"][0]["tag"] == "hand"
        return

    submitted, = road["submitted"]
    assert submitted is req.parameters, (
        "{}: the mutation was handed a different dict than the price".format(mode))
    if priceable:
        priced, = road["priced"]
        assert priced is submitted, (
            "{}: the price and the submit did not share one object".format(mode))
    else:
        assert not road["priced"], (
            "{}: this mode must never reach the pricing endpoint".format(mode))


@pytest.mark.parametrize("mode,payload,_m,_n,priceable,mutation", MODES, ids=_IDS)
def test_the_card_is_the_only_thing_submit_adds_to_the_quoted_shape(
        mode, payload, _m, _n, priceable, mutation, road):
    """Deep-equality half of the same property: snapshot the shape at quote time, submit,
    then compare field by field with the attached kaisuukenId removed. Anything else that
    moved between the quote and the spend is a badge quoting the wrong job."""
    sess = FakeSession()
    req = _build(payload)
    before = dict(req.parameters)
    core.price(sess, req)
    core.submit(sess, req)
    after = dict(req.parameters)
    after.pop("kaisuukenId", None)
    assert after == before, "{}: the submit shape drifted from the quoted shape".format(mode)


def test_a_covering_card_is_attached_on_submit_and_reported_by_price():
    """The two halves of the free card agree because they read one predicate: price
    reports card_covers(best), submit attaches that same card's id."""
    sess = FakeSession()
    seen = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(core, "_session_for_create", lambda s: s)
        mp.setattr(core, "price_task", lambda s, params: 1200)
        mp.setattr(core, "match_kaisuuken", lambda s, params, **k: dict(CARD))
        mp.setattr(core, "submit_generation",
                   lambda s, params: seen.update(params=params) or "t")
        req = _build({"version_id": "V1", "prompt": "x"})
        quoted = core.price(sess, req)
        core.submit(sess, req)
    assert quoted["free"] is True and quoted["cards_held"] == 3
    assert seen["params"]["kaisuukenId"] == "card-1"


def test_price_says_paid_when_the_card_is_short_and_submit_attaches_nothing():
    """issue #15: a MATCH is not coverage. A multi-ticket job against too few held tickets
    is paid at the full price on both surfaces -- `free` is card_covers(best), never
    bool(best), and the submit attaches no id."""
    short = dict(CARD, total=1, consumeAmount=3, covered=False)
    sess = FakeSession()
    seen = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(core, "_session_for_create", lambda s: s)
        mp.setattr(core, "price_task", lambda s, params: 27500)
        mp.setattr(core, "match_kaisuuken", lambda s, params, **k: dict(short))
        mp.setattr(core, "submit_generation",
                   lambda s, params: seen.update(params=params) or "t")
        req = _build({"mode": "R2V", "images": ["77"], "prompt": "x"})
        quoted = core.price(sess, req)
        core.submit(sess, req)
    assert quoted["free"] is False and quoted["card_short"] is True
    assert quoted["cards_needed"] == 3 and quoted["cards_held"] == 1
    assert "kaisuukenId" not in seen["params"]


# --- (b) READ_ONLY refuses before any network call ---------------------------

@pytest.mark.parametrize("mode,payload,_m,_n,_p,_mut", MODES, ids=_IDS)
def test_submit_refuses_under_read_only_before_any_network_call(
        mode, payload, _m, _n, _p, _mut, monkeypatch):
    """READ_ONLY is a user-facing contract, and it has to be checked BEFORE the free-card
    match, not just before the mutation. _apply_kaisuuken calls /v2/kaisuuken/check -- a
    real call on the account -- and every web create route used to make it and only THEN
    reach submit_generation's guard, so a READ_ONLY install still talked to PixAI before
    refusing. That is the identical fail-open the four CLI runners were fixed for on
    2026-07-21. Every stub below is a tripwire: reaching any of them is the bug."""
    def tripwire(name):
        def _boom(*a, **k):
            raise AssertionError("READ_ONLY did not stop the call before " + name)
        return _boom

    req = _build(payload)
    monkeypatch.setattr(core, "READ_ONLY", True)
    for fn in ("match_kaisuuken", "_apply_kaisuuken", "price_task",
               "submit_generation", "submit_fixer", "_session_for_create"):
        monkeypatch.setattr(core, fn, tripwire(fn))

    with pytest.raises(core.PixAIError) as err:
        core.submit(FakeSession(), req)
    assert "READ_ONLY" in str(err.value)


def test_price_is_read_only_and_never_reaches_a_mutation(road):
    """The other half of the guard: price() spends nothing, so it is NOT READ_ONLY-gated
    -- a locked-down install still gets to see what something would cost."""
    sess = FakeSession()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(core, "READ_ONLY", True)
        quoted = core.price(sess, _build({"version_id": "V1", "prompt": "x"}))
    assert quoted["cost"] == 1200
    assert not road["submitted"] and not road["fixed"]


# --- (c) the Fix can never spend a card --------------------------------------

@pytest.mark.parametrize("asked", [True, False, None])
def test_fix_forces_no_card_whatever_the_payload_asks(asked, road):
    """POST /v2/task/fixer takes only {mediaId, boxes} -- there is no kaisuukenId field on
    it anywhere -- so no free card can ever cover a Fix however well /v2/kaisuuken/check
    matches the synthesized price shape. Running the check anyway would paint the badge
    emerald 'FREE' over an action about to charge full credits."""
    payload = {"mode": "fix", "source": "99",
               "boxes": [{"x": 1, "y": 2, "width": 30, "height": 40, "tag": "face"}]}
    if asked is not None:
        payload["no_card"] = asked
    req = _build(payload)
    assert req.no_card is True

    quoted = core.price(FakeSession(), req)
    core.submit(FakeSession(), req)
    assert not road["matched"], "the card check must never run for a Fix"
    assert quoted["free"] is False and quoted["card_name"] is None
    assert quoted["cost"] == 1200
    assert road["fixed"] and not road["submitted"]


# --- (d) an incomplete payload is a note, not a number -----------------------

@pytest.mark.parametrize("mode,_p,missing,note,_pr,_mut", MODES, ids=_IDS)
def test_a_missing_input_yields_a_note_and_no_price(mode, _p, missing, note, _pr, _mut,
                                                    road):
    """Fails CLOSED: an unbuildable payload is cost:None plus the note the badge renders,
    never a `free` or a number a caller could spend on. price_task is never reached."""
    req = _build(missing)
    assert req.parameters is None
    assert req.note == note
    assert core.price(FakeSession(), req) == {"cost": None, "free": False, "note": note}
    assert not road["priced"] and not road["matched"]


@pytest.mark.parametrize("mode,_p,missing,note,_pr,_mut", MODES, ids=_IDS)
def test_submit_refuses_a_request_that_could_not_be_built(mode, _p, missing, note, _pr,
                                                          _mut, road):
    """The same request that could not be quoted cannot be spent either -- there is no
    second road to a shape, so an incomplete payload has nothing to submit."""
    with pytest.raises(core.PixAIError):
        core.submit(FakeSession(), _build(missing))
    assert not road["submitted"] and not road["fixed"]


def test_enhance_is_never_priced_even_though_its_shape_is_real(road):
    """[MAJOR] An enhance/panelplugin task HAS a real submit shape, and it still must not
    be quoted: it is priced by its workflow id, deliberately absent from _PRICE_SCALARS,
    so price_task would quote the workflow-less remainder and be confidently wrong.
    `price_note` is how one road carries 'this shape is real but unpriceable' without a
    second road appearing to hold it."""
    req = _build({"mode": "enhance", "source": "55", "workflow_id": "1794855217667308480"})
    assert req.parameters is not None and req.price_note
    quoted = core.price(FakeSession(), req)
    assert quoted["cost"] is None and quoted["free"] is False
    assert not road["priced"], "enhance must not reach the pricing endpoint"
    core.submit(FakeSession(), req)
    assert road["submitted"] == [req.parameters]


# --- the model resolve is one rule, not two ----------------------------------

def test_a_stale_client_version_resolves_identically_for_price_and_submit(monkeypatch):
    """/api/price used to run a weaker resolve of its own (rows[0] via resolve_version_meta,
    and only when the payload carried no version_id and no mode at all) while /api/generate
    validated the client's version_id against the model's real version list. Two rules is a
    badge quoting one model while the submit sends another. One rule now, so the same
    payload resolves to the same modelId on both surfaces."""
    monkeypatch.setattr(core, "list_model_versions",
                        lambda s, mid: [{"version_id": "V-LATEST"}, {"version_id": "V-OLD"}])
    resolve = core.RequestResolver(model_version=core.model_version_resolver(FakeSession()))
    stale = {"model_id": "M1", "version_id": "V-FROM-ANOTHER-MODEL", "prompt": "x"}
    chosen = {"model_id": "M1", "version_id": "V-OLD", "prompt": "x"}

    # A version_id that is not one of M1's own falls back to the newest...
    assert core.build_request(stale, resolve=resolve).parameters["modelId"] == "V-LATEST"
    # ...and one that IS gets honored (the version picker is a real choice).
    assert core.build_request(chosen, resolve=resolve).parameters["modelId"] == "V-OLD"
    # The Loom's image body carries mode="auto" (the inferenceProfile, not a road name) --
    # the old price-side condition skipped its resolve entirely on that, which is how the
    # badge came back "pick a model" for a job /api/generate would happily have submitted.
    loom = {"model_id": "M1", "version_id": "", "prompt": "x", "mode": "auto"}
    assert core.build_request(loom, resolve=resolve).parameters["modelId"] == "V-LATEST"


def test_the_road_is_pinned_by_the_caller_so_a_payload_cannot_switch_it(road):
    """`mode` is overloaded: on the image road it is the inferenceProfile quality setting,
    everywhere else it names a road. A create route is single-purpose and says which road
    it is, so a hand-rolled {"mode": "I2V"} POSTed at /api/generate builds an image gen (as
    it always did) instead of building and PAYING FOR a video. /api/price is the one caller
    that legitimately reads the road off the payload."""
    payload = {"mode": "I2V", "images": ["77"], "version_id": "V1", "prompt": "x"}
    assert core.build_request(payload).mode == "video"                  # /api/price
    pinned = core.build_request(payload, mode="image")                  # /api/generate
    assert pinned.mode == "image"
    assert pinned.parameters["inferenceProfile"] == "i2v"   # lowercased by _gen_parameters
    assert "i2vPro" not in pinned.parameters
