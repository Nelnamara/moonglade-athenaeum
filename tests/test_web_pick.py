"""The gallery Picker's web API: /api/gallery-images (browse the whole catalog with
paging + full prompts for the copy-to-clipboard feature) and /api/upload (local file
-> PixAI media_id via the free S3 handshake). All localhost-gated; upload_media is
monkeypatched so nothing touches the network."""
import io
import os

import pixai_gallery_backup as core
from pixai_gallery import CATALOG_FIELDS, create_app, save_catalog


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _client(tmp_path, rows):
    save_catalog(tmp_path / "catalog.db", rows)
    return create_app(tmp_path).test_client()


def test_gallery_images_works_from_lan_address(tmp_path):
    """The picker source must NOT be localhost-gated: a 0.0.0.0 server browsed via a
    LAN address (non-loopback remote_addr) still returns the catalog. This is the bug
    that made the picker show 'No images found' while the gallery was full."""
    cli = _client(tmp_path, [
        _row(media_id="1", filename="a_1.png", prompt_preview="p",
             created_at="2025-01-01T00:00:00"),
    ])
    d = cli.get("/api/gallery-images",
                environ_overrides={"REMOTE_ADDR": "192.168.1.50"}).get_json()
    assert len(d["images"]) == 1 and d["total"] == 1


