"""The gallery Picker's web API: /api/gallery-images (browse the whole catalog with
paging + full prompts for the copy-to-clipboard feature) and /api/upload (local file
-> PixAI media_id via the free S3 handshake). All localhost-gated; upload_media is
monkeypatched so nothing touches the network."""
import io
import json
import os
import re
from pathlib import Path

import pixai_gallery_backup as core
from pixai_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_client, login_existing_client


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
    # Per-account storage (D-7): the file lives under prompt_snippets/<user>.json now,
    # not the old flat prompt_snippets.json every account used to share.
    assert (tmp_path / "prompt_snippets" / "tester.json").exists()
    assert cli.get("/api/snippets").get_json() == {"snippets": ["masterpiece, 4k", "night"]}


def test_snippets_rejects_non_list(tmp_path):
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    assert cli.post("/api/snippets", json={"snippets": "nope"}).status_code == 400


def test_one_account_cannot_see_or_clobber_anothers_snippets(tmp_path):
    """Same split saved views already got (test_view_presets.py), same reason: prompt
    snippets were install-wide (one shared prompt_snippets.json), so any signed-in
    account could read AND wholesale-overwrite every other account's saved snippets."""
    from pixai_gallery import create_app
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


def test_gallery_model_preview_hover_is_debounced_not_instant(tmp_path):
    """Same D-11 fix as the Loom's mg-model-picker.js: a raw mouseenter re-triggered an
    instant, freshly-repositioned popup on every card the mouse passed over while
    scanning the grid. This is fundamentally a feel/timing bug (real verification is
    manual, in a browser) -- this only guards against reverting to the raw wiring."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "c.onmouseenter=function(){ scheduleShowPreview(m, c); };" in html
    assert "c.onmouseleave=cancelPreview;" in html
    assert "function scheduleShowPreview(m, anchor){" in html
    assert "function cancelPreview(){ clearTimeout(previewTimer); hidePreview(); }" in html


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
    own = json.loads((tmp_path / "prompt_snippets" / "tester.json").read_text(encoding="utf-8"))
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
    import pixai_gallery as g

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
    import pixai_gallery as g
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
    import pixai_gallery as g
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
    from pixai_gallery import create_app
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
    own = json.loads((tmp_path / "toolbox_presets" / "tester.json").read_text(encoding="utf-8"))
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


def test_catalog_counts(tmp_path):
    import pixai_gallery as g
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
    import pixai_gallery as g
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
    import pixai_gallery as g
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
    pixai_gallery.py's docstring), so an unauthenticated LAN request never reaches
    index() at all -- it's redirected to /login instead of rendering anything."""
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    r = cli.get("/", environ_overrides={"REMOTE_ADDR": "192.168.1.50"})
    assert r.status_code in (301, 302, 303, 307, 308)
    assert "/login" in r.headers["Location"]


def test_logged_in_lan_request_gets_the_same_full_ui_as_local(tmp_path):
    """A LAN request carrying a valid login session is authorized exactly like the
    local owner -- the same Generate/Loom/Panel controls, no read-only banner. There
    is only ONE access tier once you're behind the front door (a logged-in session --
    see index()'s `is_local=True` comment for why that template flag is now a
    hardcoded constant rather than a live check). Both views below are captured
    AFTER logging in: an unauthenticated LOCAL request no longer gets the full owner
    UI either (owner directive 2026-07-19 removed the loopback bypass), so the only
    real distinction left to prove is authenticated-vs-not, never the request's
    address -- see test_unauthenticated_lan_request_to_index_is_redirected_to_login
    for that side of the boundary. Community + browse surfaces (Contests / My Art)
    render either way, as before."""
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


def test_enhance_shelf_promotes_official_tools(tmp_path):
    """The Enhance sub-tab leads with a grouped shelf of curated one-click official tools
    (Upscale / Cleanup / Convert / Light) above the flat 140+ community list — so real
    tools aren't buried among junk workflows. Each card fires Gen.selectEnhance(<workflow_id>,
    <name>) -- D-12: select-then-run now, not click-runs-immediately (see below)."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert 'class="enh-shelf"' in html
    for section in ("Upscale", "Cleanup", "Convert", "Light"):
        assert ">" + section + "<" in html
    # a few of the curated official workflow ids are wired as one-click cards
    for wid in ("1794855217667308480",   # Image Upscale
                "1793505053210462325",   # Remove background
                "1793713293591365899",   # Basic Outpainting
                "1801729774701480692"):  # relight sunshine
        assert "Gen.selectEnhance('" + wid + "'," in html
    assert 'id="enh-q"' in html          # the browse-all search still present below the shelf


def test_enhance_is_select_then_run_with_a_persistent_badge(tmp_path):
    """D-12: the one Enhance path that never got the <mg-cost-badge> treatment -- it used
    to price + window.confirm() on every click, the exact pattern every other price
    surface (Image/Edit/Video, and now this one) already replaced with a persistent
    badge. Now: click selects (no spend), a separate Run button fires it, and the badge
    is the only warning -- no window.confirm left anywhere in this path."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert '<mg-cost-badge id="enhance-cost"' in html
    assert 'id="enh-go" disabled' in html                 # nothing selected yet -> Run starts disabled
    assert "function selectEnhance(wid, name){" in html
    assert "function runEnhance(){" in html
    assert "window.confirm('This Enhance tool spends credits" not in html   # old inline confirm is gone
    assert "window.confirm('Run this Enhance tool?" not in html
    # selecting enables Run and (re)prices; switching source also reprices Enhance, not just Edit
    assert "el('enh-go').disabled=false;" in html
    assert "debEnhanceCost();" in html and "debEditCost();" in html         # setEditSource fires both


