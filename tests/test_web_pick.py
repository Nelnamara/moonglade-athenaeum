"""The gallery Picker's web API: /api/gallery-images (browse the whole catalog with
paging + full prompts for the copy-to-clipboard feature) and /api/upload (local file
-> PixAI media_id via the free S3 handshake). All localhost-gated; upload_media is
monkeypatched so nothing touches the network."""
import io
import json
import os
import re
from pathlib import Path

import moonglade_backup as core
from moonglade_gallery import CATALOG_FIELDS, _account_key, create_app, save_catalog

from tests.conftest import login_client, login_existing_client
from tests.csshelp import css_rules, element, winning


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _client(tmp_path, rows):
    save_catalog(tmp_path / "catalog.db", rows)
    return create_app(tmp_path).test_client()


def _authed_client(tmp_path, rows):
    """Like _client(), but logged in for real -- for every test below EXCEPT the
    handful that specifically test the unauthenticated/LAN boundary itself
    (test_gallery_images_requires_login_over_lan_but_then_works,
    test_unauthenticated_lan_request_to_index_is_redirected_to_login, and the "mixed"
    tests that check an anonymous request first before logging the SAME client in via
    login_existing_client())."""
    save_catalog(tmp_path / "catalog.db", rows)
    return login_client(tmp_path)


def test_gallery_images_requires_login_over_lan_but_then_works(tmp_path):
    """/api/gallery-images used to be deliberately exempted from EVERY gate (its own
    docstring: 'NOT localhost-gated ... the gate added no protection while breaking
    the picker for the owner on a --host 0.0.0.0 server accessed via a LAN address') --
    a 0.0.0.0 server browsed via a LAN address with no login at all could still pull
    the catalog. The front-door rewrite (2026-07-19) retires that exemption: `/api/`
    now carries no allowlist entry of its own, so a LAN request with no session is
    refused like every other route, and the regression this test guards becomes 'the
    picker still works over LAN for a signed-in user' -- not 'works over LAN with no
    auth at all', which was the whole security gap this rewrite closed."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path, [
        _row(media_id="1", filename="a_1.png", prompt_preview="p",
             created_at="2025-01-01T00:00:00"),
    ])
    LAN = "192.168.1.50"
    r = cli.get("/api/gallery-images", environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 401                        # no session -> refused

    html = cli.get("/login").get_data(as_text=True)
    csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    cli.post("/login", data={"username": "alice", "password": "hunter2", "csrf": csrf})
    d = cli.get("/api/gallery-images", environ_overrides={"REMOTE_ADDR": LAN}).get_json()
    assert len(d["images"]) == 1 and d["total"] == 1    # same LAN address, now logged in


def test_gallery_images_prefers_full_prompt(tmp_path):
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.png", prompt_preview="short...",
             prompt_full="the full glorious prompt", created_at="2025-01-01T00:00:00"),
    ])
    d = cli.get("/api/gallery-images").get_json()
    assert d["images"][0]["prompt"] == "the full glorious prompt"
    assert d["total"] == 1 and d["page"] == 1 and d["limit"] >= 1


def test_gallery_images_type_filter_and_paging(tmp_path):
    rows = [_row(media_id=str(i), filename="f_{}.png".format(i), prompt_preview="p",
                 created_at="2025-01-{:02d}T00:00:00".format(i)) for i in range(1, 6)]
    rows.append(_row(media_id="9", filename="v_9.mp4", is_video="1",
                     created_at="2025-02-01T00:00:00"))
    cli = _authed_client(tmp_path, rows)
    # default type=image: the video is filtered in SQL, so total reflects ONLY the
    # pickable images (5) -- the old behavior counted 6 then hid one (bad counter).
    d1 = cli.get("/api/gallery-images?limit=2&page=1").get_json()
    d2 = cli.get("/api/gallery-images?limit=2&page=2").get_json()
    assert d1["total"] == 5
    ids1 = [m["media_id"] for m in d1["images"]]
    ids2 = [m["media_id"] for m in d2["images"]]
    assert ids1 and ids2 and not set(ids1) & set(ids2)   # paging advances
    assert "9" not in ids1 + ids2                        # video excluded from images
    # type=video: only the video, flagged
    dv = cli.get("/api/gallery-images?type=video").get_json()
    assert dv["total"] == 1 and [m["media_id"] for m in dv["images"]] == ["9"]
    assert dv["images"][0]["is_video"] == "1"
    # type=all: everything
    da = cli.get("/api/gallery-images?type=all").get_json()
    assert da["total"] == 6 and "9" in [m["media_id"] for m in da["images"]]


def test_gallery_images_empty_type_stays_images_only(tmp_path):
    """An EXPLICIT empty type (?type=) means images-only, same as absent -- load-bearing
    back-compat in both directions (issue #3's root): the gallery's vanilla Picker sends
    type='' and must never start surfacing videos (picker-core.js seeds '' for exactly
    that reason), which is why <mg-gallery-picker>'s combined "Image + video" option has
    to submit the server's real both-kinds value, type=all, instead of ''. If this
    mapping ever flips to "both", the Loom picker won't break -- the gallery Picker
    will."""
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00"),
        _row(media_id="9", filename="v_9.mp4", is_video="1",
             created_at="2025-02-01T00:00:00"),
    ])
    d = cli.get("/api/gallery-images?type=").get_json()
    assert d["total"] == 1 and [m["media_id"] for m in d["images"]] == ["1"]


def test_gallery_images_includes_is_nsfw_for_privacy_blur(tmp_path):
    """Audit 2026-07-21, S5 (the remaining half): /api/similar already projects is_nsfw
    (fixed 2026-07-23) but /api/gallery-images -- the route the gallery Picker,
    <mg-gallery-picker>, and the Generate drawer's reference slots all actually call --
    did not, so Privacy Blur's stronger NSFW rule (.card[data-nsfw="1"] img) never saw
    an NSFW thumbnail on any of those three surfaces."""
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.png", is_nsfw="1", created_at="2025-01-01T00:00:00"),
        _row(media_id="2", filename="b_2.png", is_nsfw="", created_at="2025-01-02T00:00:00"),
    ])
    d = cli.get("/api/gallery-images").get_json()
    by_id = {m["media_id"]: m for m in d["images"]}
    assert by_id["1"]["is_nsfw"] == "1"
    assert by_id["2"]["is_nsfw"] == ""


def test_privacy_blur_covers_the_picker_and_drawer_reference_surfaces(tmp_path):
    """Audit 2026-07-21, S5 (the client half): with is_nsfw now on the wire (test above),
    every surface rendering /api/gallery-images results needs to set data-nsfw on the card
    it builds, and body.privacy-blur needs a rule that actually blurs it -- neither existed
    for the gallery Picker, the Edit tab's single reference slot (#gen-ref-slot),
    <mg-gallery-picker> (.mg-pk-cell), or the Generate drawer's reference slots (.mgd-slot,
    all three renderers) before this pass. Source-checks since none of these are build-step
    components with an in-repo DOM test harness.

    O13 (Phase 2) update: the gallery's own Picker no longer builds its own .pick-cell grid
    at all -- it mounts the shared <mg-gallery-picker>, whose OWN is_nsfw/data-nsfw/privacy-
    blur handling is covered by the picker_js assertions below (that coverage now applies to
    the gallery too, not just the Loom). Picker.open's mg-pick bridge converts the
    component's boolean is_nsfw back to the app-wide '1'/'' STRING convention at the
    boundary, since Gen.renderGenRef's #gen-ref-slot setter (checked below) still does a
    strict === '1' comparison -- this is the one place left in moonglade_gallery.py that needs
    is_nsfw to reach it as a real value, not just be forwarded blindly."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "if(f) f(d.media_id, d.thumb, d.prompt||'', d.is_nsfw?'1':'');" in html, (
        "Picker.open's mg-pick bridge must convert the component's boolean is_nsfw back to "
        "'1'/'' -- passing the raw boolean through would silently break the strict ===  '1' "
        "check in Gen.renderGenRef's #gen-ref-slot setter below")
    assert "Picker.open(function(mid, thumb, prompt, is_nsfw){ d.respond(mid, thumb, is_nsfw); }" in html
    assert 'genRef={media_id:mid, thumb:thumb, is_nsfw:is_nsfw}' in html          # #gen-ref-slot
    assert 'body.privacy-blur #gen-ref-slot[data-nsfw="1"] img' in html
    # The old #pick-modal grid (and its dead privacy-blur branch) must be functionally
    # gone -- checked as the real CSS rule / DOM class assignment, not a bare substring,
    # since explanatory comments in the CSS legitimately still mention the old name.
    assert '.pick-cell{' not in html and "className='pick-cell'" not in html, (
        "the old #pick-modal grid should be fully gone -- <mg-gallery-picker>'s own "
        ".mg-pk-cell covers this now (see picker_js below)")

    picker_js = (Path(__file__).resolve().parents[1] / "static" / "mg-gallery-picker.js").read_text(encoding="utf-8")
    assert "if (m.is_nsfw === '1') c.setAttribute('data-nsfw', '1');" in picker_js
    assert "is_nsfw: m.is_nsfw === '1'" in picker_js
    assert 'body.privacy-blur mg-gallery-picker .mg-pk-cell[data-nsfw="1"] img' in picker_js

    drawer_js = (Path(__file__).resolve().parents[1] / "static" / "mg-generate-drawer.js").read_text(encoding="utf-8")
    assert drawer_js.count("box.setAttribute('data-nsfw', '1');") == 3   # _renderSlots, _renderEndSlot, _renderVidSlots
    assert "respond: function (media_id, thumb, is_nsfw)" in drawer_js
    assert 'body.privacy-blur mg-generate-drawer .mgd-slot[data-nsfw="1"] img' in drawer_js

    loom_jsx = (Path(__file__).resolve().parents[1] / "loom" / "master-storyboard.jsx").read_text(encoding="utf-8")
    assert "cb(e.detail.media_id, e.detail.thumb, e.detail.is_video, e.detail.duration, e.detail.is_nsfw);" in loom_jsx
    assert 'openPick((mid, thumb, isVideo, duration, isNsfw) => e.detail.respond(mid, thumb, isNsfw)' in loom_jsx

    loom_bundle = (Path(__file__).resolve().parents[1] / "loom" / "dist" / "master-storyboard.bundle.js").read_text(encoding="utf-8")
    assert "is_nsfw" in loom_bundle or "isNsfw" in loom_bundle   # esbuild output stays in sync with the .jsx source


def test_gallery_picker_is_the_shared_mg_gallery_picker_component(tmp_path):
    """O13 (Phase 2): the gallery's own image picker is <mg-gallery-picker> now -- the same
    component the Loom mounts -- instead of the old hand-rolled #pick-modal grid. Pins the
    script include and the mount/bridge shape, and asserts the old markup/grid/upload/filter
    IDs are gone, the same 'new surface present + old one gone' shape as
    test_gallery_video_tab_is_the_shared_drawer_component (the Video tab's own Option-A
    migration) -- so this swap can't silently regress back to the old hand-rolled form."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "/static/mg-gallery-picker.js" in html                    # component script on the gallery
    assert "document.createElement('mg-gallery-picker')" in html     # mounted by Picker.open(), not static markup
    assert "el.setAttribute('show-source', '');" in html             # gallery-parity attrs actually requested
    assert "el.setAttribute('show-upload', '');" in html
    assert "el.setAttribute('show-copy-prompt', '');" in html
    assert "el.addEventListener('mg-pick'" in html
    assert "el.addEventListener('mg-close'" in html
    # the old hand-rolled picker markup/grid/upload/filter chrome is gone
    for old_id in ('id="pick-modal"', 'id="pick-scrim"', 'id="pick-grid"', 'id="pick-q"',
                   'id="pick-up"', 'id="pick-file"', 'id="pick-more"', 'id="pick-copy"',
                   'id="pick-collection"', 'id="pick-source"', 'id="pick-rating"', 'id="pick-sort"'):
        assert old_id not in html, "old #pick-modal markup survived the O13 migration: " + old_id
    assert "Picker.onFilter" not in html and "Picker.onScroll" not in html and "Picker.toggleCopy" not in html


def test_gallery_model_flyout_is_the_shared_mg_model_picker_component(tmp_path):
    """O12 (Phase 2): #model-flyout's own hand-rolled search/grid/hover-preview/market UI is
    two <mg-model-picker> instances now (kind="base" and kind="lora" multi market), lazily
    mounted into #gen-picker-host on first open -- not the old #gen-grid/#gen-q/.gen-card
    rendering. Same 'new surface present + old one gone' shape as the O13 test above."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "/static/mg-model-picker.js" in html
    assert 'id="gen-picker-host"' in html
    assert "document.createElement('mg-model-picker')" in html
    assert "basePickerEl.setAttribute('kind','base');" in html
    assert "loraPickerEl.setAttribute('kind','lora');" in html
    assert "loraPickerEl.setAttribute('multi','');" in html
    assert "loraPickerEl.setAttribute('market','');" in html   # O13's sort/category parity for LoRAs
    assert "addEventListener('mg-pick', function(e){ onBasePick(e.detail); });" in html
    assert "addEventListener('mg-pick', function(e){ onLoraPick(e.detail.model, e.detail.selected); });" in html
    # the old hand-rolled grid/search/market chrome is gone
    for old_id in ('id="gen-grid"', 'id="gen-empty"', 'id="gen-q"', 'id="mkt-sort"',
                   'id="mkt-cats"', 'id="mkt-popular"', 'id="mkt-newest"'):
        assert old_id not in html, "old #model-flyout grid markup survived the O12 migration: " + old_id
    assert "function selectCard(" not in html and "function toggleLora(" not in html
    assert "function search(){" not in html and "function render(rows" not in html


def test_model_flyout_grid_fills_the_panel_instead_of_a_fixed_320px_cap(tmp_path):
    """picker-parity-round2 (problem 1): the owner's live screenshot showed only ~2 rows of
    cards then a large dead area filling the rest of #model-flyout's real height. Root cause
    was TWO independent height constraints fighting each other: .gen-body was an
    overflow:auto scroll container AND <mg-model-picker>'s own .mg-grid had a fixed
    max-height:320px (see mg-model-picker.js's own tests for that half of the fix) -- so on
    any flyout taller than ~380px, .gen-body's real extra height just sat there empty below
    the capped grid. Fix: hand the real height down to the GRID so IT is the one scrolling
    region, scoped to #model-flyout only (the main Generate form's own .gen-body is a plain
    tall scrolling form and must stay untouched)."""
    cli = _authed_client(tmp_path, [])
    html = cli.get("/").get_data(as_text=True)
    assert "#model-flyout .gen-body{overflow:hidden;display:flex;flex-direction:column;min-height:0;}" in html
    assert "#model-flyout #gen-picker-host{flex:1;min-height:0;display:flex;flex-direction:column;}" in html
    assert "#model-flyout mg-model-picker{flex:1;min-height:0;}" in html
    # #gen-drawer's own .gen-body (the main form) must be UNTOUCHED -- only ONE overflow:auto
    # rule for the base .gen-body class, not overridden away by this fix.
    assert html.count(".gen-body{padding:12px 14px;overflow-y:auto;flex:1;}") == 1


def test_model_flyout_surfaces_version_picker_and_capabilities(tmp_path):
    """picker-parity-round2 (problems 4/5): resolve_version_meta() already fetches a
    model's OTHER releases + the author's own sampling_method/capabilities -- this was being
    resolved and thrown away. #gen-version/#gen-caps surface both; base-type wiring feeds
    the resolved architecture into the LoRA picker for problem 3's compat sort/badge."""
    cli = _authed_client(tmp_path, [])
    html = cli.get("/").get_data(as_text=True)
    assert 'id="gen-version"' in html and 'onchange="Gen.pickVersion(this.value)"' in html
    assert 'id="gen-caps"' in html
    assert 'id="gen-modeldefaults-label"' in html   # sampling_method note target
    assert "pickVersion:pickVersion" in html         # exposed on the Gen public object
    # every base pick re-resolves via ?all=1 (the version LIST, not just the latest)...
    assert "fetch('/api/model-version?model_id='+encodeURIComponent(m.model_id)+'&all=1')" in html
    # ...and feeds the resolved architecture straight into the LoRA picker (problem 3)
    assert "if(loraPickerEl) loraPickerEl.setAttribute('base-type', selected.model_type||'');" in html


