"""The hand/face Fix surface: how its output is NAMED, what metadata it can honestly
carry, and how it gets priced. All mocked -- no network, no spend.

A Fix is submitted over POST /v2/task/fixer with a body of just {mediaId, boxes}, but what
PixAI creates from it is an ordinary taskKind=chat generation whose `chat` block carries a
`fixer` sub-block. Every test below turns on that one fact: the REST body is what we send,
the chat/fixer task is what comes back, and all three gaps (boilerplate filenames, blank
metadata, no cost preview) came from treating the returned task like a normal generation."""
import pathlib
from types import SimpleNamespace

import pytest

import moonglade_backup as core
import moonglade_gallery
from moonglade_gallery import CATALOG_FIELDS, save_catalog

from tests.conftest import login_client


REFERENCE_PRO = core.EDIT_MODELS["reference-pro"]["model_id"]

# The prompt PixAI writes into a fixer task itself. It is a FIXED template -- identical on
# every Fix ever submitted -- which is exactly why naming the output from it produced a
# folder of indistinguishable 60-character files.
FIX_BOILERPLATE = ("Image 2 shows the areas in Image 1 that need fixing. Please repair the "
                   "marked hands and faces while keeping everything else unchanged.")


def _fixer_task(*, boxes=None, source="700", outputs=None, top_model=True):
    """A getTaskById-shaped Fix task, matching a real one: the boxes live under
    chat.fixer, the source media id is repeated at both levels, and PixAI's own fixed
    prompt template sits in `prompts`."""
    boxes = boxes if boxes is not None else [{"x": 10, "y": 20, "width": 30, "height": 40,
                                              "tag": "hand"}]
    params = {
        "priority": 1000, "width": 1024, "height": 1536,
        "prompts": FIX_BOILERPLATE, "mediaId": source,
        "chat": {"fixer": {"boxes": boxes}, "mediaId": source,
                 "modelId": REFERENCE_PRO, "prompts": FIX_BOILERPLATE},
        "isPrivate": False, "enablePreview": False, "hidePrompts": False,
    }
    if top_model:
        params["modelId"] = REFERENCE_PRO
    return {"createdAt": "2026-07-25T12:00:00Z", "parameters": params,
            "outputs": outputs if outputs is not None else {"mediaId": "M9"}}


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


# ---------------------------------------------------------------------------
# 1. Naming -- a Fix output is named from its SOURCE, never from the template prompt
# ---------------------------------------------------------------------------

def test_fixer_block_only_matches_a_real_fix():
    assert core.fixer_block(_fixer_task())["boxes"][0]["tag"] == "hand"
    # an instruct Edit is also a chat task, but carries no fixer sub-block
    assert core.fixer_block({"parameters": {"chat": {"prompts": "make it night"}}}) is None
    assert core.fixer_block({"parameters": {"prompts": "a druid"}}) is None
    assert core.fixer_block(None) is None


def test_fix_marker_names_the_regions_that_were_repaired():
    assert core.fix_marker([{"tag": "face"}]) == "fix-face"
    assert core.fix_marker([{"tag": "hand"}]) == "fix-hand"
    # stable order regardless of the order the boxes were drawn in, and deduped
    assert core.fix_marker([{"tag": "hand"}, {"tag": "face"}, {"tag": "hand"}]) == "fix-face-hand"
    # an untagged box degrades to a plain marker rather than guessing which it was
    assert core.fix_marker([{}]) == "fix"
    assert core.fix_marker([]) == "fix"


def test_build_fix_stem_name_keeps_the_media_id_last():
    """Invariant 7 (the shared media_id -> file matcher) is what resume and every
    already_downloaded() check rely on: the readable text may be anything, but the file
    must still end in `_<media_id>`."""
    stem = core.build_fix_stem_name("a night elf druid", [{"tag": "face"}], "T1", "M9", 60)
    assert stem == "a_night_elf_druid_fix-face_T1_M9"
    assert stem.endswith("_M9")


def test_build_fix_stem_name_marker_survives_a_long_source_label():
    """The length cap applies to the source slug ONLY. If the marker could be truncated
    away, a long-prompted source would produce exactly the unreadable name this scheme
    exists to replace."""
    stem = core.build_fix_stem_name("x" * 200, [{"tag": "hand"}], "T1", "M9", 20)
    assert "_fix-hand_T1_M9" in stem
    assert stem.startswith("x" * 20 + "_")


