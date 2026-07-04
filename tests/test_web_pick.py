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


def test_gallery_images_pages_and_skips_videos(tmp_path):
    rows = [_row(media_id=str(i), filename="f_{}.png".format(i), prompt_preview="p",
                 created_at="2025-01-{:02d}T00:00:00".format(i)) for i in range(1, 6)]
    rows.append(_row(media_id="9", filename="v_9.mp4", is_video="1",
                     created_at="2025-02-01T00:00:00"))
    cli = _client(tmp_path, rows)
    d1 = cli.get("/api/gallery-images?limit=2&page=1").get_json()
    d2 = cli.get("/api/gallery-images?limit=2&page=2").get_json()
    assert d1["total"] == 6                    # total counts all catalog rows
    ids1 = [m["media_id"] for m in d1["images"]]
    ids2 = [m["media_id"] for m in d2["images"]]
    assert ids1 and ids2 and not set(ids1) & set(ids2)   # paging advances
    assert "9" not in ids1 + ids2                        # video row filtered out


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
                        lambda s, params: {"id": "c1", "total": 9, "expiresAt": 1})
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


def test_editbay_handoff_extracts_and_uploads(tmp_path, monkeypatch):
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
    d = cli.post("/api/editbay/handoff", json={"video_media_id": "V9"}).get_json()
    assert d == {"frame_media_id": "FRAME123", "duration": 5.0}
    assert seen["video"].endswith("shot_V9.mp4")


def test_editbay_handoff_needs_local_clip(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    cli = _client(tmp_path, [_row(media_id="X", filename="a_x.png",
                                  created_at="2025-01-01T00:00:00")])
    d = cli.post("/api/editbay/handoff", json={"video_media_id": "nope"}).get_json()
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
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params: None)
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


def test_branding_absent_is_404(tmp_path):
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    assert cli.get("/branding/banner.png").status_code == 404      # onerror removes the img
    assert cli.get("/branding/../catalog.db").status_code == 404    # traversal rejected