def test_base_model_version_dropdown_is_hidden_when_there_is_only_one_version(tmp_path):
    """AUDIT_2026-07-21 follow-up: renderVersions() rendered the base-model version <select>
    even for a single-option list -- a control that cannot do anything, on the majority of
    picks (most models publish exactly one release). The gate already existed in TWO other
    places in this codebase and is reused verbatim rather than reinvented: the Gallery's own
    per-LoRA chips (renderLoras -> `l.versions&&l.versions.length>1`) and the Loom's
    .lv-versel (`imgModel.versions.length > 1`).

    #gen-selmeta itself must still open for the capability badges alone -- those are
    independent of how many versions exist -- so the gate hides the <select>, not the row."""
    cli = _authed_client(tmp_path, [])
    html = cli.get("/").get_data(as_text=True)
    assert "var multi=versions.length>1;" in html
    assert "sel.style.display=multi?'':'none';" in html
    # the <option> list is only built when there's a real choice...
    assert "sel.innerHTML=multi?versions.map(function(v){" in html
    # ...and the containing row still shows for capabilities-only models
    assert "wrap.classList.toggle('show', multi||caps>0);" in html
    # the established gate this copies, still present on the per-LoRA chips
    assert "var verSel=(l.versions&&l.versions.length>1)" in html
    # submit still reads selected.version_id, never the <select>'s value -- hiding the
    # control must not be able to change what gets generated
    assert "return { version_id:(selected&&selected.version_id)||''," in html


def test_model_search_lora_always_uses_graphql_even_without_market_filters(tmp_path, monkeypatch):
    """picker-parity-round2 (problem 3): LoRA search needs real per-row architecture data
    (modelType/loraBaseModelType) on EVERY search, not just category/Newest browsing -- REST
    has no such field to request (confirmed by inspecting its full response shape -- see
    moonglade_backup.py's model_search_rest), so kind=lora now always routes through
    model_search_market_gql (GraphQL), regardless of category/sort. Base-model search
    (kind=base) is UNCHANGED -- REST by default, GraphQL only for category/Newest."""
    calls = {"rest": 0, "gql": 0}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "model_search_rest",
                        lambda *a, **k: calls.__setitem__("rest", calls["rest"] + 1) or {"results": [], "has_more": False})
    monkeypatch.setattr(core, "model_search_market_gql",
                        lambda *a, **k: calls.__setitem__("gql", calls["gql"] + 1) or {"results": [], "has_more": False})
    cli = _authed_client(tmp_path, [])
    # plain keyword LoRA search, no category, no sort=newest -- would have hit REST before this pass
    r = cli.get("/api/model-search?kind=lora&q=eris")
    assert r.status_code == 200
    assert calls == {"rest": 0, "gql": 1}
    # base-model search under the SAME conditions is unaffected -- still REST by default
    cli.get("/api/model-search?kind=base&q=eris")
    assert calls == {"rest": 1, "gql": 1}


def test_model_search_base_type_annotates_lora_results_only(tmp_path, monkeypatch):
    """base_type= (the caller's already-resolved selected base model_type) threads into
    annotate_lora_compat for kind=lora only -- a base-model search has nothing to
    compat-sort against, so it ignores the param entirely even if sent."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "model_search_market_gql",
                        lambda *a, **k: {"results": [{"model_id": "1", "lora_base_model_type": "SDXL_MODEL"}],
                                          "has_more": False})
    monkeypatch.setattr(core, "model_search_rest",
                        lambda *a, **k: {"results": [{"model_id": "9"}], "has_more": False})
    cli = _authed_client(tmp_path, [])
    d = cli.get("/api/model-search?kind=lora&base_type=SDXL_MODEL").get_json()
    assert d["results"][0]["compat"] == "yes"
    # no base_type -> untouched (no compat key added at all)
    d2 = cli.get("/api/model-search?kind=lora").get_json()
    assert "compat" not in d2["results"][0]
    # base kind ignores base_type entirely (nothing to compat-sort a base model against)
    d3 = cli.get("/api/model-search?kind=base&base_type=SDXL_MODEL").get_json()
    assert "compat" not in d3["results"][0]


def test_model_search_threads_base_type_into_the_server_side_filter(tmp_path, monkeypatch):
    """AUDIT_2026-07-21: `base_type=` already reached this route for the compat sort/badge;
    it now ALSO drives PixAI's own generationModels(loraBaseModelTypes:) filter, which this
    app had never used -- the reason a DiT.2 user's LoRA browse came back 24-of-24 SD 1.5.
    One caller-supplied value, reused at every layer rather than a second parameter."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    gql = []
    monkeypatch.setattr(core, "model_search_market_gql", lambda *a, **k: (
        gql.append(k) or {"results": [{"model_id": "1", "lora_base_model_type": "MMDIT26A_MODEL"}],
                          "has_more": False, "next_cursor": ""}))
    monkeypatch.setattr(core, "model_search_rest",
                        lambda *a, **k: {"results": [{"model_id": "9"}], "has_more": False})
    cli = _authed_client(tmp_path, [])

    d = cli.get("/api/model-search?kind=lora&base_type=MMDIT26A_MODEL").get_json()
    assert gql[-1]["lora_base_type"] == "MMDIT26A_MODEL"
    # the PRECISE per-row layer is still applied on top of the coarse server-side filter
    assert d["results"][0]["compat"] == "yes"

    # no base picked yet -> no filter (browsing before a pick must be untouched)
    cli.get("/api/model-search?kind=lora")
    assert gql[-1]["lora_base_type"] == ""

    # a base-model search never sends it, even if a client passes one
    cli.get("/api/model-search?kind=base&sort=newest&base_type=MMDIT26A_MODEL")
    assert gql[-1]["lora_base_type"] == ""


def test_model_search_threads_cursor_to_whichever_path_is_in_use(tmp_path, monkeypatch):
    """Owner report 2026-07-24: the picker never loads more than its first page. The
    unused `offset=` param is replaced by a unified `cursor=` the client just echoes back
    without needing to know which search path is serving it -- the route decides what an
    opaque cursor MEANS based on which path is active for THIS request. GraphQL: the
    literal cursor string, passed through as `after=`. REST: a plain base-10 offset,
    computed here (not inside model_search_rest, which only knows a raw int offset)."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    gql_calls = []
    monkeypatch.setattr(core, "model_search_market_gql", lambda *a, **k: (
        gql_calls.append(k) or {"results": [], "has_more": True, "next_cursor": "GQL_NEXT"}))
    rest_calls = []
    monkeypatch.setattr(core, "model_search_rest", lambda *a, **k: (
        rest_calls.append(k) or {"results": [], "has_more": True}))
    cli = _authed_client(tmp_path, [])

    # GraphQL path (kind=lora always uses it): cursor passed straight through as `after`,
    # and the server's own next_cursor rides back to the client unchanged.
    d = cli.get("/api/model-search?kind=lora&cursor=GQL_PREV").get_json()
    assert gql_calls[-1]["after"] == "GQL_PREV"
    assert d["next_cursor"] == "GQL_NEXT"

    # REST path (plain base-model keyword search): cursor is a base-10 offset string;
    # next_cursor is computed as offset+size since model_search_rest has no cursor concept.
    d2 = cli.get("/api/model-search?kind=base&cursor=24&size=24").get_json()
    assert rest_calls[-1]["offset"] == 24
    assert d2["next_cursor"] == "48"

    # first page (no cursor at all) -> REST offset 0, GraphQL after=None (not sent)
    cli.get("/api/model-search?kind=base")
    assert rest_calls[-1]["offset"] == 0
    cli.get("/api/model-search?kind=lora")
    assert gql_calls[-1]["after"] is None

    # has_more False -> next_cursor must be empty, on EITHER path, regardless of what the
    # underlying offset math would otherwise compute -- never hand back a cursor that
    # would page a client past the real end of the list.
    monkeypatch.setattr(core, "model_search_rest", lambda *a, **k: {"results": [], "has_more": False})
    d3 = cli.get("/api/model-search?kind=base&cursor=24").get_json()
    assert d3["next_cursor"] == ""


def test_collections_endpoint(tmp_path):
    rows = [_row(media_id="1", filename="a_1.png", collections="Banners,Faves",
                 created_at="2025-01-01T00:00:00"),
            _row(media_id="2", filename="b_2.png", collections="Banners",
                 created_at="2025-01-02T00:00:00")]
    cli = _authed_client(tmp_path, rows)
    d = cli.get("/api/collections").get_json()
    assert set(d["collections"]) == {"Banners", "Faves"}


def test_upload_returns_media_id_and_cleans_temp(tmp_path, monkeypatch):
    seen = {}

    def fake_upload(session, path, *a, **k):
        seen["path"] = path
        assert os.path.exists(path)            # file was materialized for upload
        return "M123"

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "upload_media", fake_upload)
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    resp = cli.post("/api/upload", data={
        "file": (io.BytesIO(b"\x89PNG fake"), "pic.png"),
    }, content_type="multipart/form-data")
    assert resp.get_json() == {"media_id": "M123"}
    assert not os.path.exists(seen["path"])    # temp file removed after upload


def test_upload_requires_a_file(tmp_path):
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    assert cli.post("/api/upload", data={}).status_code == 400


def test_tag_search_gql_shapes_names(monkeypatch):
    seen = {}

    def fake_gql(session, q, variables=None, **k):
        seen["q"], seen["vars"] = q, variables
        return {"tags": {"edges": [{"node": {"name": "no humans"}},
                                   {"node": {"name": "no shoes"}},
                                   {"node": {}}]}}

    monkeypatch.setattr(core, "gql_adhoc", fake_gql)
    out = core.tag_search_gql(object(), "no hu", first=8)
    assert out == ["no humans", "no shoes"]          # nameless node dropped
    assert "tags(q:" in seen["q"] and seen["vars"] == {"k": "no hu", "n": 8}


def test_tag_suggest_route_short_prefix_is_free(tmp_path, monkeypatch):
    """Under 2 chars: no session, no network -- just an empty list."""
    def boom(*a, **k):
        raise AssertionError("must not touch the network for short prefixes")
    monkeypatch.setattr(core, "_make_session", boom)
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    assert cli.get("/api/tag-suggest?q=n").get_json() == {"tags": []}


def test_tag_suggest_route_returns_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "tag_search_gql", lambda s, q, first=8: ["no humans"])
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    assert cli.get("/api/tag-suggest?q=no hu").get_json() == {"tags": ["no humans"]}


def test_price_route_video_mode(tmp_path, monkeypatch):
    """Video payloads price through build_shot_video_params + report the card count."""
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "price_task",
                        lambda s, params: seen.update(params=params) or 27500)
    monkeypatch.setattr(core, "match_kaisuuken",
                        lambda s, params, enrich=False: {"id": "c1", "total": 9, "expiresAt": 1})
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    d = cli.post("/api/price", json={"mode": "I2V", "images": ["55"], "prompt": "pan",
                                     "duration": 5, "video_model": "v3.2",
                                     "audio": True}).get_json()
    assert d["cost"] == 27500 and d["free"] is True and d["cards"] == 9
    i2v = seen["params"]["i2vPro"]
    assert i2v["mediaId"] == "55" and i2v["model"] == "v3.2"
    assert i2v["generateAudio"] is True


def test_price_route_reads_generate_audio_key_too(tmp_path, monkeypatch):
    """The Loom sends `generate_audio` (matching /api/loom/generate's own key); the older
    `audio` key is the web drawer's. /api/price must accept either -- it used to only read
    `audio`, so a Loom price preview never reflected the real audio-enabled cost even though
    the actual generation correctly included it (a real, if smaller, mismatch fixed alongside
    wiring audio into the Loom for the first time)."""
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "price_task",
                        lambda s, params: seen.update(params=params) or 27500)
    monkeypatch.setattr(core, "match_kaisuuken",
                        lambda s, params, enrich=False: {"id": "c1", "total": 9, "expiresAt": 1})
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    d = cli.post("/api/price", json={"mode": "I2V", "images": ["55"], "prompt": "pan",
                                     "duration": 5, "video_model": "v3.2",
                                     "generate_audio": True, "audio_language": "none"}).get_json()
    assert d["cost"] == 27500
    i2v = seen["params"]["i2vPro"]
    assert i2v["generateAudio"] is True
    assert i2v["audioLanguage"] == "none"   # PixAI's real SE-only value, not literal silence


def test_price_route_video_needs_an_image(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no pricing without a source image")
    monkeypatch.setattr(core, "price_task", boom)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    d = cli.post("/api/price", json={"mode": "R2V", "images": []}).get_json()
    assert d["cost"] is None and "source image" in d["note"]


def test_price_route_i2v_still_needs_an_image_even_with_video_refs(tmp_path, monkeypatch):
    # I2V/FLF are image-anchored -- a video_refs entry must NOT waive the image requirement
    # for those two modes, only for R2V (which the multi-parity build made a genuine option).
    def boom(*a, **k):
        raise AssertionError("no pricing without a source frame")
    monkeypatch.setattr(core, "price_task", boom)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    d = cli.post("/api/price", json={"mode": "I2V", "images": [], "video_refs": ["9"]}).get_json()
    assert d["cost"] is None and "source image" in d["note"]


def test_price_route_r2v_prices_video_only_multiref(tmp_path, monkeypatch):
    """Found while wiring the ref-slot expansion: R2V's price gate checked ONLY `images`,
    so a video-only or audio-only Multi-ref (both real, API-supported references) silently
    failed pricing with 'pick a source image' even though the submit itself would have
    worked. R2V must accept ANY reference kind alone."""
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "price_task", lambda s, params: seen.update(params=params) or 27500)
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, enrich=False: None)
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    d = cli.post("/api/price", json={"mode": "R2V", "images": [], "video_refs": ["9"],
                                     "prompt": "@video1 dances"}).get_json()
    assert d["cost"] == 27500 and d.get("note") is None
    rv = seen["params"]["referenceVideo"]
    assert rv["referenceVideoMediaIds"] == ["9"] and rv["referenceImageMediaIds"] == []
    seen.clear()
    d2 = cli.post("/api/price", json={"mode": "R2V", "images": [], "audio_refs": ["7"],
                                      "prompt": "@audio1 plays"}).get_json()
    assert d2["cost"] == 27500 and d2.get("note") is None
    assert seen["params"]["referenceVideo"]["referenceAudioMediaIds"] == ["7"]


def test_price_route_threads_negative_and_channel(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "price_task", lambda s, params: seen.update(params=params) or 27500)
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, enrich=False: None)
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    cli.post("/api/price", json={"mode": "I2V", "images": ["55"], "negative": "blurry",
                                 "is_private": True})
    assert seen["params"]["i2vPro"]["negativePrompts"] == "blurry"
    assert seen["params"]["isPrivate"] is True


def test_account_route_sums_cards_and_coverage(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "account_info", lambda s: {
        "quotaAmount": 330990, "tasks": {"totalCount": 4}, "followerCount": 30, "followingCount": 4})
    monkeypatch.setattr(core, "list_kaisuukens",
                        lambda s: [{"count": 16}, {"count": 34}, {"count": None}])
    # 2 distinct local tasks (tA on two media, tB) out of 4 on the server -> 50% coverage
    cli = _authed_client(tmp_path, [
        _row(media_id="1", task_id="tA", filename="a_1.png", created_at="2025-01-01T00:00:00"),
        _row(media_id="2", task_id="tA", filename="b_2.png", created_at="2025-01-02T00:00:00"),
        _row(media_id="3", task_id="tB", filename="c_3.png", created_at="2025-01-03T00:00:00"),
    ])
    d = cli.get("/api/account").get_json()
    assert d["credits"] == 330990 and d["cards"] == 50
    assert d["server_tasks"] == 4 and d["local_tasks"] == 2 and d["coverage_pct"] == 50.0
    assert d["followers"] == 30 and d["following"] == 4


def test_snippets_roundtrip_and_persist(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    assert cli.get("/api/snippets").get_json() == {"snippets": []}
    saved = cli.post("/api/snippets",
                     json={"snippets": ["masterpiece, 4k", "", "  ", "night"]}).get_json()
    assert saved == {"snippets": ["masterpiece, 4k", "night"]}   # blanks dropped
    # Per-account storage (D-7): the file lives under prompt_snippets/<key>.json now,
    # not the old flat prompt_snippets.json every account used to share. Keyed via
    # _account_key (B14 residual), not the raw username.
    assert (tmp_path / "prompt_snippets" / (_account_key("tester") + ".json")).exists()
    assert cli.get("/api/snippets").get_json() == {"snippets": ["masterpiece, 4k", "night"]}


def test_snippets_rejects_non_list(tmp_path):
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    assert cli.post("/api/snippets", json={"snippets": "nope"}).status_code == 400


def test_one_account_cannot_see_or_clobber_anothers_snippets(tmp_path):
    """Same split saved views already got (test_view_presets.py), same reason: prompt
    snippets were install-wide (one shared prompt_snippets.json), so any signed-in
    account could read AND wholesale-overwrite every other account's saved snippets."""
    from moonglade_gallery import create_app
    from tests.conftest import login_test_client
    app = create_app(tmp_path)

    alice = login_test_client(app, username="alice", password="a-real-test-password-1")
    alice.post("/api/snippets", json={"snippets": ["alice-only"]})

    bob = login_test_client(app, username="bob", password="a-real-test-password-2")
    assert bob.get("/api/snippets").get_json()["snippets"] == [], (
        "bob can see alice's snippets -- the store is not per-account")

    bob.post("/api/snippets", json={"snippets": ["bob-only"]})
    assert bob.get("/api/snippets").get_json()["snippets"] == ["bob-only"]
    assert alice.get("/api/snippets").get_json()["snippets"] == ["alice-only"], (
        "bob's save wiped alice's snippets -- the store is not per-account")


def test_snippets_are_independent_for_accounts_differing_only_by_case(tmp_path):
    """B14 residual: _snips_path() keyed its per-account file with quote(username,
    safe=""), which is case-PRESERVING -- "Nel" and "nel" quote to two different
    strings that name the SAME file on NTFS (case-insensitive-but-preserving), even
    though account identity is case-SENSITIVE (same alice/bob split as above, just
    unlucky enough to collide on disk). FAILS before the fix on this filesystem:
    nel's snippets read/save clobbers Nel's."""
    from moonglade_gallery import create_app
    from tests.conftest import login_test_client
    app = create_app(tmp_path)

    upper = login_test_client(app, username="Nel", password="a-real-test-password-1")
    upper.post("/api/snippets", json={"snippets": ["Nel-only"]})

    lower = login_test_client(app, username="nel", password="a-real-test-password-2")
    assert lower.get("/api/snippets").get_json()["snippets"] == [], (
        "nel can see Nel's snippets -- case-differing usernames collide on disk")

    lower.post("/api/snippets", json={"snippets": ["nel-only"]})
    assert lower.get("/api/snippets").get_json()["snippets"] == ["nel-only"]
    assert upper.get("/api/snippets").get_json()["snippets"] == ["Nel-only"], (
        "nel's save overwrote Nel's snippets -- case-collision on disk")


def test_gallery_model_preview_hover_is_debounced_not_instant(tmp_path):
    """D-11 fix, originally landed as the gallery's OWN scheduleShowPreview/cancelPreview
    (a raw mouseenter re-triggered an instant, freshly-repositioned popup on every card the
    mouse passed over while scanning the grid). O12 (Phase 2) moved the whole search-grid
    -- including this debounce -- into the shared <mg-model-picker> component, so the
    gallery gets the fix by LOADING that component now, not by hand-rolling its own copy.
    This is fundamentally a feel/timing bug (real verification is manual, in a browser) --
    this only guards against a future edit reverting to raw, un-debounced wiring, wherever
    that wiring now lives."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "/static/mg-model-picker.js" in html   # the gallery's own grid IS this component now
    # The old hand-rolled copy must be gone, not just superseded -- two independently-
    # debounced implementations is exactly the kind of drift this migration exists to end.
    assert "function scheduleShowPreview(" not in html
    assert "function cancelPreview(" not in html

    picker_js = (Path(__file__).resolve().parents[1] / "static" / "mg-model-picker.js").read_text(encoding="utf-8")
    assert "c.addEventListener('mouseenter', function () { self._schedulePreview(m, c); });" in picker_js
    assert "_schedulePreview(m, anchor) {" in picker_js
    assert "_cancelPreview() {" in picker_js


def test_account_without_its_own_file_still_sees_legacy_shared_snippets(tmp_path):
    """Upgrade path: nothing disappears the moment the store goes per-account. An
    account with no file of its own falls back to the old shared prompt_snippets.json
    (read-only) -- exactly what it saw before the split -- and diverges on first save."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    (tmp_path / "prompt_snippets.json").write_text(
        json.dumps(["from-before"]), encoding="utf-8")

    assert cli.get("/api/snippets").get_json() == {"snippets": ["from-before"]}

    cli.post("/api/snippets", json={"snippets": ["from-before", "new-one"]})
    own = json.loads((tmp_path / "prompt_snippets" / (_account_key("tester") + ".json"))
                     .read_text(encoding="utf-8"))
    assert own == ["from-before", "new-one"]
    assert json.loads((tmp_path / "prompt_snippets.json").read_text(encoding="utf-8")) == ["from-before"]