def test_build_fix_stem_name_without_a_source_label():
    assert core.build_fix_stem_name("", [{"tag": "face"}], "T1", "M9", 60) == "fix-face_T1_M9"


def _stub_collect(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "resolve_media",
                        lambda s, m: ("https://cdn/" + m, {"width": 1024, "height": 1536}))
    monkeypatch.setattr(core, "download",
                        lambda s, url, stem, **k: ("ok", stem.with_suffix(".jpg")))
    monkeypatch.setattr(moonglade_gallery, "make_thumbnail", lambda *a, **k: None)


def test_collect_names_a_fix_from_its_source_image_not_the_template(monkeypatch, tmp_path):
    """The observed bug: a Fix landed as
    images/Image_2_shows_the_areas_in_Image_1_that_need_fixing_Please_r_<task>_<media>.jpg.
    Every Fix output got that same name because the fixer prompt is a fixed template."""
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="700", filename="images/a_night_elf_druid_T0_700.jpg",
                       prompt_preview="a night elf druid, moonlight")])
    _stub_collect(monkeypatch, tmp_path)
    monkeypatch.setattr(core, "_task_detail_query", lambda s, t: _fixer_task())
    core.collect_generation(object(), "T1", str(tmp_path))
    row = next(r for r in moonglade_gallery.load_catalog(tmp_path / "catalog.db")
               if r["media_id"] == "M9")
    assert row["filename"] == "images/a_night_elf_druid_moonlight_fix-hand_T1_M9.jpg"
    assert "Image_2_shows" not in row["filename"]


def test_collect_falls_back_to_the_source_media_id_when_it_is_not_in_the_catalog(
        monkeypatch, tmp_path):
    """A Fix run on an image this backup has never seen (a fresh upload) still must not
    inherit the template name -- the source media_id is at least a real handle."""
    _stub_collect(monkeypatch, tmp_path)
    monkeypatch.setattr(core, "_task_detail_query", lambda s, t: _fixer_task(source="700"))
    core.collect_generation(object(), "T1", str(tmp_path))
    row = next(r for r in moonglade_gallery.load_catalog(tmp_path / "catalog.db")
               if r["media_id"] == "M9")
    assert row["filename"] == "images/700_fix-hand_T1_M9.jpg"


def test_collect_still_names_an_ordinary_generation_from_its_prompt(monkeypatch, tmp_path):
    """No-regression: only the fixer family changes. A normal generation keeps
    build_stem_name's <prompt>_<task>_<media>."""
    _stub_collect(monkeypatch, tmp_path)
    monkeypatch.setattr(core, "_task_detail_query", lambda s, t: {
        "parameters": {"prompts": "a night elf druid", "modelId": "V1"},
        "outputs": {"mediaId": "M9", "seed": 42}})
    core.collect_generation(object(), "T1", str(tmp_path))
    row = next(r for r in moonglade_gallery.load_catalog(tmp_path / "catalog.db")
               if r["media_id"] == "M9")
    assert row["filename"] == "images/a_night_elf_druid_T1_M9.jpg"


# ---------------------------------------------------------------------------
# 2. Metadata -- fill what the task really carries, leave the rest an honest em-dash
# ---------------------------------------------------------------------------

def test_extract_full_meta_reads_a_fixer_tasks_model():
    fm = core.extract_full_meta(_fixer_task())
    assert fm["model_id"] == REFERENCE_PRO
    assert fm["model_name"] == "Reference Pro"


def test_extract_full_meta_falls_back_to_the_chat_blocks_model_id():
    """build_chat_edit_parameters sets modelId INSIDE the chat block and nowhere else, so a
    chat task built by this app has no top-level modelId at all."""
    fm = core.extract_full_meta(_fixer_task(top_model=False))
    assert fm["model_id"] == REFERENCE_PRO


def test_extract_full_meta_invents_no_seed_sampler_steps_or_cfg_for_a_fix():
    """A fixer task has no outputs.detailParameters and no seed. Those fields stay empty --
    the detail page's em-dash is the honest answer; a borrowed number would be a lie."""
    fm = core.extract_full_meta(_fixer_task())
    assert fm["seed"] == "" and fm["steps"] == ""
    assert fm["sampler"] == "" and fm["cfg_scale"] == ""