def test_enhance_price_uses_the_selected_tool_and_shared_source(tmp_path, monkeypatch):
    """/api/price's mode=enhance branch (already handled server-side, unchanged by D-12)
    still gets exactly {mode, source, workflow_id} -- this pins the client-side payload
    shape the new badge wiring builds, not just that the server accepts it."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    seen = {}
    monkeypatch.setattr(core, "price_task", lambda s, params: seen.update(p=params) or 4200)
    monkeypatch.setattr(core, "match_kaisuuken", lambda *a, **k: None)
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    r = cli.post("/api/price", json={"mode": "enhance", "source": "12345", "workflow_id": "999"})
    assert r.get_json()["cost"] == 4200
    assert seen["p"]["model"] == "pixai-panelplugin" and seen["p"]["workflowId"] == "999"


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
    assert "#model-flyout" in html and "translate(-50%, -50%)" in html  # flyout centered (was clipped)
    # Isolate the mobile breakpoint itself -- a bare substring check let this pass off
    # the DESKTOP #gen-drawer.wide{width:600px;} rule (a different breakpoint entirely),
    # so a broken/missing mobile override could ship invisibly. The tablet media query
    # right after this one is a stable end marker for the slice.
    mobile_block = html.split("@media (max-width: 480px)")[1].split("@media (min-width: 681px)")[0]
    assert "#gen-drawer, #gen-drawer.wide, #gen-drawer.dock-left, #gen-drawer.dock-right { width: 100%" in mobile_block, \
        "the mobile full-width drawer rule is missing from inside the 480px breakpoint"  # full-width sheet


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
    """Every surface that renders a live cost is a <mg-cost-badge> now, and every page carrying
    one MUST also load static/mg-cost-badge.js. A custom element whose definition never loads is
    an inert <div>: setChecking()/setPrice() throw, the cost line freezes on its idle hint, and
    the Go button beside it still spends. That failure is silent and it is on the spend path, so
    the pairing gets a test rather than a convention -- the same reasoning that put the drawer's
    own script tag under test above."""
    import pixai_gallery as pg
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


def test_generate_card_has_seed_field(tmp_path):
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert 'id="gen-seed"' in html and "seed:(el('gen-seed')" in html   # UI + payload wire the seed


def test_generate_drawer_blocks_submit_on_unresolved_lora(tmp_path):
    """A LoRA whose /api/model-version lookup never resolves (still pending, or
    permanently failed) used to just vanish from payload()'s loras filter -- the
    generation submitted anyway, spending full credits on a result silently missing
    a LoRA the user believed was included, with nothing on screen but an hourglass
    that never explained itself (audit: fail-open, 2026-07-21). Fixed: the lookup's
    failure path is distinguished from success (entry.failed), Go is gated on every
    added LoRA having actually resolved, and generate() refuses to submit even if
    something got the disabled button clicked anyway."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    # The silent-drop shape must be gone: a bare `.catch(function(){ renderLoras(); });`
    # right after the model-version fetch, with no failed-state tracking at all.
    assert ".catch(function(){ renderLoras(); });" not in html
    assert "entry.failed=true" in html
    assert "entry.failed=!entry.version_id" in html
    assert "function anyLoraUnresolved(){ return loras.some(function(l){ return !l.version_id; }); }" in html
    assert "anyIncompat() || anyLoraUnresolved()" in html          # Go button gate
    assert "if(anyLoraUnresolved()){ el('gen-lora-note').scrollIntoView" in html   # submit-time guard


def test_enhance_price_routes_panelplugin_and_guards_spend(tmp_path, monkeypatch):
    """/api/price mode=enhance builds panelplugin params so a real cost can be shown.

    The spend guardrail used to be a hardcoded window.confirm() claiming "free cards do
    not cover Enhance workflows" -- D-12 replaced it with the persistent <mg-cost-badge>
    (test_enhance_is_select_then_run_with_a_persistent_badge), which reflects PixAI's
    REAL per-request match_kaisuuken result instead of a fixed claim baked into a string.
    This test now only pins the price-routing params; the badge test above owns the
    guardrail assertion."""
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "price_task", lambda s, params: seen.update(p=params) or 8000)
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, enrich=False: None)
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    cli.post("/api/price", json={"mode": "enhance", "source": "55",
                                 "workflow_id": "1794855217667308480"})
    assert seen["p"]["model"] == "pixai-panelplugin"
    assert str(seen["p"].get("workflowId")) == "1794855217667308480"


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