def test_suggest_prompt_route(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "suggest_prompt", lambda s, mid: ["1girl, night", "a girl at night"])
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    assert cli.get("/api/suggest-prompt?media_id=55").get_json() == {
        "suggestions": ["1girl, night", "a girl at night"]}
    assert cli.get("/api/suggest-prompt").status_code == 400   # no media_id


def test_rows_for_media_ids_preserves_order_drops_missing():
    import moonglade_gallery as g

    class FakeCon:
        def execute(self, sql, params):
            rows = [{"media_id": p, "rating": "0"} for p in params if p != "99"]
            return type("C", (), {"fetchall": lambda self: rows})()

        def close(self):
            pass

    import unittest.mock as mock
    with mock.patch.object(g, "_connect", return_value=FakeCon()):
        rows = g.rows_for_media_ids("db", ["3", "1", "99", "2"])
    assert [r["media_id"] for r in rows] == ["3", "1", "2"]   # order kept, 99 dropped


def test_contact_sheet_renders_selection(tmp_path):
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-02T00:00:00", rating="3"),
        _row(media_id="2", filename="b_2.png", created_at="2025-01-01T00:00:00"),
    ])
    html = cli.get("/contact-sheet?ids=2,1").get_data(as_text=True)
    # both cells present, selection order (2 then 1), stars for the rated one, auto-print
    assert html.index("/thumbs/2.jpg") < html.index("/thumbs/1.jpg")
    assert "★★★" in html and "window.print()" in html


def test_contact_sheet_captions_off(tmp_path):
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-02T00:00:00", rating="3")])
    html = cli.get("/contact-sheet?ids=1&captions=0").get_data(as_text=True)
    assert "class='cap'" not in html


def test_contact_sheet_photo_and_strip(tmp_path):
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00"),
        _row(media_id="2", filename="b_2.png", created_at="2025-01-02T00:00:00"),
    ])
    photo = cli.get("/contact-sheet?ids=1&format=photo").get_data(as_text=True)
    assert "size:4in 6in" in photo and "/full/1" in photo
    strip = cli.get("/contact-sheet?ids=1,2&format=strip").get_data(as_text=True)
    # two identical strips (for cutting), frames cycle to fill four
    assert strip.count("class='strip'") == 2
    assert strip.count("/full/1") == 4 and strip.count("/full/2") == 4


def test_loom_handoff_extracts_and_uploads(tmp_path, monkeypatch):
    """Frame handoff: find the shot's clip -> extract last frame -> upload -> media_id."""
    import moonglade_gallery as g
    (tmp_path / "videos").mkdir()
    clip = tmp_path / "videos" / "shot_V9.mp4"
    clip.write_bytes(b"fake")

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    seen = {}

    def fake_extract(vp, out, at_seconds=None):
        seen["video"] = vp
        seen["at"] = at_seconds
        with open(out, "wb") as fh:      # simulate a produced frame
            fh.write(b"png")
        return out
    monkeypatch.setattr(core, "extract_last_frame", fake_extract)
    monkeypatch.setattr(core, "upload_media", lambda s, p: "FRAME123")
    monkeypatch.setattr(core, "probe_video_duration", lambda p: 5.0)

    cli = _authed_client(tmp_path, [_row(media_id="V9", filename="videos/shot_V9.mp4",
                                  is_video="1", created_at="2025-01-01T00:00:00")])
    d = cli.post("/api/loom/handoff", json={"video_media_id": "V9"}).get_json()
    assert d == {"frame_media_id": "FRAME123", "duration": 5.0}
    assert seen["video"].endswith("shot_V9.mp4")
    assert seen["at"] is None            # no trim_out -> take the clip's true last frame


def test_loom_handoff_is_trim_aware(tmp_path, monkeypatch):
    """A trimmed previous shot must hand off the frame at its trimOut (the point the cut
    ends on), not the untrimmed clip's real final frame -- else the continuity chain shows
    a frame the edit never plays."""
    import moonglade_gallery as g
    (tmp_path / "videos").mkdir()
    clip = tmp_path / "videos" / "shot_V9.mp4"
    clip.write_bytes(b"fake")

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    seen = {}

    def fake_extract(vp, out, at_seconds=None):
        seen["at"] = at_seconds
        with open(out, "wb") as fh:
            fh.write(b"png")
        return out
    monkeypatch.setattr(core, "extract_last_frame", fake_extract)
    monkeypatch.setattr(core, "upload_media", lambda s, p: "FRAME123")
    monkeypatch.setattr(core, "probe_video_duration", lambda p: 5.0)

    cli = _authed_client(tmp_path, [_row(media_id="V9", filename="videos/shot_V9.mp4",
                                  is_video="1", created_at="2025-01-01T00:00:00")])
    d = cli.post("/api/loom/handoff", json={"video_media_id": "V9", "trim_out": 3.2}).get_json()
    assert d == {"frame_media_id": "FRAME123", "duration": 5.0}
    assert seen["at"] == 3.2             # the trimOut reached ffmpeg


def test_loom_handoff_needs_local_clip(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    cli = _authed_client(tmp_path, [_row(media_id="X", filename="a_x.png",
                                  created_at="2025-01-01T00:00:00")])
    d = cli.post("/api/loom/handoff", json={"video_media_id": "nope"}).get_json()
    assert "not downloaded" in d["error"]


def test_loom_handoff_ignores_deleted_quarantine(tmp_path, monkeypatch):
    """B17 (audit 2026-07-21): the fallback resolver's bare '*<mid>.*' glob had no
    quarantine exclusion -- a file under _deleted/ (a local purge) was a valid hit,
    so a purged clip could be extracted and uploaded to seed the next (paid) shot.
    No catalog row for this media_id, so the fast path can't shortcut past the
    fallback -- this exercises exactly the buggy branch."""
    import moonglade_gallery as g
    qdir = tmp_path / g.DELETED_DIRNAME
    qdir.mkdir()
    (qdir / "shot_V9.mp4").write_bytes(b"fake")

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    calls = []
    monkeypatch.setattr(core, "extract_last_frame", lambda *a, **k: calls.append(a) or None)

    cli = _authed_client(tmp_path, [])
    d = cli.post("/api/loom/handoff", json={"video_media_id": "V9"}).get_json()

    assert calls == [], "extracted a frame from a file quarantined under _deleted/"
    assert "not downloaded" in d["error"]


def test_loom_handoff_requires_exact_media_id_match(tmp_path, monkeypatch):
    """B17 (audit 2026-07-21): the fallback glob had no media_id_of(p) == mid check,
    so a SHORTER media_id could match as a substring of a longer, UNRELATED one's
    filename -- e.g. a request for 'V9' resolving to a clip whose real id is '9V9'."""
    import moonglade_gallery as g
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "other_9V9.mp4").write_bytes(b"fake")   # real media_id is "9V9"

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    calls = []
    monkeypatch.setattr(core, "extract_last_frame", lambda *a, **k: calls.append(a) or None)

    cli = _authed_client(tmp_path, [])
    d = cli.post("/api/loom/handoff", json={"video_media_id": "V9"}).get_json()

    assert calls == [], "matched a DIFFERENT media_id's file via a substring collision"
    assert "not downloaded" in d["error"]


def test_loom_video_duration_probes_local_file(tmp_path, monkeypatch):
    """Footage-import fallback: when the catalog's own video_duration column is blank
    (older row, or a request-duration that was never captured), the Footage tab probes
    the real local file via ffprobe instead of leaving an imported clip's length wrong."""
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "shot_V9.mp4").write_bytes(b"fake")
    monkeypatch.setattr(core, "probe_video_duration", lambda p: 7.25)

    cli = _authed_client(tmp_path, [_row(media_id="V9", filename="videos/shot_V9.mp4",
                                  is_video="1", created_at="2025-01-01T00:00:00")])
    d = cli.get("/api/loom/video-duration?media_id=V9").get_json()
    assert d == {"duration": 7.25}


def test_loom_video_duration_requires_media_id(tmp_path):
    cli = _authed_client(tmp_path, [])
    r = cli.get("/api/loom/video-duration")
    assert r.status_code == 400
    assert r.get_json()["duration"] is None


def test_loom_video_duration_missing_file_is_a_soft_miss_not_a_500(tmp_path):
    """No catalog row and no file on disk -- a legitimate miss (e.g. a media_id from
    another machine's catalog), not a server error; the client falls back to its own
    default duration rather than being told to retry."""
    cli = _authed_client(tmp_path, [])
    r = cli.get("/api/loom/video-duration?media_id=nope")
    assert r.status_code == 200
    d = r.get_json()
    assert d["duration"] is None
    assert "not found" in d["error"]


def test_loom_video_duration_ignores_deleted_quarantine(tmp_path, monkeypatch):
    """Same B17 quarantine contract as /api/loom/handoff (shared resolver,
    _find_local_video_file): a file sitting under _deleted/ must not be probed as if
    it were a live survivor."""
    import moonglade_gallery as g
    qdir = tmp_path / g.DELETED_DIRNAME
    qdir.mkdir()
    (qdir / "shot_V9.mp4").write_bytes(b"fake")
    calls = []
    monkeypatch.setattr(core, "probe_video_duration", lambda p: calls.append(p) or 9.0)

    cli = _authed_client(tmp_path, [])
    d = cli.get("/api/loom/video-duration?media_id=V9").get_json()
    assert calls == [], "probed a file quarantined under _deleted/"
    assert d["duration"] is None


def test_loom_video_duration_requires_login(tmp_path):
    cli = _client(tmp_path, [_row(media_id="V9", filename="videos/shot_V9.mp4",
                                   is_video="1", created_at="2025-01-01T00:00:00")])
    r = cli.get("/api/loom/video-duration?media_id=V9")
    assert r.status_code == 401


def test_gen_reference_image_passthrough():
    """Capture #14 (task 2030052367400863154): 'use as reference' = plain img2img,
    a top-level mediaId + strength on a standard submit."""
    from types import SimpleNamespace
    a = SimpleNamespace(params_json="", prompt="p", negative="", model="m",
                        width=512, height=512, steps=25, cfg=7, count=1,
                        priority=500, mode="auto", seed=None, lora=[],
                        prompt_helper=True, kaisuuken_id="",
                        ref_media_id="739707411648019153", ref_strength=0.55)
    p = core._gen_parameters(a)
    assert p["mediaId"] == "739707411648019153" and p["strength"] == 0.55
    a.ref_media_id = ""
    p2 = core._gen_parameters(a)
    assert "mediaId" not in p2 and "strength" not in p2   # absent when no ref


def test_edit_scene_id_passthrough():
    """Capture #13 (task 2030050946353349700): a Toolbox preset = the normal chat
    block + a canned prompt + top-level sceneId."""
    p = core.build_chat_edit_parameters("canned prompt", ["55"],
                                        scene_id="character-card")
    assert p["sceneId"] == "character-card" and p["chat"]["prompts"] == "canned prompt"
    assert "sceneId" not in core.build_chat_edit_parameters("x", ["55"])


def test_presets_import_and_use(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "task_detail_gql", lambda s, tid: {
        "parameters": {"sceneId": "character-card",
                       "chat": {"prompts": "BIG CANNED PROMPT",
                                "modelId": "1948514378441961474"}}})
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    d = cli.post("/api/presets", json={"task_id": "2030050946353349700"}).get_json()
    assert d["imported"] == "character-card"
    lst = cli.get("/api/presets").get_json()["presets"]
    assert lst["character-card"]["label"] == "Character Card"
    assert "prompt" not in lst["character-card"]          # GET never leaks the prompt body
    # price path uses the banked preset: canned prompt + sceneId + its model
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "price_task", lambda s, params: seen.update(p=params) or 8000)
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, enrich=False: None)
    cli.post("/api/price", json={"mode": "edit", "source": "55",
                                 "preset": "character-card"})
    assert seen["p"]["sceneId"] == "character-card"
    assert seen["p"]["chat"]["prompts"] == "BIG CANNED PROMPT"
    assert seen["p"]["chat"]["modelId"] == "1948514378441961474"


def test_one_account_cannot_see_or_clobber_anothers_presets(tmp_path, monkeypatch):
    """Same split saved views/snippets/Loom storyboards already got: Toolbox presets
    were install-wide (one shared toolbox_presets.json), so any signed-in account
    could read AND wholesale-overwrite every other account's imported presets."""
    from moonglade_gallery import create_app
    from tests.conftest import login_test_client
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "task_detail_gql", lambda s, tid: {
        "parameters": {"sceneId": "alice-scene",
                       "chat": {"prompts": "ALICE PROMPT", "modelId": "1"}}})
    app = create_app(tmp_path)

    alice = login_test_client(app, username="alice", password="a-real-test-password-1")
    d = alice.post("/api/presets", json={"task_id": "111"}).get_json()
    assert d["imported"] == "alice-scene"

    bob = login_test_client(app, username="bob", password="a-real-test-password-2")
    assert bob.get("/api/presets").get_json()["presets"] == {}, (
        "bob can see alice's presets -- the store is not per-account")

    monkeypatch.setattr(core, "task_detail_gql", lambda s, tid: {
        "parameters": {"sceneId": "bob-scene",
                       "chat": {"prompts": "BOB PROMPT", "modelId": "2"}}})
    bob.post("/api/presets", json={"task_id": "222"})
    assert set(bob.get("/api/presets").get_json()["presets"]) == {"bob-scene"}
    assert set(alice.get("/api/presets").get_json()["presets"]) == {"alice-scene"}, (
        "bob's save wiped alice's presets -- the store is not per-account")