def test_collect_writes_the_fix_model_and_leaves_the_rest_empty(monkeypatch, tmp_path):
    """The catalog row is what the detail page renders. Model was an em-dash because the
    collect path never wrote model_id/model_name at all."""
    _stub_collect(monkeypatch, tmp_path)
    monkeypatch.setattr(core, "_task_detail_query", lambda s, t: _fixer_task())
    core.collect_generation(object(), "T1", str(tmp_path))
    row = next(r for r in moonglade_gallery.load_catalog(tmp_path / "catalog.db")
               if r["media_id"] == "M9")
    assert row["model_id"] == REFERENCE_PRO and row["model_name"] == "Reference Pro"
    assert row["width"] == "1024" and row["height"] == "1536"     # dimensions already survived
    assert row["seed"] == "" and row["steps"] == ""
    assert row["sampler"] == "" and row["cfg_scale"] == ""


# ---------------------------------------------------------------------------
# 3. Pricing -- /v2/task-price CAN price a Fix, given the chat.fixer-shaped params
# ---------------------------------------------------------------------------

def test_fix_price_params_carry_the_boxes_in_the_chat_block():
    """The chat block is what carries the cost: measured 2026-07-25, the same call without
    it returns the 1200 base floor instead of a Fix's real price."""
    p = core.build_fixer_price_parameters(
        "700", [{"x": 1, "y": 2, "width": 3, "height": 4, "tag": "FACE"}])
    assert p["chat"]["fixer"]["boxes"] == [{"x": 1, "y": 2, "width": 3, "height": 4,
                                           "tag": "face"}]
    assert p["chat"]["modelId"] == REFERENCE_PRO and p["modelId"] == REFERENCE_PRO
    assert p["chat"]["mediaId"] == "700" and p["mediaId"] == "700"


def test_fix_price_params_share_submit_fixers_own_box_cleaning(monkeypatch):
    """The priced shape must be the SUBMITTED shape -- if the two filtered boxes
    differently, the badge would price a request the server never receives."""
    boxes = [{"x": 5, "y": 6, "width": 7, "height": 8, "tag": "Hand"},
             {"x": 1, "y": 1, "width": 0, "height": 5, "tag": "hand"},   # zero width
             {"x": 1, "y": 1, "width": 5, "height": 5, "tag": "elbow"}]  # not a fixer tag
    seen = {}
    monkeypatch.setattr(core, "_rest_post",
                        lambda s, path, body, **k: seen.update(body=body) or {"id": "F1"})
    core.submit_fixer(object(), "700", boxes)
    priced = core.build_fixer_price_parameters("700", boxes)
    assert priced["chat"]["fixer"]["boxes"] == seen["body"]["boxes"]
    assert len(seen["body"]["boxes"]) == 1


def test_fix_price_params_refuse_a_request_with_no_usable_box():
    with pytest.raises(core.PixAIError):
        core.build_fixer_price_parameters("700", [])


def test_price_task_json_encodes_the_fix_chat_block(monkeypatch):
    """price_task only forwards keys it knows; `chat` is already in its nested set, so the
    fixer block reaches /v2/task-price as URL-encoded JSON."""
    seen = {}
    monkeypatch.setattr(core, "_rest_get",
                        lambda s, path, params=None, **k: seen.update(params=params)
                        or {"actualPrice": 8000})
    p = core.build_fixer_price_parameters("700", [{"x": 1, "y": 2, "width": 3, "height": 4,
                                                  "tag": "face"}])
    assert core.price_task(object(), p) == 8000
    assert '"fixer"' in seen["params"]["chat"]


def _price_client(tmp_path, monkeypatch, cost=8000):
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "price_task",
                        lambda s, params: seen.update(params=params) or cost)
    monkeypatch.setattr(core, "match_kaisuuken",
                        lambda s, params, **k: seen.setdefault("card_checked", True)
                        and {"id": "c1", "total": 9})
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="700", filename="a_700.png",
                       created_at="2026-07-25T00:00:00")])
    return login_client(tmp_path), seen