def test_gallery_images_prefers_full_prompt(tmp_path):
    cli = _client(tmp_path, [
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
    cli = _client(tmp_path, rows)
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
    cli = _client(tmp_path, rows)
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
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    resp = cli.post("/api/upload", data={
        "file": (io.BytesIO(b"\x89PNG fake"), "pic.png"),
    }, content_type="multipart/form-data")
    assert resp.get_json() == {"media_id": "M123"}
    assert not os.path.exists(seen["path"])    # temp file removed after upload


def test_upload_requires_a_file(tmp_path):
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
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
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    assert cli.get("/api/tag-suggest?q=n").get_json() == {"tags": []}


def test_tag_suggest_route_returns_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "tag_search_gql", lambda s, q, first=8: ["no humans"])
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
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
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    d = cli.post("/api/price", json={"mode": "I2V", "images": ["55"], "prompt": "pan",
                                     "duration": 5, "video_model": "v3.2",
                                     "audio": True}).get_json()
    assert d["cost"] == 27500 and d["free"] is True and d["cards"] == 9
    i2v = seen["params"]["i2vPro"]
    assert i2v["mediaId"] == "55" and i2v["model"] == "v3.2"
    assert i2v["generateAudio"] is True


def test_price_route_video_needs_an_image(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no pricing without a source image")
    monkeypatch.setattr(core, "price_task", boom)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    d = cli.post("/api/price", json={"mode": "R2V", "images": []}).get_json()
    assert d["cost"] is None and "source image" in d["note"]


def test_account_route_sums_cards_and_coverage(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "account_info", lambda s: {
        "quotaAmount": 330990, "tasks": {"totalCount": 4}, "followerCount": 30, "followingCount": 4})
    monkeypatch.setattr(core, "list_kaisuukens",
                        lambda s: [{"count": 16}, {"count": 34}, {"count": None}])
    # 2 distinct local tasks (tA on two media, tB) out of 4 on the server -> 50% coverage
    cli = _client(tmp_path, [
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
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    assert cli.get("/api/snippets").get_json() == {"snippets": []}
    saved = cli.post("/api/snippets",
                     json={"snippets": ["masterpiece, 4k", "", "  ", "night"]}).get_json()
    assert saved == {"snippets": ["masterpiece, 4k", "night"]}   # blanks dropped
    assert (tmp_path / "prompt_snippets.json").exists()
    assert cli.get("/api/snippets").get_json() == {"snippets": ["masterpiece, 4k", "night"]}


def test_snippets_rejects_non_list(tmp_path):
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    assert cli.post("/api/snippets", json={"snippets": "nope"}).status_code == 400


def test_suggest_prompt_route(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "suggest_prompt", lambda s, mid: ["1girl, night", "a girl at night"])
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
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
    cli = _client(tmp_path, [
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
    cli = _client(tmp_path, [
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

    def fake_extract(vp, out):
        seen["video"] = vp
        with open(out, "wb") as fh:      # simulate a produced frame
            fh.write(b"png")
        return out
    monkeypatch.setattr(core, "extract_last_frame", fake_extract)
    monkeypatch.setattr(core, "upload_media", lambda s, p: "FRAME123")
    monkeypatch.setattr(core, "probe_video_duration", lambda p: 5.0)

    cli = _client(tmp_path, [_row(media_id="V9", filename="videos/shot_V9.mp4",
                                  is_video="1", created_at="2025-01-01T00:00:00")])
    d = cli.post("/api/loom/handoff", json={"video_media_id": "V9"}).get_json()
    assert d == {"frame_media_id": "FRAME123", "duration": 5.0}
    assert seen["video"].endswith("shot_V9.mp4")


def test_loom_handoff_needs_local_clip(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    cli = _client(tmp_path, [_row(media_id="X", filename="a_x.png",
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
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    d = cli.post("/api/presets", json={"task_id": "2030050946353349700"}).get_json()
    assert d["imported"] == "character-card"
    lst = cli.get("/api/presets").get_json()["presets"]
    assert lst["character-card"]["label"] == "Character Card"
    assert "prompt" not in lst["character-card"]          # GET never leaks the prompt body
    # price path uses the banked preset: canned prompt + sceneId + its model
    seen = {}
    monkeypatch.setattr(core, "price_task", lambda s, params: seen.update(p=params) or 8000)
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, enrich=False: None)
    cli.post("/api/price", json={"mode": "edit", "source": "55",
                                 "preset": "character-card"})
    assert seen["p"]["sceneId"] == "character-card"
    assert seen["p"]["chat"]["prompts"] == "BIG CANNED PROMPT"
    assert seen["p"]["chat"]["modelId"] == "1948514378441961474"


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
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    d = cli.get("/api/contests").get_json()             # default = active only
    assert d["official"] == 1 and d["community"] == 2   # 1 official + 2 running community
    assert all(c["active"] for c in d["contests"])


def test_your_art_ranks_published_and_enriches_views(tmp_path, monkeypatch):
    import pixai_gallery as g
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    # views come from a per-artwork call; mock it deterministically off the artwork_id
    monkeypatch.setattr(core, "artwork_views", lambda s, aid: {"aw1": 500, "aw2": 90}.get(aid, 0))
    cli = _client(tmp_path, [
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
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    assert cli.get("/api/artwork-views?id=aw9").get_json() == {"views": 174}
    assert cli.get("/api/artwork-views").get_json()["views"] is None   # missing id -> 400/null


def test_lan_view_hides_owner_only_controls(tmp_path):
    """On a LAN-served instance, owner-only controls (Generate / The Loom / Panel / balance chip)
    are localhost-gated -> the header hides them and shows a read-only note instead of dead buttons.
    Browse + community surfaces (Contests / My Art / Achievements / Health) stay."""
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    localhost = cli.get("/").get_data(as_text=True)
    lan = cli.get("/", environ_overrides={"REMOTE_ADDR": "192.168.1.50"}).get_data(as_text=True)
    # The Generate button (btn-primary) + The Loom header link are owner-only -> localhost only.
    _loom = "video storyboard, where shots"   # unique to the header Loom link title (owner-only)
    assert _loom in localhost and "read-only LAN view" not in localhost
    assert _loom not in lan and "read-only LAN view" in lan
    # community + browse surfaces survive on both
    for html in (localhost, lan):
        assert "Contests.open()" in html and "YourArt.open()" in html


def test_export_csv_downloads_as_attachment(tmp_path):
    """The web export is a real browser DOWNLOAD (attachment), not a file written into the
    backup folder. Localhost-only (owner data)."""
    cli = _client(tmp_path, [
        _row(media_id="1", filename="a_1.png", prompt_preview="p1", created_at="2025-01-01T00:00:00"),
        _row(media_id="2", filename="b_2.png", prompt_preview="p2", created_at="2025-01-02T00:00:00"),
    ])
    r = cli.get("/export-csv")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    cd = r.headers.get("Content-Disposition", "")
    assert "attachment" in cd and ".csv" in cd          # downloads, doesn't render
    lines = r.get_data(as_text=True).splitlines()
    assert "media_id" in lines[0]                        # header row present
    assert sum(1 for ln in lines[1:] if ln.strip()) == 2  # both rows exported
    # a LAN device can't pull the owner's catalog
    assert cli.get("/export-csv",
                   environ_overrides={"REMOTE_ADDR": "192.168.1.9"}).status_code == 403


def test_branding_absent_is_404(tmp_path):
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    assert cli.get("/branding/banner.png").status_code == 404      # onerror removes the img
    assert cli.get("/branding/../catalog.db").status_code == 404    # traversal rejected


def test_enhance_shelf_promotes_official_tools(tmp_path):
    """The Enhance sub-tab leads with a grouped shelf of curated one-click official tools
    (Upscale / Cleanup / Convert / Light) above the flat 140+ community list — so real
    tools aren't buried among junk workflows. Each card fires Gen.enhance(<workflow_id>)."""
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
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
        assert "Gen.enhance('" + wid + "')" in html
    assert 'id="enh-q"' in html          # the browse-all search still present below the shelf


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
    monkeypatch.setattr(core, "price_task", lambda s, params: seen.update(p=params) or 8000)
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, enrich=False: None)
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
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
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
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
    monkeypatch.setattr(core, "price_task", lambda s, params: seen.update(p=params) or 8000)
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, enrich=False: None)
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    cli.post("/api/price", json={"mode": "edit", "edit_model": "reference-pro", "source": "55",
                                 "resolution": "1K", "quality": "medium", "aspect": "3:4"})
    mc = seen["p"]["chat"]["modelConfig"]
    assert mc["resolution"] == "2K" and "quality" not in mc      # snapped + quality dropped


def test_edit_multi_reference_sources(tmp_path, monkeypatch):
    """Multi-image references: the Edit card sends sources[] -> chat.mediaIds carries them all
    (primary first), capped to the model's ref limit; falls back to [source] when absent."""
    seen = {}
    monkeypatch.setattr(core, "price_task", lambda s, params: seen.update(p=params) or 8000)
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, enrich=False: None)
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
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
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "@media (max-width: 480px)" in html
    assert "repeat(2, minmax(0, 1fr)) !important" in html           # 2-up grid, ignores saved --thumb
    assert "#model-flyout" in html and "translate(-50%, -50%)" in html  # flyout centered (was clipped)
    assert "#gen-drawer.wide { width: 100%" in html or "#gen-drawer.wide" in html  # full-width sheet


def test_video_v40_full_cost_warning(tmp_path):
    """The Video card hard-warns when the pricier v4.0 full model is picked (14k/s vs
    Lite's 5.5k -- a 15s clip is 210k credits), so it's never a silent surprise."""
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert ".gen-cost.warn" in html                 # the warn style
    assert "V4.0 full" in html and "2.5" in html      # the ~2.5x-Lite warning text


def test_toasts_anchored_top_right(tmp_path):
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "#mg-toasts{position:fixed;right:16px;top:64px" in html   # top-right, clear of the header


def test_generate_card_has_seed_field(tmp_path):
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert 'id="gen-seed"' in html and "seed:(el('gen-seed')" in html   # UI + payload wire the seed


def test_enhance_price_routes_panelplugin_and_guards_spend(tmp_path, monkeypatch):
    """/api/price mode=enhance builds panelplugin params (so cost can be shown), and the
    Enhance click carries a spend guardrail since free cards don't cover these workflows."""
    seen = {}
    monkeypatch.setattr(core, "price_task", lambda s, params: seen.update(p=params) or 8000)
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, enrich=False: None)
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    cli.post("/api/price", json={"mode": "enhance", "source": "55",
                                 "workflow_id": "1794855217667308480"})
    assert seen["p"]["model"] == "pixai-panelplugin"
    assert str(seen["p"].get("workflowId")) == "1794855217667308480"
    html = cli.get("/").get_data(as_text=True)
    assert "free cards do not cover Enhance" in html    # the confirm guardrail


def test_import_task_by_id(tmp_path, monkeypatch):
    """Panel 'Recover a task by ID' -> collect_generation. Localhost-gated; numeric-only;
    recovers edits/favorites-only tasks that Sync's listing skips."""
    called = {}
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, tid, out, **k: called.update(tid=tid) or {"saved": 1, "media_ids": ["m1"], "is_video": False})
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    assert cli.post("/api/import-task", json={"task_id": "123"},
                    environ_overrides={"REMOTE_ADDR": "192.168.1.9"}).status_code == 403   # LAN refused
    d = cli.post("/api/import-task", json={"task_id": "nope"}).get_json()
    assert d.get("error") and "tid" not in called                          # non-numeric rejected, no collect
    d = cli.post("/api/import-task", json={"task_id": "2030585251815688815"}).get_json()
    assert d["ok"] and d["saved"] == 1 and called["tid"] == "2030585251815688815"
    html = cli.get("/panel").get_data(as_text=True)
    assert 'id="import-tid"' in html and "importTask()" in html            # the panel card + wiring


def test_account_surfaces_cards_claim_and_subscription(tmp_path, monkeypatch):
    """The header balance surface exposes per-card breakdown + soonest expiry, claimable
    free credits, and the subscription cliff — the data the chip/badge/warnings render."""
    monkeypatch.setattr(core, "account_info", lambda s: {
        "quotaAmount": 140, "subscription": {"endAt": "2026-07-27T00:00:00Z", "cancelAtPeriodEnd": True}})
    monkeypatch.setattr(core, "list_kaisuukens", lambda s: [
        {"name": "Edit Pro Only", "count": 17, "expires": "2026-07-17T20:11:09Z"},
        {"name": "Reference Pro Only", "count": 5, "expires": "2026-07-17T20:11:09Z"}])
    monkeypatch.setattr(core, "list_claims", lambda s: [
        {"id": "pixai-daily-credits", "amount": 30000, "canClaim": True},
        {"id": "agent-daily-stamina", "amount": 20, "canClaim": True}])
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
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
    monkeypatch.setattr(core, "claim_reward", lambda s, cid: claimed.append(cid))
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    # LAN request refused (claiming is on the owner's account)
    assert cli.post("/api/claim", environ_overrides={"REMOTE_ADDR": "192.168.1.9"}).status_code == 403
    d = cli.post("/api/claim").get_json()
    assert d["claimed"] == 1 and d["credits"] == 30000       # only the ready credit reward
    assert claimed == ["pixai-daily-credits"]


def test_edit_card_has_reference_slots(tmp_path):
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert 'id="edit-refs"' in html and 'id="edit-ref-cap"' in html
    assert "renderEditRefs" in html and "editRefs" in html


def test_generate_card_has_size_and_custom_dimensions(tmp_path):
    """The Generate card must expose real dimensions — size presets + custom W/H + a wider
    aspect set — not the old 5 hardcoded ~512px buttons. The API has no size cap (backend
    _dim only floors to /8), so the card shouldn't self-throttle to half a megapixel."""
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
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
    cli = _client(tmp_path, [_row(media_id="9", filename="v_9.mp4", is_video="1",
                                  created_at="2025-02-01T00:00:00")])
    html = cli.get("/").get_data(as_text=True)
    assert "vid.load()" in html                       # explicit reload after src change
    assert "vid.currentTime = 0;" not in html          # the premature seek is gone
    assert "vid.error" in html                          # surfaces the MediaError code on failure


def test_service_worker_never_caches_misses(tmp_path):
    """The SW must NOT freeze a 404 (a thumbnail that didn't exist yet) into its cache --
    that was the 'blank video tile until a hard-refresh' bug. It must only cache OK
    responses, use a bumped cache name, and delete the old (poisoned) cache on activate
    so existing clients self-heal without Ctrl+Shift+R."""
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    sw = cli.get("/sw.js").get_data(as_text=True)
    assert "resp.ok" in sw and "c.put" in sw                # caches only successful fetches
    assert "pixai-img-v2" in sw and "pixai-img-v1" not in sw  # bumped cache name
    assert "caches.delete" in sw                            # purges the poisoned old cache