def test_presets_are_independent_for_accounts_differing_only_by_case(tmp_path, monkeypatch):
    """B14 residual: toolbox_presets was the most recently split store, and it copied
    _view_presets_path's exact quote(username, safe="") keying -- inheriting the same
    case-collision bug. FAILS before the fix on this filesystem: nel's presets
    read/save clobbers Nel's."""
    from moonglade_gallery import create_app
    from tests.conftest import login_test_client
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "task_detail_gql", lambda s, tid: {
        "parameters": {"sceneId": "upper-scene",
                       "chat": {"prompts": "UPPER PROMPT", "modelId": "1"}}})
    app = create_app(tmp_path)

    upper = login_test_client(app, username="Nel", password="a-real-test-password-1")
    upper.post("/api/presets", json={"task_id": "111"})

    lower = login_test_client(app, username="nel", password="a-real-test-password-2")
    assert lower.get("/api/presets").get_json()["presets"] == {}, (
        "nel can see Nel's presets -- case-differing usernames collide on disk")

    monkeypatch.setattr(core, "task_detail_gql", lambda s, tid: {
        "parameters": {"sceneId": "lower-scene",
                       "chat": {"prompts": "LOWER PROMPT", "modelId": "2"}}})
    lower.post("/api/presets", json={"task_id": "222"})
    assert set(lower.get("/api/presets").get_json()["presets"]) == {"lower-scene"}
    assert set(upper.get("/api/presets").get_json()["presets"]) == {"upper-scene"}, (
        "nel's save wiped Nel's presets -- case-collision on disk")


def test_account_without_its_own_file_still_sees_legacy_shared_presets(tmp_path, monkeypatch):
    """Upgrade path: nothing disappears the moment the store goes per-account. An
    account with no file of its own falls back to the old shared toolbox_presets.json
    (read-only) -- exactly what it saw before the split -- and diverges on first save."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "task_detail_gql", lambda s, tid: {
        "parameters": {"sceneId": "new-scene",
                       "chat": {"prompts": "NEW PROMPT", "modelId": "3"}}})
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    (tmp_path / "toolbox_presets.json").write_text(
        json.dumps({"from-before": {"label": "From Before", "scene_id": "",
                                    "prompt": "x", "model_id": "9"}}),
        encoding="utf-8")

    assert set(cli.get("/api/presets").get_json()["presets"]) == {"from-before"}

    cli.post("/api/presets", json={"task_id": "333"})
    own = json.loads((tmp_path / "toolbox_presets" / (_account_key("tester") + ".json"))
                     .read_text(encoding="utf-8"))
    assert set(own) == {"from-before", "new-scene"}
    legacy = json.loads((tmp_path / "toolbox_presets.json").read_text(encoding="utf-8"))
    assert set(legacy) == {"from-before"}


def test_redaction_does_not_over_redact_when_out_dir_is_a_relative_path(tmp_path, monkeypatch):
    """Caught in adversarial review: --out defaults to a relative "pixai_backup" and
    main() never resolves it before create_app(out_dir). Unresolved, str(out_dir) for
    an out_dir given as "." (the exact scenario `--out .` produces) is a bare, generic
    1-character string -- which then matches, and redacts, every single period in
    every error message app-wide (a real, reproduced bug: an ordinary "retry in 0.5s"
    style message came back full of "<host-path>" fragments instead of the real
    diagnostic text). monkeypatch.chdir makes tmp_path itself the cwd so Path(".")
    genuinely IS out_dir, exactly like a real `--out .` invocation -- a relative Path
    built any other way (e.g. os.path.relpath) is normally a long, specific string and
    would not actually reproduce this.

    Bite: change _redact_host_paths back to using str(out_dir) instead of
    str(Path(out_dir).resolve()) and this fails -- the periods in the message below
    get eaten."""
    monkeypatch.chdir(tmp_path)
    out_dir = Path(".")
    save_catalog(out_dir / "catalog.db", [_row(media_id="1", filename="a_1.png",
                                          created_at="2025-01-01T00:00:00")])
    cli = login_client(out_dir)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())

    def boom(*a, **k):
        raise RuntimeError("retry in 0.5s. version 2.1.0. see release notes.")
    monkeypatch.setattr(core, "list_contests", boom)

    r = cli.get("/api/contests")
    body = r.get_data(as_text=True)
    assert "<host-path>" not in body
    assert "retry in 0.5s. version 2.1.0. see release notes." in body


def test_error_responses_redact_host_paths_even_with_a_space_in_the_directory_name(tmp_path, monkeypatch):
    """The re-spin of the redaction an earlier attempt got REJECTED for (2026-07-21,
    docs/AUDIT_2026-07-21.md S3): a regex-based version stopped matching at the first
    whitespace, so a spaced Windows username/directory (`C:\\Users\\John Smith\\...`)
    still leaked into an error response in full -- exactly the harm this exists to
    close. out_dir here deliberately has a space in it, not a convenient unspaced tmp
    dir, so this actually exercises that failure mode instead of dodging it.

    Also proves longest-candidate-first: pytest's own tmp_path is itself a real
    subdirectory of tempfile.gettempdir() on this machine, so out_dir is naturally
    NESTED under a second, shorter redaction candidate. If the shorter candidate fired
    first, only the tempdir prefix would be replaced, leaving "...\\John Smith\\..."
    still exposed right after the placeholder -- this test would still catch that.

    Bite: replace _redact_host_paths's body with `return msg` (a no-op) and this fails."""
    out_dir = tmp_path / "John Smith" / "pixai_backup"
    out_dir.mkdir(parents=True)
    save_catalog(out_dir / "catalog.db", [_row(media_id="1", filename="a_1.png",
                                          created_at="2025-01-01T00:00:00")])
    cli = login_client(out_dir)

    def boom(*a, **k):
        raise RuntimeError("could not read {}\\config.json: permission denied".format(out_dir))
    monkeypatch.setattr(core, "_make_session", boom)

    r = cli.post("/api/price", json={"model_id": "1", "prompt": "x"})
    body = r.get_data(as_text=True)
    assert str(out_dir) not in body
    assert "John Smith" not in body
    assert "<host-path>" in body


def test_redaction_covers_a_second_independent_call_site(tmp_path, monkeypatch):
    """The sweep touched 37 sites across the file, not one -- prove a SECOND,
    differently-shaped site (different local variable names, different sibling JSON
    keys) got the same treatment, not just the one this file happens to exercise most.
    (The spaced-directory regression itself is covered above; this one just needs a
    real redaction candidate, so it reuses out_dir rather than an unrelated path that
    would never actually appear in a real error message.)"""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())

    def boom(*a, **k):
        raise RuntimeError("upstream call failed, see {}\\log.txt".format(tmp_path))
    monkeypatch.setattr(core, "list_contests", boom)

    r = cli.get("/api/contests")
    body = r.get_data(as_text=True)
    assert str(tmp_path) not in body
    assert "<host-path>" in body


def test_redaction_is_case_insensitive_because_windows_paths_are(tmp_path, monkeypatch):
    """`_redact_host_paths` matched with `str.replace`, which is case-SENSITIVE, while the
    paths it is redacting live on a case-INSENSITIVE filesystem. A third-party library or a
    normalized OS string can hand back the same directory in a different case (Users vs
    users, drive letter either way), and the exact-case check silently misses it, shipping the real
    host path and the OS username to a LAN caller while the guard reports success.

    Bite: revert the matching to `path in out` / `out.replace(path, ...)` and this fails."""
    out_dir = tmp_path / "Jane Smith" / "pixai_backup"
    out_dir.mkdir(parents=True)
    save_catalog(out_dir / "catalog.db", [_row(media_id="1", filename="a_1.png",
                                          created_at="2025-01-01T00:00:00")])
    cli = login_client(out_dir)

    # the SAME directory, spelled in a different case -- what a normalizing library returns
    shouty = str(out_dir).upper()

    def boom(*a, **k):
        raise RuntimeError("could not read {}\\config.json: permission denied".format(shouty))
    monkeypatch.setattr(core, "_make_session", boom)

    body = cli.post("/api/price", json={"model_id": "1", "prompt": "x"}).get_data(as_text=True)
    assert "JANE SMITH" not in body, "upper-cased host path leaked verbatim: " + body[:300]
    assert "<host-path>" in body


def test_redaction_catches_a_slash_flipped_windows_path(tmp_path, monkeypatch):
    """Same failure mode, second real variant: plenty of libraries hand back a Windows path
    with forward slashes (`C:/Users/...`). That is the same directory and must redact too --
    an exact-substring match against the backslash spelling never sees it."""
    out_dir = tmp_path / "Jane Smith" / "pixai_backup"
    out_dir.mkdir(parents=True)
    save_catalog(out_dir / "catalog.db", [_row(media_id="1", filename="a_1.png",
                                          created_at="2025-01-01T00:00:00")])
    cli = login_client(out_dir)
    flipped = str(out_dir).replace("\\", "/")

    def boom(*a, **k):
        raise RuntimeError("could not read {}/config.json: denied".format(flipped))
    monkeypatch.setattr(core, "_make_session", boom)

    body = cli.post("/api/price", json={"model_id": "1", "prompt": "x"}).get_data(as_text=True)
    assert "Jane Smith" not in body, "slash-flipped host path leaked: " + body[:300]
    assert "<host-path>" in body


def test_redaction_still_does_not_eat_ordinary_messages(tmp_path, monkeypatch):
    """The degenerate-candidate guard must survive the case-insensitive rewrite: an ordinary
    message containing no host path at all comes back untouched. This is the regression the
    length floor and the resolve() both exist for -- a looser matcher is exactly how that
    class of bug returns."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())

    def boom(*a, **k):
        raise RuntimeError("upstream said: retry in 0.5s (attempt 2 of 3)")
    monkeypatch.setattr(core, "list_contests", boom)

    body = cli.get("/api/contests").get_data(as_text=True)
    assert "<host-path>" not in body, "redacted an ordinary message: " + body[:300]
    assert "retry in 0.5s" in body


def test_catalog_counts(tmp_path):
    import moonglade_gallery as g
    g.save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00",
             collections="faves,wips"),
        _row(media_id="2", filename="b_2.png", created_at="2025-01-02T00:00:00",
             collections="faves"),
        _row(media_id="3", filename="c_3.mp4", is_video="1", created_at="2025-01-03T00:00:00"),
    ])
    c = g.catalog_counts(tmp_path / "catalog.db")
    assert c == {"images": 2, "videos": 1, "collections": 2}   # faves + wips distinct


def test_distinct_task_count(tmp_path):
    import moonglade_gallery as g
    g.save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", task_id="tA", filename="a_1.png", created_at="2025-01-01T00:00:00"),
        _row(media_id="2", task_id="tA", filename="b_2.png", created_at="2025-01-02T00:00:00"),  # same task (batch)
        _row(media_id="3", task_id="tB", filename="c_3.png", created_at="2025-01-03T00:00:00"),
        _row(media_id="4", task_id="",   filename="d_4.png", created_at="2025-01-04T00:00:00"),  # no task id
    ])
    # 2 distinct tasks (tA, tB); the batch-sibling and the empty task_id don't inflate it
    assert g.distinct_task_count(tmp_path / "catalog.db") == 2


_CONTEST_PAGES = {
    1: {"data": [
        {"id": "1", "title": {"en": "Summer Embers", "zh": "x"}, "slug": "pixai-summer-embers",
         "type": "official", "runtimeStatus": "running", "voteType": "creator_pick",
         "prizeAmount": 29000000, "mediaId": "M1", "startAt": "2026-06-26T00:00:00Z",
         "endAt": "2026-07-06T00:00:00Z", "prizeDistribution": [{"rank": 1, "count": 1, "amount": 100}]},
        {"id": "2", "title": {"en": "Rookie Contest"}, "slug": "user-rookie", "type": "community",
         "runtimeStatus": "running", "prizeAmount": 100000, "mediaId": "M2",
         "startAt": "2026-06-29T00:00:00Z", "endAt": "2026-07-10T00:00:00Z"},
        {"id": "3", "title": {"en": "Old One"}, "slug": "user-old", "type": "community",
         "runtimeStatus": "ended", "prizeAmount": 5000, "mediaId": "", "endAt": "2026-05-01T00:00:00Z"},
    ], "page": 1, "pageSize": 50, "totalPage": 2, "totalCount": 4},
    2: {"data": [
        {"id": "4", "title": {"en": "Page-2 Live"}, "slug": "user-p2", "type": "community",
         "runtimeStatus": "running", "prizeAmount": 0, "mediaId": "M4", "endAt": "2026-08-01T00:00:00Z"},
    ], "page": 2, "pageSize": 50, "totalPage": 2, "totalCount": 4},
}


def test_list_contests_normalizes_and_pages(monkeypatch):
    seen = []
    def fake_get(s, path, params=None, **k):
        seen.append((path, params.get("page")))
        return _CONTEST_PAGES[params["page"]]
    monkeypatch.setattr(core, "_rest_get", fake_get)
    # active_only walks BOTH pages (a running contest hides on page 2) and keeps only 'running'
    active = core.list_contests(object(), active_only=True)
    assert [c["id"] for c in active] == ["1", "2", "4"]      # the 'ended' one dropped, page-2 kept
    assert ("/contest/list", 2) in seen                      # paged through
    c0 = active[0]
    assert c0["title"] == "Summer Embers" and c0["type"] == "official" and c0["active"] is True
    assert c0["url"] == "https://pixai.art/en/contest/pixai-summer-embers"
    assert c0["cover_url"] == "https://api.pixai.art/v1/media/M1/thumbnail"
    assert c0["prize_amount"] == 29000000
    # all -> the ended one is included
    allc = core.list_contests(object(), active_only=False)
    assert any(c["id"] == "3" and c["active"] is False for c in allc)


def test_api_contests_route(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_rest_get",
                        lambda s, path, params=None, **k: _CONTEST_PAGES[params["page"]])
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    d = cli.get("/api/contests").get_json()             # default = active only
    assert d["official"] == 1 and d["community"] == 2   # 1 official + 2 running community
    assert all(c["active"] for c in d["contests"])


def test_your_art_ranks_published_and_enriches_views(tmp_path, monkeypatch):
    import moonglade_gallery as g
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    # views come from a per-artwork call; mock it deterministically off the artwork_id
    monkeypatch.setattr(core, "artwork_views", lambda s, aid: {"aw1": 500, "aw2": 90}.get(aid, 0))
    cli = _authed_client(tmp_path, [
        _row(media_id="1", artwork_id="aw1", filename="a_1.png", is_published="1",
             liked_count="4", comment_count="2", created_at="2025-01-01T00:00:00"),
        _row(media_id="2", artwork_id="aw2", filename="b_2.png", is_published="1",
             liked_count="40", comment_count="0", created_at="2025-01-02T00:00:00"),
        _row(media_id="3", filename="c_3.png", is_published="",  # not published -> excluded
             liked_count="99", created_at="2025-01-03T00:00:00"),
    ])
    # pure helpers
    assert [r["media_id"] for r in g.top_published_rows(tmp_path / "catalog.db")] == ["2", "1"]  # by likes
    assert g.published_totals(tmp_path / "catalog.db") == {"count": 2, "likes": 44, "comments": 2}
    # route: localhost -> enriched with views, re-sorted by views (aw1=500 > aw2=90)
    d = cli.get("/api/your-art").get_json()
    assert d["views_synced"] is True and d["totals"]["count"] == 2
    assert [m["media_id"] for m in d["items"]] == ["1", "2"]     # aw1 (500 views) now first
    assert d["items"][0]["views"] == 500


def test_artwork_views_route(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "artwork_views", lambda s, aid: 174)
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    assert cli.get("/api/artwork-views?id=aw9").get_json() == {"views": 174}
    assert cli.get("/api/artwork-views").get_json()["views"] is None   # missing id -> 400/null


def test_unauthenticated_lan_request_to_index_is_redirected_to_login(tmp_path):
    """Before the LAN-auth front-door rewrite (2026-07-19), an unauthenticated LAN
    request to `/` rendered a stripped-down 'read-only LAN view' (owner-only controls
    hidden, a small banner shown instead) -- `/` had no gate of its own at all back
    then. That whole in-between tier is retired: `/` now carries no allowlist
    exemption from the global front-door hook (_enforce_front_door(), see
    moonglade_gallery.py's docstring), so an unauthenticated LAN request never reaches
    index() at all -- it's redirected to /login instead of rendering anything."""
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    r = cli.get("/", environ_overrides={"REMOTE_ADDR": "192.168.1.50"})
    assert r.status_code in (301, 302, 303, 307, 308)
    assert "/login" in r.headers["Location"]


def test_logged_in_lan_request_gets_the_same_full_ui_as_local(tmp_path):
    """A LAN request carrying a valid login session is authorized exactly like the
    local owner for the LOGIN-tier controls this test actually checks -- Generate/Loom,
    no read-only banner. There is only ONE access tier for THOSE once you're behind the
    front door (a logged-in session -- see index()'s `is_local=True` comment for why
    that template flag is now a hardcoded constant rather than a live check). Both
    views below are captured AFTER logging in: an unauthenticated LOCAL request no
    longer gets the full owner UI either (the loopback bypass is gone), so the only
    real distinction left to prove for LOGIN-tier controls is authenticated-vs-not,
    never the request's address -- see
    test_unauthenticated_lan_request_to_index_is_redirected_to_login for that side of
    the boundary. Community + browse surfaces (Contests / My Art) render either way,
    as before. NOT claimed identical here, deliberately: the header also renders a
    LOCALHOST-tier "^ Import" button, gated on the real `is_true_local` check rather
    than this shared LOGIN-tier flag -- see
    tests/test_route_tiers.py::test_index_withholds_the_import_button_from_a_lan_session
    for that control's own local-vs-LAN pair (docs/AUDIT_2026-07-21.md P3/S5-3,
    FIXED 2026-07-24)."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    html = cli.get("/login").get_data(as_text=True)
    csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    cli.post("/login", data={"username": "alice", "password": "hunter2", "csrf": csrf})
    localhost = cli.get("/").get_data(as_text=True)
    lan = cli.get("/", environ_overrides={"REMOTE_ADDR": "192.168.1.50"}).get_data(as_text=True)
    # The Generate button (btn-primary) + The Loom header link are owner-level controls.
    _loom = "video storyboard, where shots"   # unique to the header Loom link title (owner-only)
    assert _loom in localhost and "read-only LAN view" not in localhost
    assert _loom in lan and "read-only LAN view" not in lan
    # community + browse surfaces render on both
    for html in (localhost, lan):
        assert "Contests.open()" in html and "YourArt.open()" in html


def test_export_csv_downloads_as_attachment(tmp_path):
    """The web export is a real browser DOWNLOAD (attachment), not a file written into the
    backup folder. Authorized only (owner data)."""
    cli = _client(tmp_path, [
        _row(media_id="1", filename="a_1.png", prompt_preview="p1", created_at="2025-01-01T00:00:00"),
        _row(media_id="2", filename="b_2.png", prompt_preview="p2", created_at="2025-01-02T00:00:00"),
    ])
    # An unauthorized LAN device can't pull the owner's catalog -- sent to /login
    # (an HTML page route, so a redirect there rather than a bare 403 lets normal
    # browser navigation work cleanly). Checked FIRST, while `cli` is still anonymous.
    r2 = cli.get("/export-csv", environ_overrides={"REMOTE_ADDR": "192.168.1.9"})
    assert r2.status_code == 302
    assert r2.headers["Location"].startswith("/login")
    cli = login_existing_client(cli)
    r = cli.get("/export-csv")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    cd = r.headers.get("Content-Disposition", "")
    assert "attachment" in cd and ".csv" in cd          # downloads, doesn't render
    lines = r.get_data(as_text=True).splitlines()
    assert "media_id" in lines[0]                        # header row present
    assert sum(1 for ln in lines[1:] if ln.strip()) == 2  # both rows exported


def test_export_csv_honours_the_gallery_filters(tmp_path):
    """Export used to mean "the whole library" no matter what the grid was showing, so
    exporting a search gave you everything. It now reads the SAME filter args the index
    route does; a request with none of them still dumps the whole catalog."""
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.png", prompt_preview="night elf",
             model_name="WAI", rating="5", created_at="2025-01-01T00:00:00"),
        _row(media_id="2", filename="b_2.png", prompt_preview="daylight city",
             model_name="WAI", rating="1", created_at="2025-02-01T00:00:00"),
        _row(media_id="3", filename="c_3.png", prompt_preview="night market",
             model_name="Other", rating="3", created_at="2026-01-01T00:00:00"),
    ])

    import csv

    def ids(qs=""):
        r = cli.get("/export-csv" + qs)
        assert r.status_code == 200 and r.mimetype == "text/csv"
        rows = list(csv.DictReader(io.StringIO(r.get_data(as_text=True))))
        return {row["media_id"] for row in rows}

    assert ids() == {"1", "2", "3"}                          # no filters -> everything
    assert ids("?q=night") == {"1", "3"}                     # search
    assert ids("?model=WAI") == {"1", "2"}                   # dropdown filter
    assert ids("?q=night&model=WAI") == {"1"}                # filters combine, as in the grid
    assert ids("?rating_min=3") == {"1", "3"}                # numeric filter is validated, not raw
    assert ids("?from_year=2026") == {"3"}                   # Year dropdown with no Month
    assert ids("?q=nothingmatchesthis") == set()             # empty result is a header-only CSV


def test_grid_export_link_appears_only_when_filtered(tmp_path):
    """The filtered-export backend (above) shipped with no way to REACH it: the only CSV link
    lived on the Control Panel and always dumped the whole catalog. The gallery grid now grows
    an 'Export this view' link -- but ONLY inside the {% if chips %} active-filter bar, so an
    unfiltered grid still routes people to the Panel's full dump instead of a redundant one."""
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.png", prompt_preview="night elf", model_name="WAI",
             created_at="2025-01-01T00:00:00"),
        _row(media_id="2", filename="b_2.png", prompt_preview="daylight", model_name="WAI",
             created_at="2025-02-01T00:00:00"),
    ])
    plain = cli.get("/").get_data(as_text=True)
    assert "Export this view" not in plain and "/export-csv?" not in plain   # unfiltered: none
    filtered = cli.get("/?q=night").get_data(as_text=True)
    assert "Export this view" in filtered                                    # filtered: it shows
    assert "/export-csv?" in filtered and "q=night" in filtered              # carries the query