def test_price_route_prices_a_fix(tmp_path, monkeypatch):
    cli, seen = _price_client(tmp_path, monkeypatch)
    d = cli.post("/api/price", json={"mode": "fix", "source": "700",
                                     "boxes": [{"x": 1, "y": 2, "width": 3, "height": 4,
                                                "tag": "face"}]}).get_json()
    assert d["cost"] == 8000
    assert seen["params"]["chat"]["fixer"]["boxes"][0]["tag"] == "face"


def test_price_route_never_claims_a_free_card_covers_a_fix(tmp_path, monkeypatch):
    """POST /v2/task/fixer accepts only {mediaId, boxes} -- it has no kaisuukenId field, so
    no free card can ever be spent on a Fix. Running the card check anyway would paint
    "FREE - a card covers this" over an action about to charge full credits."""
    cli, seen = _price_client(tmp_path, monkeypatch)
    d = cli.post("/api/price", json={"mode": "fix", "source": "700",
                                     "boxes": [{"x": 1, "y": 2, "width": 3, "height": 4,
                                                "tag": "hand"}]}).get_json()
    assert d["free"] is False and d["cards"] is None
    assert "card_checked" not in seen


def test_price_route_reaches_task_price_with_the_chat_block_intact(tmp_path, monkeypatch, pixai):
    """The one test that stubs nothing but the HTTP call itself. price_task forwards only
    keys in its own scalar/nested sets, so if `chat` ever stopped surviving that filter the
    badge would quietly show the 1200 base floor instead of a Fix's real price -- a wrong
    number, which is worse than none."""
    seen = {}
    monkeypatch.setattr(core, "_rest_get",
                        lambda s, path, params=None, **k: seen.update(path=path, params=params)
                        or {"originalPrice": 8000, "actualPrice": 8000})
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="700", filename="a_700.png",
                       created_at="2026-07-25T00:00:00")])
    d = login_client(tmp_path).post(
        "/api/price", json={"mode": "fix", "source": "700",
                            "boxes": [{"x": 1, "y": 2, "width": 3, "height": 4,
                                       "tag": "face"}]}).get_json()
    assert d["cost"] == 8000 and d["free"] is False
    assert seen["path"] == "/task-price"
    assert '"fixer"' in seen["params"]["chat"] and seen["params"]["mediaId"] == "700"


def test_price_route_fix_without_a_box_is_a_note_not_a_price(tmp_path, monkeypatch):
    cli, _ = _price_client(tmp_path, monkeypatch)
    d = cli.post("/api/price", json={"mode": "fix", "source": "700", "boxes": []}).get_json()
    assert d["cost"] is None and "box" in d["note"]
    d2 = cli.post("/api/price", json={"mode": "fix", "source": ""}).get_json()
    assert d2["cost"] is None and d2["note"]


# ---------------------------------------------------------------------------
# 3b. The Fix surface's own badge + confirm
#
# The classic template (and its inline fixCost()/editCost()) was cut; the shipped Fix
# surface is now gallery/src/components/FixTab.jsx, with the desktop Edit counterpart in
# EditTab.jsx and the mobile Edit hook in gen/useEditGenerate.js. The contracts below are
# the SAME ones the classic tests pinned -- ported to the React sources, which is how this
# suite already reads shipped front-end behavior (see test_branding.py's LoginPage.jsx
# assertions).
# ---------------------------------------------------------------------------

_GALLERY_SRC = pathlib.Path(__file__).resolve().parent.parent / "gallery" / "src"


def _src(rel):
    return (_GALLERY_SRC / rel).read_text(encoding="utf-8")


def _price_build(src):
    """A cost surface's build() -- the payload builder it hands the shared price probe.

    Since 2026-08-22 the debounce, the /api/price call, the sequence guard and the abort
    live in gen/usePriceProbe.js (one module for all six cost lines); each host keeps only
    a `build` useCallback saying WHAT to price and when there is nothing to price. Every
    such helper closes on its deps array -- `}, [...]` -- and that token never appears
    inside the body, so slicing to the first `}, [` captures the whole thing."""
    i = src.index("const build = useCallback(")
    return src[i:src.index("}, [", i)]


def _probe_src():
    return _src("gen/usePriceProbe.js")