def test_grid_export_link_drives_the_filtered_export_end_to_end(tmp_path):
    """The link must carry the LIVE query string, so following it exports exactly the filtered
    view -- this proves the reachability wiring end to end, not just the backend (which its own
    test above already covers)."""
    import re
    import html as htmlmod
    import csv
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.png", prompt_preview="night elf", model_name="WAI",
             created_at="2025-01-01T00:00:00"),
        _row(media_id="2", filename="b_2.png", prompt_preview="daylight city", model_name="WAI",
             created_at="2025-02-01T00:00:00"),
        _row(media_id="3", filename="c_3.png", prompt_preview="night market", model_name="Other",
             created_at="2026-01-01T00:00:00"),
    ])
    grid = cli.get("/?q=night&model=WAI").get_data(as_text=True)
    m = re.search(r'href="(/export-csv\?[^"]+)"', grid)
    assert m, "filtered grid did not render an /export-csv link"
    href = htmlmod.unescape(m.group(1))          # Jinja escaped & -> &amp; in the attribute
    r = cli.get(href)
    assert r.status_code == 200 and r.mimetype == "text/csv"
    ids = {row["media_id"] for row in csv.DictReader(io.StringIO(r.get_data(as_text=True)))}
    assert ids == {"1"}                          # q=night AND model=WAI -> only row 1


def test_branding_absent_is_404(tmp_path):
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    assert cli.get("/branding/banner.png").status_code == 404      # onerror removes the img
    assert cli.get("/branding/../catalog.db").status_code == 404    # traversal rejected


def test_enhance_subtab_is_the_local_art_filters_surface(tmp_path):
    """The Enhance sub-tab is where art filters live, and they run entirely in the browser.

    Every control that submitted a `pixai-panelplugin` task is gone -- PixAI never dispatches
    one from an API key (see tests/test_enhance.py's test_no_panelplugin_submit_path_survives
    for the measurement) -- and so is the paid `pixai-image-filter` submit that used to be the
    other half of the same command. PixAI's seven art filters are gradient composites served
    from a public config endpoint, so the tab now applies them locally: no credits, no request.

    What must remain: the sub-tab button, the filters entry point, the flyout it opens, and a
    line saying which PixAI tools still only run on their own site. What must NOT: any element
    the deleted panelplugin JS addressed, and no route that would send a filter to a worker."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "Gen.setEditSub('enhance')" in html            # the tab itself survives
    assert 'id="edit-sub-enhance"' in html
    assert "pixai.art" in html                            # the pane says what does NOT run here
    # the local filters surface: the module, the entry point, and the side-by-side flyout
    assert '/static/mg-art-filters.js' in html
    assert 'Gen.toggleFilters()' in html
    assert 'id="filters-flyout"' in html
    for part in ('id="af-stage"', 'id="af-img"', 'id="af-swatches"', 'id="af-strength"',
                 'id="af-save"'):
        assert part in html, part + " is missing from the filters flyout"
    for dead in ('class="enh-shelf"', 'class="enh-card"', 'id="enh-q"', 'id="enh-list"',
                 'id="enh-go"', 'id="enh-result"', 'id="enh-selected"',
                 'id="enhance-cost"', "Gen.selectEnhance(", "Gen.runEnhance(",
                 "function selectEnhance", "function runEnhance", "function renderWorkflows",
                 "/api/workflows", "/api/enhance", "pixai-image-filter"):
        assert dead not in html, dead + " is still in the page"


def test_art_filters_flyout_is_a_comparison_and_placed_like_the_model_flyout(tmp_path):
    """Three properties of the filters panel that a plain "the ids are present" check misses.

    1. THREE COLUMNS, in order: the untouched original, the filtered preview, then the palette
       rail. Judging a filter is a COMPARISON -- with one image you had to toggle No filter
       back and forth and hold the difference in your head. The two pictures also have to be
       two distinct <img> elements: MgArtFilters mutates the preview's element (a CSS `filter`
       for image_parameters, overlay divs at inset:0), so anything sharing it would be filtered
       too and there would be nothing left to compare against.
    2. The image columns take an EXPLICIT flex-basis, never `auto`. From an `auto` basis a
       column's base size is the image's INTRINSIC width, which overflows the panel and makes
       flex-wrap drop the rail under the pictures at every width -- measured on the old
       two-column build, and the whole point of the panel is lost.
    3. Positioned by the in-repo overlay idiom, not a new one. #filters-flyout is a top-level
       fixed panel placed by JS (the same shape as #model-preview, which mg-model-picker's
       _place() drives) -- it must NOT be a child of #gen-drawer, because the drawer carries
       `transform: translateX(...)` and a transform makes its box the containing block for
       position:fixed descendants, so viewport coordinates computed from
       getBoundingClientRect() would land relative to the drawer instead.
    """
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    # (1) the layout rule, not just the markup
    assert "#filters-flyout .af-wrap{display:flex;" in html
    orig_at = html.index('id="af-orig"')
    stage_at = html.index('id="af-stage"')
    rail_at = html.index('id="af-swatches"')
    assert orig_at < stage_at < rail_at, (
        "column order must read original -> preview -> palette rail")
    assert html.count('id="af-orig"') == 1 and html.count('id="af-img"') == 1
    assert orig_at < html.index('id="af-img"'), (
        "the original must not live inside #af-stage -- the filter would be applied to it too")
    # (2) explicit basis on the growing columns, fixed width on the rail
    assert "#filters-flyout .af-col{flex:1 1 250px;" in html
    assert "#filters-flyout .af-rail{flex:0 0 236px;" in html
    # (3) fixed + JS-placed, and OUTSIDE the transformed drawer
    assert "#filters-flyout{position:fixed;" in html
    drawer_at = html.index('<aside id="gen-drawer"')
    drawer_end = html.index("</aside>", drawer_at)
    flyout_at = html.index('id="filters-flyout"')
    assert flyout_at > drawer_end, (
        "#filters-flyout is inside #gen-drawer, whose transform would capture its "
        "position:fixed coordinates")
    assert "function placeFilters(" in html


def test_art_filters_rail_groups_both_sets_and_offers_four_actions(tmp_path):
    """The rail is two headed sets, and the action row is the agreed four buttons.

    Ours lead because they are the house set; PixAI's follow. The grouping is not decoration --
    the sets do not behave alike (four of PixAI's seven use Photoshop whole-colour blend modes
    that CSS can only approximate, so their saved file differs from their preview; the
    Moonglade five are exact-only), and a tile's tooltip is where that is said.

    Publish is present but DISABLED: publishing to PixAI is Epic C and its mutation is
    deliberately not wired. Shown-with-a-reason rather than hidden, so the group matches the
    agreed layout instead of silently growing a fourth button later.
    """
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "AF.groups().forEach(" in html, "the rail must be built from the grouped API"
    assert ".af-grp{" in html and ".af-tiles{" in html
    for bid in ("af-none", "af-save", "af-send", "af-publish"):
        assert 'id="%s"' % bid in html, "missing action button: " + bid
    pub = html.index('id="af-publish"')
    assert "disabled" in html[pub:pub + 260], "Publish must ship disabled until Epic C lands"
    assert "Gen.filterSend()" in html and "filterSend:filterSend" in html


def test_art_filters_send_uploads_for_free_and_never_touches_the_local_import(tmp_path):
    """"Send to image gen" goes through /api/upload -- the free 3-step S3 handshake -- and
    hands the returned media_id to the Edit source.

    Two things this pins. It must NOT reuse /api/import-local: that route writes into the
    owner's library and returns no media_id, so an i2i path keyed on a media_id would get
    nothing. And it must not submit anything: the upload spends no credits, and the generation
    the drawer then runs is the priced step. A regression that made this button generate would
    charge for a button whose label says it only sends.
    """
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    body = html[html.index("function filterSend("):]
    body = body[:body.index("window.addEventListener('resize', placeFilters)")]
    assert "'/api/upload'" in body
    assert "import-local" not in body, "Send must not go through the library-import route"
    assert "/api/generate" not in body and "/api/edit" not in body, (
        "Send uploads only -- it must not submit a generation")
    assert "setEditSource(String(d.media_id))" in body


def test_filter_actions_close_the_panel_without_re_opening_it(tmp_path):
    """`toggleFilters()` is a TOGGLE, and both filter actions run across an await.

    Nothing disables the panel's own close paths while a request is in flight -- only the
    pressed button is disabled -- so the header's x, `#gen-scrim` and the unconditional
    global `Escape -> Gen.close()` all stay live. Calling the toggle blind on resolve
    therefore RE-OPENS a panel the user already dismissed, and `placeFilters()` then measures
    a drawer that has slid away (`transform:translateX(100%)`), landing the panel over the
    gallery with nothing behind it -- the exact state `Gen.close()` exists to prevent.

    So the resolve handlers must go through `closeFiltersIfOpen()`, which checks `.open`
    first, and must never call `toggleFilters()` directly.
    """
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "function closeFiltersIfOpen(" in html
    guard = html[html.index("function closeFiltersIfOpen("):]
    guard = guard[:guard.index("function afActing(")]
    assert "classList.contains('open')" in guard, (
        "closeFiltersIfOpen must check the panel is open before toggling it")

    for fn in ("function filterSave(", "function filterSend("):
        body = html[html.index(fn):]
        body = body[:body.index("\n  function ", 10)] if "\n  function " in body[10:] else body
        body = body[:body.index("window.addEventListener('resize', placeFilters)")] \
            if "window.addEventListener('resize', placeFilters)" in body else body
        assert "toggleFilters()" not in body, (
            fn + " calls the toggle directly -- it re-opens a panel closed mid-request")


def test_filter_actions_capture_the_filter_before_the_await(tmp_path):
    """`afId` is module state and the tiles and **No filter** stay clickable during a
    request, so it can change or be cleared before the resolve handler runs.

    `AF.get()` answers an unknown id with `null` -- deliberately, so an unmapped filter is
    never silently rendered as something else -- which makes `AF.get(afId).name` a TypeError
    thrown inside a `.then` SUCCESS handler. The sibling rejection handler on the same
    `.then` cannot catch its own success handler's throw, so every side effect still lands
    and the only trace is an unhandled rejection in the console: the panel closes, the source
    switches, and no toast ever appears.

    Both actions must therefore resolve the filter ONCE, before the await, via afActing().
    """
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "function afActing(" in html
    for fn in ("function filterSave(", "function filterSend("):
        body = html[html.index(fn):]
        body = body[:body.index("window.addEventListener('resize', placeFilters)")] \
            if "window.addEventListener('resize', placeFilters)" in body else body[:4000]
        assert "afActing()" in body, fn + " does not capture the acting filter"
        # The capture has to happen BEFORE the network call, not inside the handler.
        assert body.index("afActing()") < body.index("AF.toBlob("), fn
        assert "AF.get(afId)" not in body, (
            fn + " still reads afId after the await -- AF.get() can return null there")


def test_edit_model_id_and_quality_omit():
    """The Edit-model registry maps picker keys to the right model ids, and
    build_chat_edit_parameters omits 'quality' when empty (Reference Pro has no quality)."""
    assert core.edit_model_id("edit-pro") == core.EDIT_PRO_MODEL_ID
    assert core.edit_model_id("reference-pro") == "1948514378441961474"
    assert core.edit_model_id("nope") == "" and core.edit_model_id("") == ""
    ref = core.build_chat_edit_parameters("x", ["10"], quality="")     # ref-pro: no quality knob
    assert "quality" not in ref["chat"]["modelConfig"]
    ep = core.build_chat_edit_parameters("x", ["10"], quality="high")
    assert ep["chat"]["modelConfig"]["quality"] == "high"


def test_edit_price_uses_selected_model(tmp_path, monkeypatch):
    """The Edit card's model picker drives the submitted modelId + valid option set:
    Reference Pro -> model 1948..., 4K/21:9, no quality; Edit Pro -> Edit Pro model + quality."""
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "price_task", lambda s, params: seen.update(p=params) or 8000)
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, enrich=False: None)
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    cli.post("/api/price", json={"mode": "edit", "edit_model": "reference-pro", "source": "55",
                                 "resolution": "4K", "quality": "", "aspect": "21:9"})
    chat = seen["p"]["chat"]
    assert chat["modelId"] == "1948514378441961474"
    assert chat["modelConfig"]["resolution"] == "4K" and chat["modelConfig"]["aspectRatio"] == "21:9"
    assert "quality" not in chat["modelConfig"]            # Reference Pro sends no quality
    seen.clear()
    cli.post("/api/price", json={"mode": "edit", "edit_model": "edit-pro", "source": "55",
                                 "resolution": "2K", "quality": "high", "aspect": "1:1"})
    chat = seen["p"]["chat"]
    assert chat["modelId"] == core.EDIT_PRO_MODEL_ID and chat["modelConfig"]["quality"] == "high"


def test_edit_card_has_model_picker(tmp_path):
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert 'id="em-edit-pro"' in html and 'id="em-reference-pro"' in html
    assert "Gen.setEditModel('reference-pro')" in html
    assert "EDIT_CAPS" in html and "'reference-pro'" in html   # capability-driven dropdowns


def test_clamp_edit_config_snaps_to_model_caps():
    """Backend guard (fixes the skeptic-found preset bug): any resolution/quality/aspect that
    the resolved model doesn't support is snapped to a valid one — no path sends an invalid knob."""
    # Reference Pro: no quality knob + 1K unsupported -> quality dropped, resolution -> 2K default
    assert core.clamp_edit_config("1948514378441961474", "1K", "medium", "21:9") == ("2K", "", "21:9")
    # Edit Pro: 4K unsupported -> 1K default; valid quality kept; unknown aspect -> default 3:4
    assert core.clamp_edit_config(core.EDIT_PRO_MODEL_ID, "4K", "high", "nope") == ("1K", "high", "3:4")
    # unknown model -> pass through untouched
    assert core.clamp_edit_config("999", "8K", "ultra", "5:1") == ("8K", "ultra", "5:1")


def test_edit_price_clamps_invalid_knobs(tmp_path, monkeypatch):
    """End-to-end: Reference Pro sent with Edit-Pro-style knobs (the preset-mismatch case) is
    clamped server-side to valid values before the params ever reach PixAI."""
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "price_task", lambda s, params: seen.update(p=params) or 8000)
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, enrich=False: None)
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    cli.post("/api/price", json={"mode": "edit", "edit_model": "reference-pro", "source": "55",
                                 "resolution": "1K", "quality": "medium", "aspect": "3:4"})
    mc = seen["p"]["chat"]["modelConfig"]
    assert mc["resolution"] == "2K" and "quality" not in mc      # snapped + quality dropped


def test_edit_multi_reference_sources(tmp_path, monkeypatch):
    """Multi-image references: the Edit card sends sources[] -> chat.mediaIds carries them all
    (primary first), capped to the model's ref limit; falls back to [source] when absent."""
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "price_task", lambda s, params: seen.update(p=params) or 8000)
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, enrich=False: None)
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    cli.post("/api/price", json={"mode": "edit", "edit_model": "edit-pro", "source": "100",
                                 "sources": ["100", "200", "300"], "resolution": "1K",
                                 "quality": "medium", "aspect": "3:4"})
    chat = seen["p"]["chat"]
    assert chat["mediaId"] == "100" and chat["mediaIds"] == ["100", "200", "300"]
    seen.clear()   # Edit Pro caps at 4 -> a 6-image list is trimmed
    cli.post("/api/price", json={"mode": "edit", "edit_model": "edit-pro", "source": "1",
                                 "sources": ["1", "2", "3", "4", "5", "6"]})
    assert seen["p"]["chat"]["mediaIds"] == ["1", "2", "3", "4"]
    seen.clear()   # no sources[] -> falls back to the single source
    cli.post("/api/price", json={"mode": "edit", "edit_model": "edit-pro", "source": "9"})
    assert seen["p"]["chat"]["mediaIds"] == ["9"]


def test_portrait_mobile_pass(tmp_path):
    """The <=480px portrait pass: 2-up grid, header nav swipe strip, full-width drawer +
    centered model flyout, lightbox arrows moved off the image."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "@media (max-width: 480px)" in html
    assert "repeat(2, minmax(0, 1fr)) !important" in html           # 2-up grid, ignores saved --thumb
    # The drawer/flyout half of this pass is asserted by CASCADE, not by substring --
    # see test_portrait_mobile_drawer_rules_actually_win below for why.


PHONE, DESKTOP = 375, 1280


def test_portrait_mobile_drawer_rules_actually_win(tmp_path):
    """The Generate drawer's <=480px overrides must WIN the cascade, not merely exist.

    This test replaces a presence check that could not fail. The old version asserted
    the mobile rule's TEXT was inside the 480px block -- and it was, correct and
    completely dead, for as long as the rule had shipped. Every declaration below
    leans on a bare `#gen-drawer` / `#model-flyout` / `.dock-ctl button` /
    `.gen-head .x` selector, and the 480px block sat ~1,500 lines ABOVE the drawer's
    own <style> block. Equal specificity + earlier position = the base rules won; a
    media query adds no specificity. Measured in a real browser at 375x812 while the
    old test was green: the open dock-right drawer was 352.5px wide (a 22.5px dead
    gutter beside a "full-width" sheet) and the flyout sat at rect y=-332.9px, half
    of it above the top of the viewport. `.wide` and `.dock-left` looked right the
    whole time -- their compound selectors out-specify the bare base rule -- which is
    why eyeballing the phone layout never caught it either.

    So: resolve the winner the way a browser does (!important, specificity, document
    order) and assert on that. Moving these rules back above the drawer's stylesheet
    now fails here instead of shipping silently.
    """
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    rules = css_rules(cli.get("/").get_data(as_text=True))

    def win(levels, prop, width):
        w = winning(rules, levels, prop, width)
        assert w is not None, "nothing declares {!r} for this element".format(prop)
        return w

    # --- the drawer is a full-width sheet on a phone, in every dock/width variant ---
    for extra in ({}, {"wide"}, {"dock-left"}, {"dock-top"}, {"dock-bottom"}):
        drawer = element(id="gen-drawer", classes={"open"} | set(extra))
        label = "+".join(sorted(extra)) or "default dock"
        assert win(drawer, "width", PHONE).value == "100%", \
            "phone drawer width lost the cascade ({})".format(label)
        assert win(drawer, "max-width", PHONE).value == "100vw", \
            "phone drawer max-width lost the cascade ({})".format(label)

    # --- the model flyout is a centered, reachable overlay in every dock ---
    for dock in ({}, {"dock-left"}, {"dock-top"}, {"dock-bottom"}):
        flyout = element(id="model-flyout", classes={"open"},
                         ancestors=[dict(id="gen-drawer", classes={"open"} | set(dock))])
        label = "+".join(sorted(dock)) or "default dock"
        # position/top/left are the three the base rule actually contested and won.
        assert win(flyout, "position", PHONE).value == "fixed", \
            "phone flyout position lost the cascade ({})".format(label)
        assert win(flyout, "top", PHONE).value == "50%", \
            "phone flyout top lost the cascade ({})".format(label)
        assert win(flyout, "left", PHONE).value == "50%", \
            "phone flyout left lost the cascade ({})".format(label)
        # transform was the one declaration that DID survive -- the base rule sets no
        # transform, so nothing contested it. That is exactly what stranded the panel
        # off-screen: a centering transform applied to un-centered coordinates.
        assert win(flyout, "transform", PHONE).value == "translate(-50%,-50%)", \
            "phone flyout transform lost the cascade ({})".format(label)
        assert win(flyout, "width", PHONE).value == "94vw", \
            "phone flyout width lost the cascade ({})".format(label)

    # --- the touch targets this pass exists to enlarge ---
    dock_btn = element(tag="button", ancestors=[dict(classes={"dock-ctl"})])
    assert win(dock_btn, "width", PHONE).value == "34px"     # was stuck at the 22px base
    assert win(dock_btn, "height", PHONE).value == "34px"
    close_x = element(classes={"x"}, ancestors=[dict(classes={"gen-head"})])
    assert win(close_x, "font-size", PHONE).value == "28px"  # was stuck at the 22px base
    assert win(close_x, "min-width", PHONE).value == "40px"

    # --- and none of it leaks onto desktop: the base rules still win at 1280px ---
    desktop_drawer = element(id="gen-drawer", classes={"open"})
    assert win(desktop_drawer, "width", DESKTOP).value == "420px"
    assert win(desktop_drawer, "max-width", DESKTOP).value == "94vw"
    assert win(element(id="gen-drawer", classes={"open", "wide"}), "width", DESKTOP).value == "600px"
    desktop_flyout = element(id="model-flyout", classes={"open"},
                             ancestors=[dict(id="gen-drawer", classes={"open"})])
    assert win(desktop_flyout, "position", DESKTOP).value == "absolute"
    assert win(desktop_flyout, "top", DESKTOP).value == "0"
    assert win(desktop_flyout, "width", DESKTOP).value == "372px"
    assert winning(rules, desktop_flyout, "transform", DESKTOP) is None
    assert win(dock_btn, "width", DESKTOP).value == "22px"
    assert win(close_x, "font-size", DESKTOP).value == "22px"


def test_css_cascade_resolver_can_actually_fail(tmp_path):
    """Guard the guard. tests/csshelp.py is the only reason the test above can bite,
    so prove its verdict tracks document order rather than just reporting whatever it
    finds last: feed it the SAME two rules in both orders and require the answers to
    differ. Without this, a resolver bug that always returned the base rule would make
    every assertion above vacuously green -- which is precisely the failure mode
    (a test that cannot fail) this whole pass exists to remove.
    """
    base = "<style>#d{width:420px;}</style>"
    mobile = "<style>@media (max-width: 480px){#d{width:100%;}}</style>"
    target = element(id="d")

    assert winning(css_rules(base + mobile), target, "width", PHONE).value == "100%"
    assert winning(css_rules(mobile + base), target, "width", PHONE).value == "420px"
    # ...and the media query is genuinely evaluated, not ignored.
    assert winning(css_rules(base + mobile), target, "width", DESKTOP).value == "420px"
    # A higher-specificity earlier rule still beats a later bare one.
    assert winning(css_rules("<style>#d.x{width:1px;}#d{width:2px;}</style>"),
                   element(id="d", classes={"x"}), "width", PHONE).value == "1px"


def test_dead_css_selectors_removed_in_broader_sweep():
    """O9's broader mechanical sweep (audit 2026-07-21): after the two NAMED dead rules
    (.vp-chip/.gen-ce) were deleted in a prior pass, this extracts every class selector out of
    moonglade_gallery.py's inline <style> blocks and checks each for a real producer (a template
    element, or a classList.add/className site in the inline JS). Two more turned up with zero
    producers anywhere in the repo:
      - .dock-right on #gen-drawer -- Gen.setDock(d) only ever toggles 'dock-'+x for x in
        ['left','top','bottom']; picking "right" (the default -- #gen-drawer starts with no
        class attribute at all, and the "Dock right" button's onclick is setDock('right'))
        REMOVES all three instead of ever adding a 'dock-right' class, so that compound
        selector never matched a real element.
      - #model-preview .mp-tags (+ its `span` rule) -- showPreview() builds mp-meta/mp-nm/
        mp-sub/mp-badges/mp-desc into #model-preview's innerHTML but never emits an .mp-tags
        element; nothing else in the repo references it either.
    Removing them is a no-op for real rendering: the bare #gen-drawer / #model-flyout selectors
    already at the front of those same comma-lists match unconditionally, so the mobile
    full-width-drawer / centered-flyout behavior (checked by
    test_portrait_mobile_drawer_rules_actually_win above) is unaffected. Their LIVE siblings
    (dock-left/top/bottom, the rest of .mp-*) must survive.

    NOTE the assertion below is a blunt substring check over the whole module, so it also
    trips on the WORD in ordinary prose, not just on a live selector. If a comment needs to
    describe that dock, spell it "the right-hand dock" rather than hyphenating it."""
    src = (Path(__file__).resolve().parents[1] / "moonglade_gallery.py").read_text(encoding="utf-8")
    assert "dock-right" not in src
    assert "mp-tags" not in src
    for still_alive in ("dock-left", "dock-top", "dock-bottom",
                        "mp-nm", "mp-sub", "mp-desc", "mp-badges"):
        assert still_alive in src, "a LIVE sibling selector was removed: " + still_alive


def test_video_v40_full_cost_warning():
    """The Video form hard-warns when the pricier v4.0 full model is picked (14k/s vs Lite's
    5.5k -- a 15s clip is 210k credits), so it's never a silent surprise. Since the drawer
    swap the Video form IS the shared <mg-generate-drawer> component, so the warning lives in
    that file (mgd-cost.warn), not the gallery's own inline HTML."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "static" / "mg-generate-drawer.js").read_text(encoding="utf-8")
    assert ('mg-generate-drawer mg-cost-badge[data-state="paid"][data-warn]'
            '{border-color:var(--red,#f38ba8);color:var(--red,#f38ba8);}') in src   # still RED
    # The specific warning text, not a bare "2.5" -- that also matches two unrelated
    # font-size:12.5px CSS rules elsewhere in this same file, so the old check passed
    # even with the real warning deleted.
    assert "V4.0 full — ~2.5× Lite" in src        # the ~2.5x-Lite warning text


def test_cost_badge_ships_with_every_price_surface(tmp_path):
    """Every <mg-cost-badge> element MUST ship on a page that also loads
    static/mg-cost-badge.js. A custom element whose definition never loads is an inert
    <div>: setChecking()/setPrice() throw, the cost line freezes on its idle hint, and
    the Go button beside it still spends. That failure is silent and it is on the spend
    path, so the pairing gets a test rather than a convention -- the same reasoning that
    put the drawer's own script tag under test above.

    Scope: this checks the <mg-cost-badge>/script pairing, not "every surface that
    renders a live cost" -- the Loom has two OTHER live-cost surfaces that are
    genuinely not badges, so this test's mechanism (a custom-element/script pairing
    check) has nothing to pair for them: the "Generate all" aggregate estimate
    (the .lv-cost-pill button, master-storyboard.jsx) and the per-shot spend-gate
    confirm() dialogs (the fail-closed cost gate ahead of a submit). Both print cost as
    plain text/JS strings with no custom element to upgrade, so a missing script tag
    can't silently break them the way it breaks a badge (audit: tests-that-dont-bite,
    doc-lie, 2026-07-21 -- the docstring used to claim "every surface", which this
    test's own assertions never covered)."""
    import moonglade_gallery as pg
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                         created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert '<mg-cost-badge id="gen-cost"' in html        # gallery Generate tab
    assert '<mg-cost-badge id="edit-cost"' in html       # gallery Edit tab
    assert '/static/mg-cost-badge.js' in html            # ...and the definition they need
    assert '/static/mg-cost-badge.js' in pg._LOOM_SHELL  # the Loom's drawer needs it too


def test_toasts_anchored_top_right(tmp_path):
    """Toast/Jobs/Achievement CSS moved into static/mg-notify.js (2026-07-18, shared with the
    Loom) -- it's injected client-side, not present in the server-rendered HTML, so this now
    checks the page loads the shared script and that the script's own CSS still positions
    toasts top-right (unchanged) at the z-index raised above the Loom's own overlays."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert '<script src="/static/mg-notify.js"></script>' in html
    notify_js = (Path(__file__).resolve().parents[1] / "static" / "mg-notify.js").read_text(encoding="utf-8")
    assert "#mg-toasts{position:fixed;right:16px;top:64px" in notify_js   # top-right, clear of the header


def test_flyout_open_does_not_search_the_hidden_tab(tmp_path):
    """Owner report 2026-07-24 ("still slow"): ensurePickers() creates AND mounts both the
    base and LoRA pickers together the moment the flyout first opens, so both used to fire
    a full network search immediately -- including the one nobody had asked to see yet,
    competing with the real search for the same connection. setKind() must call
    ensureSearched() on whichever picker just became visible instead, so only ONE search
    fires on open."""
    picker_js = (Path(__file__).resolve().parents[1] / "static" / "mg-model-picker.js").read_text(encoding="utf-8")
    assert "this._searched = false;" in picker_js
    assert "if (this.style.display !== 'none') { this._searched = true; this._search(); }" in picker_js
    assert "ensureSearched() {" in picker_js
    assert "if (this._searched && !this._stale) return;" in picker_js

    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "if(vis && vis.ensureSearched) vis.ensureSearched();" in html


def test_picking_a_base_model_does_not_double_search_the_hidden_lora_picker(tmp_path):
    """AUDIT_2026-07-21 follow-up: the deferred-search fix closed only one of two redundant
    requests. Picking a base model sets `base-type` on the LoRA picker -- which is normally
    still HIDDEN, since both hosts mount base+LoRA together and reveal one -- and
    attributeChangedCallback searched unconditionally, without ever setting `_searched`. So
    the hidden instance fetched and built ~24 cards nobody had asked to see, and then the
    first reveal's ensureSearched() fired the IDENTICAL request all over again.

    Two halves, both required: `_search()` must own the `_searched` flag (so ANY search
    counts), and a base-type change on a hidden instance must defer rather than search."""
    picker_js = (Path(__file__).resolve().parents[1] / "static" / "mg-model-picker.js").read_text(encoding="utf-8")
    # 1) _search() owns the flag -- not just the two call sites that knew about it
    body = picker_js.split("    _search() {", 1)[1][:900]
    assert "this._searched = true;" in body and "this._stale = false;" in body

    # 2) a hidden instance defers; a visible one still re-searches on the spot
    assert ("if (this.style.display === 'none') { if (this._searched) this._stale = true; return; }"
            in picker_js)
    assert "this._stale = false;" in picker_js   # initialized, never undefined on first reveal

    # The Gallery still feeds the resolved architecture straight into the LoRA picker -- the
    # deferral changes WHEN the search happens, never whether base_type reaches the server.
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "if(loraPickerEl) loraPickerEl.setAttribute('base-type', selected.model_type||'');" in html


def test_generate_card_has_seed_field(tmp_path):
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert 'id="gen-seed"' in html and "seed:(el('gen-seed')" in html   # UI + payload wire the seed


def test_generate_drawer_gates_on_the_real_account_lora_cap(tmp_path):
    """The account's real LoRA-per-generation cap (Acct.loraCap(), sourced from
    membership.privilege via /api/account) now shows next to the LoRAs label, blocks
    Generate when exceeded, and warns with the exact count to remove -- rather than the
    old behavior of no cap at all (see the O12 CHANGELOG note on why a silent hard-refuse
    in the picker itself was deliberately rejected)."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert 'id="gen-lora-cap"' in html                      # the indicator next to "LoRAs"
    assert "function overLoraCap(){ var cap=window.Acct&&Acct.loraCap?Acct.loraCap():null; return cap!=null && loras.length>cap; }" in html
    assert "anyIncompat() || anyLoraUnresolved() || overLoraCap()" in html   # Go button gate
    assert "Your account allows " in html                   # the over-cap warning text
    assert "if(window.Gen && Gen.refreshLoraCap) Gen.refreshLoraCap();" in html   # Acct pushes the cap into Gen on every refresh