def _transport_src():
    """The one price transport (2026-08-23). The POST came out of the hook: usePriceProbe
    still owns the debounce, the sequence guard, the verdict and the teardown abort, but the
    request -- and the {response}-vs-{failed} split the spend gate reads -- lives in
    gen/priceRequest.js, which the Loom's own price sites ride too."""
    return _src("gen/priceRequest.js")


def test_fix_surface_mounts_the_shared_cost_badge():
    src = _src("components/FixTab.jsx")
    # Ported 2026-08-08 (no-vanilla campaign step 4): the vanilla <mg-cost-badge> custom
    # element became the shared React <CostBadge> (forwardRef, same setPrice/setChecking/clear
    # via costRef). A Fix is the one spend surface a free card can NEVER cover, so it must
    # still carry the shared cost renderer, not a bespoke one.
    assert "import CostBadge from" in src
    assert "<CostBadge ref={costRef}" in src, (
        "the Fix surface no longer mounts <CostBadge> -- it would be the only spend "
        "surface without the shared cost renderer")
    assert "onClick={run}" in src   # and a submit button wired to run()


def test_fix_cost_asks_the_server_and_hardcodes_nothing():
    src = _src("components/FixTab.jsx")
    body = _price_build(src)
    assert 'mode: "fix"' in body
    # The request itself is not this surface's: the host rides the shared probe, and the
    # probe rides the one price transport -- the only /api/price caller under gallery/src.
    assert "usePriceProbe" in src
    assert '"/api/price"' in _transport_src()
    assert "requestPrice" in _probe_src(), (
        "the probe must get its request from gen/priceRequest.js, not hand-roll one again")
    assert "8000" not in body and "8,000" not in body, (
        "the badge hardcodes the measured price instead of calling /api/price -- it would "
        "go silently wrong the moment PixAI reprices a Fix")


def test_fix_confirm_still_gates_the_submit_and_no_longer_denies_a_price():
    src = _src("components/FixTab.jsx")
    assert "window.confirm(" in src
    assert src.index("window.confirm(") < src.index('submitTask("/api/fix"')
    head = src[:src.index("window.confirm(")]
    # The confirm quotes the SETTLED figure, not a blanket cannot-be-priced denial. Since
    # 2026-08-22 that figure is the probe's last /api/price answer, and the identity gate is
    # what guarantees it belongs to THESE boxes -- it replaced the old flush-the-debounce-
    # and-await dance, which existed only because the number could still be in flight.
    assert "probe.response" in head
    assert "if (!probe.canSubmit) { probe.refresh(); return; }" in head, (
        "the confirm may only open once a verdict for this payload has settled")
    assert "no cost preview is available" not in src, (
        "the confirm still tells the owner a Fix cannot be priced -- it can, and the "
        "badge beside the button is showing the number")


def test_badge_and_submit_send_the_same_boxes():
    """The badge has to quote the request the button sends. Both go through the one
    display-to-original-pixel scaler (editCore.js's scaleBoxes); two copies of that
    arithmetic is how a price stops matching the thing being priced."""
    core_src = _src("gen/editCore.js")
    i = core_src.index("export function scaleBoxes(")
    assert "naturalWidth" in core_src[i:i + 400]
    src = _src("components/FixTab.jsx")
    # Since the dock fidelity pass (2026-08-16) the element handed to scaleBoxes is
    # scaleEl() -- the live <img> when it is laid out, else the last real measurement
    # (the ▲-collapsed dock hides the picture with display:none, and a 0-wide element
    # would submit display pixels as original pixels). Same invariant: ONE scaler, the
    # SAME element expression, in the price body and the submit body alike.
    assert src.count("scaleBoxes(boxes, scaleEl())") == 2, (
        "the price body and the submit body no longer share the one scaleBoxes call each "
        "-- the badge would price a request the server never receives")


# Every surviving cost surface. FixTab and EditTab are the desktop fix/edit pair the
# classic's fixCost/editCost became; the mobile Edit hook was written to the identical
# contract (its own header says so) and shares the pin. Since 2026-08-22 all three (and
# the three other cost lines) get their sequence guard from ONE module, so the contract is
# pinned once against gen/usePriceProbe.js and each host is pinned as a caller of it.
_COST_HELPERS = (
    "components/FixTab.jsx",
    "components/EditTab.jsx",
    "gen/useEditGenerate.js",
)