def test_generate_drawer_gates_advanced_controls_by_model_compatibility(tmp_path):
    """extra.compatibility (probed live 2026-07-06, memory pixai-model-capability-schema)
    says which Advanced-panel params a model actually HONORS -- e.g. Tsubaki.2 ignores CFG
    scale entirely and runs sampling steps FIXED at 16. An editable control that silently
    does nothing was worse than no control at all -- gateField() disables it (never hides;
    the owner can still see it exists and why it's off) and fails OPEN on unknown/absent
    data (only an explicit `false` disables anything), same convention as every other
    fail-open gate in this app."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "function gateField(id, honored, bounds, defMin, defMax){" in html
    assert "var off = honored===false;" in html                # fail open: undefined/true never disables
    assert "f.title = off ? 'This model doesn\\u2019t use this setting' : '';" in html
    # min/max must ALWAYS resolve to something (the model's own bounds, or the field's real
    # default) -- never left conditionally untouched, or a stale bound from a PREVIOUSLY
    # selected model leaks forward onto one with no restrictions at all (caught live 2026-07-24).
    assert "if(defMin!=null) f.min = (bounds&&bounds.min!=null) ? bounds.min : defMin;" in html
    assert "if(defMax!=null) f.max = (bounds&&bounds.max!=null) ? bounds.max : defMax;" in html
    assert "gateField('gen-neg', compat.negativePrompt, null);" in html
    assert "gateField('gen-steps', compat.samplingSteps, restr.samplingSteps, 1, 150);" in html
    assert "gateField('gen-cfg', compat.cfgScale, restr.cfgScale, 1, 30);" in html
    assert "selected.compatibility=v.compatibility||{}; selected.restrictions=v.restrictions||{};" in html
    assert "applyCapabilityGating();" in html                  # called from applyVersion, covers both onBasePick + pickVersion


def test_generate_drawer_offers_a_per_lora_version_selector(tmp_path):
    """resolve_version_meta() (and the old single-fetch LoRA resolve) always silently took
    the newest release; PixAI's own model/LoRA cards offer a version selector, the base
    model already got one (picker-parity-round2). This closes the matching gap for an
    already-added LoRA chip: a <select> appears only when the LoRA actually has more than
    one published release (mirrors the base model's #gen-version -- the common single-
    version case renders nothing extra), and picking a different one applies its OWN
    version_id/lora_base_type/trigger_words with no new network call (the full version list
    was already resolved when the LoRA was first picked, by mg-model-picker.js's
    ?all=1 fetch)."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "l.versions&&l.versions.length>1" in html          # conditional, not always-shown
    assert 'onchange="Gen.loraPickVersion(' in html
    assert "function loraPickVersion(i, vid){" in html
    assert "l.version_id=v.version_id||''; l.lora_base_type=v.lora_base_model_type||'';" in html
    assert "loraPickVersion:loraPickVersion" in html           # exposed on Gen's public API


def test_generate_drawer_blocks_submit_on_unresolved_lora(tmp_path):
    """A LoRA whose /api/model-version lookup never resolves (still pending, or
    permanently failed) used to just vanish from payload()'s loras filter -- the
    generation submitted anyway, spending full credits on a result silently missing
    a LoRA the user believed was included, with nothing on screen but an hourglass
    that never explained itself (audit: fail-open, 2026-07-21). Fixed: the lookup's
    failure path is distinguished from success (entry.failed), Go is gated on every
    added LoRA having actually resolved, and generate() refuses to submit even if
    something got the disabled button clicked anyway.

    O12 (Phase 2): the LoRA pick/resolve lifecycle itself (the fetch that sets
    entry.failed) moved into <mg-model-picker>'s own _toggleMulti() -- the gallery's
    onLoraPick() only consumes the ALREADY-resolved-or-failed entry the component hands
    it. So the failed-tracking assertions now check mg-model-picker.js; everything that
    still lives in moonglade_gallery.py (the Go-button gate, generate()'s submit-time guard,
    anyLoraUnresolved() itself) is unchanged and still checked against the gallery page."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    # The silent-drop shape must be gone: a bare `.catch(function(){ renderLoras(); });`
    # right after the model-version fetch, with no failed-state tracking at all.
    assert ".catch(function(){ renderLoras(); });" not in html
    assert "function anyLoraUnresolved(){ return loras.some(function(l){ return !l.version_id; }); }" in html
    assert "anyIncompat() || anyLoraUnresolved()" in html          # Go button gate
    assert "if(anyLoraUnresolved()){ el('gen-lora-note').scrollIntoView" in html   # submit-time guard

    picker_js = (Path(__file__).resolve().parents[1] / "static" / "mg-model-picker.js").read_text(encoding="utf-8")
    assert "entry.failed = true;" in picker_js
    assert "entry.failed = !entry.version_id;" in picker_js


def test_price_no_longer_has_an_enhance_mode(tmp_path, monkeypatch):
    """/api/price used to accept mode=enhance and build panelplugin params for it. That
    branch went with the surface: pricing a task PixAI will never dispatch only ever
    produced a credible-looking number for an hour of queuing. The payload now falls
    through to the ordinary image-generation branch, which answers "pick a model" -- an
    honest refusal, and NOT a price."""
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "price_task", lambda s, params: seen.update(p=params) or 8000)
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, enrich=False: None)
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    r = cli.post("/api/price", json={"mode": "enhance", "source": "55",
                                     "workflow_id": "1794855217667308480"})
    assert r.get_json().get("cost") is None
    assert not seen, "a removed mode still reached the pricing endpoint"


def test_import_task_by_id(tmp_path, monkeypatch):
    """Panel 'Recover a task by ID' -> collect_generation. LOGIN tier (not localhost --
    see below); numeric-only; recovers edits/favorites-only tasks Sync's listing skips.

    The 401 below is asserted from an ANONYMOUS client -- login_existing_client() is only
    called on the next line -- so it proves the front door refuses an unauthenticated
    request and nothing more. It used to be commented "# LAN refused" alongside a
    "Localhost-gated" docstring, which claimed a tier assertion this test has never made:
    the front door answers before any handler runs, so it would read identically whether
    or not a localhost check existed. That exact shape is how three real gate regressions
    shipped unnoticed this week. Relabelled rather than deleted -- the anonymous-refusal
    check is still worth having.

    This route's ACTUAL tier is pinned by tests/test_route_tiers.py, which drives an
    authenticated non-local session against every registered route. It is deliberately
    LOGIN, not localhost: recovering your own finished media spends nothing."""
    called = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, tid, out, **k: called.update(tid=tid) or {"saved": 1, "media_ids": ["m1"], "is_video": False})
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    assert cli.post("/api/import-task", json={"task_id": "123"},
                    environ_overrides={"REMOTE_ADDR": "192.168.1.9"}).status_code == 401   # anonymous refused by the front door
    cli = login_existing_client(cli)
    d = cli.post("/api/import-task", json={"task_id": "nope"}).get_json()
    assert d.get("error") and "tid" not in called                          # non-numeric rejected, no collect
    d = cli.post("/api/import-task", json={"task_id": "2030585251815688815"}).get_json()
    assert d["ok"] and d["saved"] == 1 and called["tid"] == "2030585251815688815"
    # already in the gallery -> reports it + hands back the media, does NOT re-fetch ("behind the milk")
    save_catalog(tmp_path / "catalog.db", [_row(media_id="ex1", filename="e.png", task_id="999",
                                                created_at="2025-01-02T00:00:00")])
    called.clear()
    d = cli.post("/api/import-task", json={"task_id": "999"}).get_json()
    assert d.get("already") is True and d["saved"] == 0 and "ex1" in d["media_ids"]
    assert "tid" not in called                                             # no re-collect
    html = cli.get("/panel").get_data(as_text=True)
    assert 'id="import-tid"' in html and "importTask()" in html            # the panel card + wiring


def test_import_task_closes_the_original_orphaned_job_entry(tmp_path, monkeypatch):
    """THE BUG (docs/AUDIT_2026-07-21.md, owner-2026-07-23, task 2037215124834251576):
    a generation finishes on PixAI's side but our own /api/task-status never gets a
    chance to run for it -- the polling browser tab closed, or a transient exception
    left it at 'running' by api_task_status()'s own deliberate design -- so the job
    sits at 'running' in jobs.jsonl forever. The owner's real recovery for exactly this
    is a manual task-id import through THIS route -- but the import only ever wrote a
    brand-new 'import-<suffix>' job and never touched the ORIGINAL orphaned job_id
    (which, for a web-submitted generate job, IS the numeric task id), so the Activity
    card kept spinning on the orphan forever even after the real media had landed.
    Recovering the same task id an orphan is keyed on must close that original entry."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, tid, out, **k: {"saved": 1, "media_ids": ["m1"], "is_video": False})
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    cli = login_existing_client(cli)
    tid = "2037215124834251576"
    core.append_job_event(tmp_path, tid, status="running", type="generate", label="Generated")

    d = cli.post("/api/import-task", json={"task_id": tid}).get_json()
    assert d["ok"] and d["saved"] == 1

    by_id = {j["job_id"]: j for j in core.read_jobs(tmp_path)}
    assert by_id[tid]["status"] == "done", "the original orphaned entry was never closed"
    assert by_id[tid]["media_ids"] == ["m1"]
    # the recovery's own new job_id still exists too -- this closes the orphan
    # IN ADDITION TO, not instead of, the import's own activity entry.
    assert any(j.get("type") == "import" for j in by_id.values())


def test_import_task_closes_orphan_on_the_already_cataloged_path_too(tmp_path):
    """Same bug, the OTHER success branch: if the task's media is already in the
    catalog (the "behind the milk" short-circuit -- e.g. the live-mirror watcher
    collected it moments before the owner clicked Recover), the original orphaned job
    entry must still get closed. Without this, a recovery landing on the
    already-cataloged branch does nothing for the stuck Activity card at all."""
    tid = "999"
    core.append_job_event(tmp_path, tid, status="running", type="generate", label="Generated")
    save_catalog(tmp_path / "catalog.db", [_row(media_id="ex1", filename="e.png", task_id=tid,
                                                created_at="2025-01-02T00:00:00")])
    cli = login_client(tmp_path)

    d = cli.post("/api/import-task", json={"task_id": tid}).get_json()
    assert d.get("already") is True

    by_id = {j["job_id"]: j for j in core.read_jobs(tmp_path)}
    assert by_id[tid]["status"] == "done", "the already-cataloged path left the orphan spinning"


def test_import_task_leaves_a_dismissed_orphan_alone(tmp_path, monkeypatch):
    """If the owner already dismissed the orphaned entry by hand, a later recovery must
    not resurrect it with a new event -- dismiss is an explicit user action and stays
    respected, same as every other job in the log."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, tid, out, **k: {"saved": 1, "media_ids": ["m1"], "is_video": False})
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    cli = login_existing_client(cli)
    tid = "2222"
    core.append_job_event(tmp_path, tid, status="running", type="generate", label="Generated")
    core.append_job_event(tmp_path, tid, dismissed=True)

    cli.post("/api/import-task", json={"task_id": tid})

    from moonglade_backup import _reconstruct_jobs
    jobs_by_id, _order, _n = _reconstruct_jobs(tmp_path)
    assert jobs_by_id[tid]["status"] == "running"       # untouched
    assert jobs_by_id[tid]["dismissed"] is True


def test_account_surfaces_cards_claim_and_subscription(tmp_path, monkeypatch):
    """The header balance surface exposes per-card breakdown + soonest expiry, claimable
    free credits, and the subscription cliff — the data the chip/badge/warnings render."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "account_info", lambda s: {
        "quotaAmount": 140, "subscription": {"endAt": "2026-07-27T00:00:00Z", "cancelAtPeriodEnd": True}})
    monkeypatch.setattr(core, "list_kaisuukens", lambda s: [
        {"name": "Edit Pro Only", "count": 17, "expires": "2026-07-17T20:11:09Z"},
        {"name": "Reference Pro Only", "count": 5, "expires": "2026-07-17T20:11:09Z"}])
    monkeypatch.setattr(core, "list_claims", lambda s: [
        {"id": "pixai-daily-credits", "amount": 30000, "canClaim": True},
        {"id": "agent-daily-stamina", "amount": 20, "canClaim": True}])
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    d = cli.get("/api/account").get_json()
    assert d["credits"] == 140 and d["cards"] == 22
    assert d["card_expiry"] == "2026-07-17" and len(d["cards_by"]) == 2
    assert d["claim_credits"] == 30000 and "pixai-daily-credits" in d["claim_ids"]
    assert d["sub"]["end"] == "2026-07-27" and d["sub"]["cancel"] is True


def test_account_endpoint_still_serves_credits_after_the_roles_removal(tmp_path, monkeypatch):
    """This test used to assert /api/account returned a normalized `roles` list. That whole
    feature is gone, because fetching it was breaking everything else: `me.roles` is a
    RoleConnection, and selecting it bare failed GraphQL validation for the ENTIRE account
    query -- so the credits chip read 0/0, the membership-derived LoRA cap emptied, and the
    first-run setup wizard would have rejected a valid API key.

    It was never read by any UI. Nothing that no consumer wants should be able to take the
    account read down with it. What this now guards is the thing that actually matters and
    that the roles work silently broke: the endpoint still serves real credits.
    """
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "account_info", lambda s: {"quotaAmount": 1850640})
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                         created_at="2025-01-01T00:00:00")])
    body = cli.get("/api/account").get_json()
    assert body["credits"] == 1850640, "the credits chip lost its number again: {!r}".format(body)
    assert "roles" not in body, "roles is back in the payload; see _ACCOUNT_QUERY's guard"