def test_cost_helpers_invalidate_in_flight_requests_before_bailing_out():
    """Found in code review 2026-07-25, and it affected BOTH classic cost helpers.

    Each guards against a stale response with a sequence number: `mine = ++seq`, then the
    handler drops its result if `mine !== seq`. In the classic, the early-return path -- no
    source, or no boxes -- sat BEFORE that bump, so: request goes out for a real selection;
    the user hits Clear (or changes the source); the helper re-runs, takes the early
    return, and leaves the sequence untouched; the in-flight response then arrives, still
    matches, passes the guard, and paints a price for boxes that no longer exist. The
    badge shows a confident number for a request nobody made.

    The bump has to happen BEFORE any return, so bailing out is itself an invalidation.
    The React helpers were written fixed; this pins them fixed.

    Since 2026-08-22 the mechanism is one module: refresh() bumps the sequence the moment a
    re-price is scheduled -- BEFORE the debounce fires and therefore before the fire step can
    take its nothing-to-price exit -- and it cannot be short-circuited past while an answer is
    out (an in-flight request means an unsettled verdict, which never short-circuits). Each
    host says only WHAT is idle; none of them can get the ordering wrong any more.

    Bite: move the `seq.current++` below refresh()'s scheduling and this fails by name."""
    probe = _probe_src()
    refresh = probe[probe.index("const refresh = useCallback("):]
    bump = refresh.index("seq.current++")
    schedule = refresh.index("setTimeout(fire, PRICE_DEBOUNCE_MS)")
    assert bump < schedule, (
        "usePriceProbe's refresh() re-arms the debounce at char {} before invalidating the "
        "answer in flight at char {} -- that response stays valid and repaints a stale price "
        "after the user has cleared or changed the selection".format(schedule, bump))
    # And the fire step's own nothing-to-price exit is downstream of that bump by construction:
    # it only ever runs from the timer refresh() armed.
    fire = probe[probe.index("const fire = useCallback("):probe.index("const refresh = useCallback(")]
    assert "badge.clear()" in fire and "settledFor(key)" in fire, (
        "the idle exit must clear the badge AND settle -- an unsettled idle would dead-disable "
        "the submit control with no message on screen")
    for rel in _COST_HELPERS:
        assert "usePriceProbe" in _src(rel), rel + " no longer rides the shared probe"


def test_cost_helpers_still_drop_a_superseded_response():
    """The other half of the contract, so the fix above can't be 'achieved' by deleting the
    guard: a response whose sequence no longer matches must still be discarded."""
    probe = _probe_src()
    fire = probe[probe.index("const fire = useCallback("):probe.index("const refresh = useCallback(")]
    flat = fire.replace(" ", "")
    # Re-anchored 2026-08-23: there used to be TWO guards, one in .then and one in .catch.
    # requestPrice never rejects -- it RESOLVES onto {response} or {failed} -- so both paths
    # now join at a single guard, which must therefore stand before EITHER of them paints.
    # Same property, one copy of it; the bite below is what actually protects it.
    assert flat.count("mine!==seq.current") == 1, (
        "the answer path and the failure path must join at exactly one sequence guard")
    guard = flat.index("mine!==seq.current")
    assert guard < flat.index("setPrice(null)") and guard < flat.index("setPrice(d)"), (
        "both the answer path and the failure path must consult the sequence before painting, "
        "or a superseded response would repaint over a newer one")
    # Each cost surface owns its OWN sequence (the classic's editCost once shared `costSeq`
    # with the Generate tab's debouncedCost(), so an '?edit=' deep link cancelled the Generate
    # tab's first price check before it ever fired). Ownership is structural now: the counter
    # is a useRef INSIDE the hook, so one probe instance per host is one counter per host.
    assert "const seq = useRef(0)" in probe, "the probe no longer owns a sequence counter"
    assert probe.index("const seq = useRef(0)") > probe.index(
        "export default function usePriceProbe"), (
        "the counter must be declared INSIDE the hook -- module-level state would be shared "
        "across every probe instance, which is the '?edit= cancelled the Generate tab's first "
        "price check' bug all over again")
    for rel in _COST_HELPERS:
        src = _src(rel)
        assert "usePriceProbe({" in src, (
            "{} must instantiate its OWN probe rather than share another surface's".format(rel))
        assert "costRef" in src, "{} must own the badge instance its probe drives".format(rel)