def test_account_surfaces_the_real_membership_lora_cap(tmp_path, monkeypatch):
    """PixAI's own account API already returns the account's real per-generation LoRA
    entitlement (membership.privilege.{lora,freeUserLora}) -- account_info() already fetches
    it (see the CLI's --account dashboard, run_account_info), but nothing ever exposed it to
    the web app, so the picker had no idea what the real cap was. `lora` wins when both are
    present (mirrors the CLI's own field-check order); `free_user_lora` is the fallback for
    an account with no paid `lora` entitlement at all."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "account_info", lambda s: {
        "quotaAmount": 140,
        "membership": {"privilege": {"lora": 15, "freeUserLora": 2}}})
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    d = cli.get("/api/account").get_json()
    assert d["lora_cap"] == 15


def test_account_lora_cap_falls_back_to_free_user_lora(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "account_info", lambda s: {
        "quotaAmount": 140,
        "membership": {"privilege": {"freeUserLora": 2}}})
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    d = cli.get("/api/account").get_json()
    assert d["lora_cap"] == 2


def test_account_lora_cap_null_when_membership_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "account_info", lambda s: {"quotaAmount": 140})
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    d = cli.get("/api/account").get_json()
    assert d["lora_cap"] is None


def test_claim_endpoint_gated_and_claims_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "list_claims", lambda s: [
        {"id": "pixai-daily-credits", "amount": 30000, "canClaim": True},
        {"id": "agent-startup-stamina", "amount": 15, "canClaim": False}])   # not ready -> skipped
    claimed = []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "claim_reward", lambda s, cid: claimed.append(cid))
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    # An unauthenticated LAN request is refused -- checked first, while `cli` is still
    # anonymous, then logged in for the real claim below.
    assert cli.post("/api/claim", environ_overrides={"REMOTE_ADDR": "192.168.1.9"}).status_code == 401
    cli = login_existing_client(cli)
    d = cli.post("/api/claim").get_json()
    assert d["claimed"] == 1 and d["credits"] == 30000       # only the ready credit reward
    assert claimed == ["pixai-daily-credits"]


def test_gallery_video_tab_is_the_shared_drawer_component(tmp_path):
    """Web parity step 2 (the drawer swap): the gallery's Video tab is the shared
    <mg-generate-drawer> web component now -- the same element the Loom mounts, giving the
    gallery the full-parity Video form (6 image + 3 video + 1 audio refs, negative prompt,
    Channel, full model roster) over the proven /api/loom/generate submit path. Pins the
    script include, the mount point, and the host's mg-pick-request wiring, and asserts the
    old hand-rolled form (9 image slots, 5-model select, no video/audio/negative/channel)
    is gone -- so the swap can't silently regress back to simple mode."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "/static/mg-generate-drawer.js" in html              # component script on the gallery
    assert "<mg-generate-drawer></mg-generate-drawer>" in html  # mounted in the Video tab
    assert "mg-pick-request" in html                            # host wires the gallery Picker
    # the old hand-rolled video form is gone
    assert 'id="video-slots"' not in html
    assert 'id="video-model"' not in html
    assert "Gen.videoGenerate()" not in html


def test_gallery_video_tab_registers_with_the_job_tracker(tmp_path):
    """Audit 2026-07-21, B4: the drawer swap above wired mg-pick-request but not mg-submit
    or mg-result, so a Video tab generation never showed up in the Activity card and never
    refreshed the header's credit balance -- both things every OTHER tab (Generate/Edit/Fix,
    still the pre-migration runTask()) already gets for free. The drawer polls and renders
    its OWN result inline regardless (self-contained, same as the Loom's mount), which is
    exactly why this was invisible: the generation itself always looked like it worked.

    Bite: remove either listener and this fails, naming which one.
    """
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    # Checked as the exact listener registrations, not bare substrings -- Acct.refresh() in
    # particular already appears twice elsewhere on this page (runTask's own callback), so
    # "Acct.refresh() in html" alone would pass even with this entire fix reverted.
    assert "document.addEventListener('mg-submit', function(e){" in html, (
        "no mg-submit listener -- a Video tab generation never reaches the Activity card")
    assert "window.Jobs.register(d.task_id, 'Rendered')" in html, (
        "mg-submit fires but nothing registers the job with the Activity tracker")
    assert "document.addEventListener('mg-result', function(){ Acct.refresh(); });" in html, (
        "no mg-result listener calling Acct.refresh() -- the header credit balance never "
        "refreshes after a Video tab generation completes")


def test_edit_card_has_reference_slots(tmp_path):
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert 'id="edit-refs"' in html and 'id="edit-ref-cap"' in html
    assert "renderEditRefs" in html and "editRefs" in html


def test_generate_card_has_size_and_custom_dimensions(tmp_path):
    """The Generate card must expose real dimensions — size presets + custom W/H + a wider
    aspect set — not the old 5 hardcoded ~512px buttons. The API has no size cap (backend
    _dim only floors to /8), so the card shouldn't self-throttle to half a megapixel."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert 'id="gen-size"' in html and 'id="gen-cw"' in html and 'id="gen-ch"' in html
    assert 'data-rw="16" data-rh="9"' in html and 'data-rw="3" data-rh="1"' in html  # ratio-based
    assert 'value="1536"' in html and 'value="2048"' in html   # L / XL presets
    assert 'data-w="512"' not in html                           # old hardcoded caps gone


def test_lightbox_video_uses_load_not_premature_seek(tmp_path):
    """Mobile (iOS Safari) fix: after changing the lightbox <video> src we must call
    load() and must NOT seek currentTime before metadata loads (that throws on iOS and
    aborts playback). Guards against reintroducing the desktop-only-works regression."""
    cli = _authed_client(tmp_path, [_row(media_id="9", filename="v_9.mp4", is_video="1",
                                  created_at="2025-02-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "vid.load()" in html                       # explicit reload after src change
    assert "vid.currentTime = 0;" not in html          # the premature seek is gone
    assert "vid.error" in html                          # surfaces the MediaError code on failure


# Cache generations that shipped a poisoning bug. A client holding one of these must be
# force-healed by a bump, so the live cache name may never be any of them again:
#   v1 -- froze 404s in (blank video tile until a hard-refresh)
#   v2 -- cache-first on /thumbs/, which pinned the stale poster --rebuild-thumbs repairs
_POISONED_CACHES = ("pixai-img-v1", "pixai-img-v2", "pixai-img-v3")


def test_service_worker_never_caches_misses(tmp_path):
    """The SW must NOT freeze a 404 (a thumbnail that didn't exist yet) into its cache --
    that was the 'blank video tile until a hard-refresh' bug. It must only cache OK
    responses, use a cache name bumped past every known-poisoned generation, and delete the
    old cache on activate so existing clients self-heal without Ctrl+Shift+R."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    sw = cli.get("/sw.js").get_data(as_text=True)
    assert "resp.ok" in sw and "c.put" in sw                # caches only successful fetches
    assert "caches.delete" in sw                            # purges the poisoned old cache
    # Assert the invariant, not a literal: pinning the exact name here meant every
    # legitimate bump broke this test, which is how it came to assert a stale version.
    m = re.search(r"const C='(pixai-img-v\d+)'", sw)
    assert m, "SW must declare a versioned cache name"
    assert m.group(1) not in _POISONED_CACHES, (
        "cache name {} shipped a poisoning bug -- bump it so held clients self-heal"
        .format(m.group(1)))


def test_service_worker_never_caches_a_followed_login_redirect(tmp_path):
    """`resp.ok` alone is not a cache guard here, because a GATED media response is a 200.

    /thumbs/, /img/ and /full/ are not under _JSON_GATE_PREFIXES, so the front door answers
    an unauthorized request for one with `redirect(url_for("login", ...))`. An <img>
    subresource has redirect mode "follow", so the browser follows it and hands the worker
    the LOGIN PAGE at status 200 / ok===true / redirected===true -- which the old guard
    happily wrote into Cache Storage under the image's own URL.

    On /img/ and /full/ that branch is cache-first with no revalidation (`r||fetch`), so the
    poisoned entry is served forever: through re-login, reloads and restarts, curable only
    by Ctrl+Shift+R. The trigger is ordinary -- Sign out is a global revoke, so signing out
    on the desktop kills the tablet's session mid-lazy-load.

    Bite: drop either `!resp.redirected` and this fails, naming the branch.
    """
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                         created_at="2025-01-01T00:00:00")])
    sw = cli.get("/sw.js").get_data(as_text=True)

    writes = re.findall(r"if\(resp&&resp\.ok([^)]*)\)c\.put\(", sw)
    assert len(writes) == 2, (
        "expected exactly two cache writes (originals + thumbnails), found {} -- if a third "
        "was added it needs the same redirect guard".format(len(writes)))
    for i, guard in enumerate(writes):
        assert "!resp.redirected" in guard, (
            "cache write #{} writes any ok response, including a login page reached by "
            "following the front door's 302. Add `&&!resp.redirected`.".format(i + 1))

    # And prove the premise rather than asserting it: a gated media URL really does answer
    # with a redirect whose target is a 200, which is the response shape being guarded.
    anon = create_app(tmp_path).test_client()
    r = anon.get("/img/2025-01/a_1.png")
    assert r.status_code in (301, 302, 303, 307, 308), (
        "the front door no longer redirects gated media -- if it now 401s, resp.ok would "
        "catch it and this guard's rationale needs revisiting")
    assert "/login" in (r.headers.get("Location") or "")


def test_service_worker_revalidates_thumbnails(tmp_path):
    """Thumbnails are rewritten IN PLACE at the same /thumbs/<media_id>.jpg URL by
    --rebuild-thumbs, so they must NOT be served cache-first: this worker never consults
    Cache-Control, so a cache-first hit pins the broken poster the rebuild was meant to
    repair -- for the life of the cache. Thumbs get stale-while-revalidate (paint from
    cache, refresh behind it); only write-once originals stay cache-first."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    sw = cli.get("/sw.js").get_data(as_text=True)
    # /thumbs/ is handled on its own branch, separate from the originals' cache-first one
    assert "isThumb" in sw and "isOrig" in sw
    # the thumb branch always fires a fetch -- it does not short-circuit on a cache hit.
    # Sliced from a marker unique to the thumb branch (not a brace-count split, which
    # used to grab the trailing "});\n" off the LAST "}" in the whole rest of the
    # string -- a no-op slice that made every assertion below it unconditionally true).
    assert "const n=fetch(e.request,{cache:'no-cache'})" in sw, \
        "thumb branch's revalidate fetch not found where expected -- if it moved, update the slice marker below"
    thumb_branch = sw[sw.index("const n=fetch(e.request,{cache:'no-cache'})"):]
    assert "r||n" in thumb_branch, "thumbs must fall back to the network, not stop at a cache hit"
    assert "c.put" in thumb_branch, "the thumb branch itself must revalidate-write, not just some other branch"
    # and the server must stop claiming thumbnails are immutable
    hdr = cli.get("/thumbs/1.jpg").headers.get("Cache-Control", "")
    assert "immutable" not in hdr, (
        "thumbnails are rewritten in place; 'immutable' pins the stale one. Got: " + hdr)


def test_price_route_prices_the_loom_image_edit_and_reference_bodies(tmp_path, monkeypatch):
    """The Loom's Image / Edit / Reference tabs now price their REAL submit body through
    /api/price before spending (confirmSpend, the same fail-closed gate the video shots use).
    Each client shape must route to a priceable params object. If a key were wrong,
    _params_and_nocard returns a `note` (params None), price_task is never called, and the
    client guardrail degrades to a permanent "couldn't verify the cost" that can never show
    the true credits/free-card state -- exactly the silent-spend seam this closes.

    Bites: revert any of confirmSpend's price bodies to a mismatched key and the matching
    cost assertion drops from 1200 to None."""
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "price_task", lambda s, params: seen.update(params=params) or 1200)
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, enrich=False: None)  # no free card
    # The Loom Image picker emits model_id only (no version_id); /api/price resolves it to a
    # version the same way /api/generate does. Stub that resolve so the test needs no network.
    monkeypatch.setattr(core, "resolve_version_meta",
                        lambda s, mid: {"version_id": "ver_" + str(mid)})
    cli = _authed_client(tmp_path, [_row(media_id="99", filename="b_99.png",
                                         created_at="2025-01-01T00:00:00")])

    # Image tab -> confirmSpend({model_id, prompt}); no `mode`, model_id-only -> generate branch
    # after the version resolve above.
    d = cli.post("/api/price", json={"model_id": "1709df", "prompt": "a moonwell"}).get_json()
    assert d["cost"] == 1200 and d["free"] is False, \
        "image price body did not route to a priceable gen (got {})".format(d)
    assert seen["params"].get("modelId") == "ver_1709df", \
        "the resolved version_id didn't reach price_task's params"

    # Edit tab -> confirmSpend({mode:'edit', source, instruction, edit_model:'edit-pro'}).
    base = {"mode": "edit", "source": "99", "instruction": "make it night"}
    d = cli.post("/api/price", json={**base, "edit_model": "edit-pro"}).get_json()
    assert d["cost"] == 1200, "edit price body did not route to a priceable edit (got {})".format(d)
    edit_params = seen["params"]

    # Reference tab -> confirmSpend({mode:'edit', source, sources, instruction, edit_model:'reference-pro'}).
    d = cli.post("/api/price", json={"mode": "edit", "source": "99", "sources": ["99", "99"],
                                     "instruction": "a still", "edit_model": "reference-pro"}).get_json()
    assert d["cost"] == 1200, "reference (multi-source) body did not price (got {})".format(d)

    # And edit_model actually threads: same source, only the model differs -> different params.
    d = cli.post("/api/price", json={**base, "edit_model": "reference-pro"}).get_json()
    assert d["cost"] == 1200
    ref_params = seen["params"]
    assert edit_params != ref_params, \
        "edit-pro and reference-pro priced to identical params -- edit_model didn't thread through"


# ---------------------------------------------------------------------------
# Import: creating a collection on the way in
# ---------------------------------------------------------------------------

def test_import_modal_can_create_a_collection_on_import(tmp_path):
    """The dropdown could only pick a collection that already existed, so importing into a
    NEW one meant importing uncollected first and re-collecting afterwards. A collection is
    just a name applied to rows (add_to_collection), so an unseen name creates one -- the
    only thing missing was the way in.

    The sentinel must never reach the server as a collection name: chosenCollection()
    resolves it to the typed value before the request is built.
    """
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                         created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)

    assert 'value="__new__"' in html, "no '+ New collection' option in the import dropdown"
    assert 'id="imp-newcoll"' in html, "the option exists but there is nowhere to type the name"
    assert 'ImportUI.onCollectionChange()' in html, "picking the option reveals nothing"

    # The sentinel is resolved client-side, never appended as a collection name.
    assert "chosenCollection" in html
    assert "fd.append('collection', coll)" in html, (
        "the import still appends the raw <select> value -- '__new__' would be sent as a "
        "literal collection name")


def test_import_modal_refuses_to_import_into_an_unnamed_new_collection(tmp_path):
    """Picking "New collection…" and leaving it blank must not fall through to importing
    uncollected -- that is the failure you notice later, hunting for files that went
    somewhere else. chosenCollection() returns null for that state and doImport stops.
    """
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                         created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "if(coll===null)" in html, (
        "doImport does not distinguish 'no collection chosen' from 'new collection, name "
        "still blank' -- a blank name would silently import uncollected")


def test_import_collection_choice_does_not_persist_between_imports(tmp_path):
    """reset() runs on both open() and close(), so a name typed for one batch cannot ride
    along on the next -- collection choice is per-import, not sticky."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                         created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "if(cs)cs.value=''" in html and "if(cn)cn.value=''" in html, (
        "reset() leaves the collection selection or the typed new-collection name behind")


def test_fix_tab_warns_before_it_spends(tmp_path):
    """The Fix sub-tab (hand/face box-fixer) used to fire /api/fix with zero warning of any
    kind -- the only credit-spending action in the app with neither a price nor a confirm.
    It carries both now: an <mg-cost-badge> priced through /api/price and a confirm that
    quotes the badge's number. The confirm is not redundant, because a Fix can never be
    covered by a free card -- every press spends. Cost-badge and pricing detail live in
    tests/test_fix.py; this stays the guard that the SUBMIT is gated."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                         created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    start = html.index("function fix(){")
    end = html.index("function openEdit(mid){", start)   # the next function, whole fix() in between
    fix_fn = html[start:end]
    assert "window.confirm(" in fix_fn, "fix() submits with no spend confirmation at all"
    # the confirm must gate the actual submit, not just exist somewhere nearby
    assert fix_fn.index("window.confirm(") < fix_fn.index("runTask('/api/fix'"), (
        "the confirm exists but doesn't actually gate the runTask('/api/fix') call")
