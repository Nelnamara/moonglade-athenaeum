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


def test_account_route_sums_cards(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "account_info", lambda s: {"quotaAmount": 330990})
    monkeypatch.setattr(core, "list_kaisuukens",
                        lambda s: [{"count": 16}, {"count": 34}, {"count": None}])
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    assert cli.get("/api/account").get_json() == {"credits": 330990, "cards": 50}


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


def test_branding_absent_is_404(tmp_path):
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2025-01-01T00:00:00")])
    assert cli.get("/branding/banner.png").status_code == 404      # onerror removes the img
    assert cli.get("/branding/../catalog.db").status_code == 404    # traversal rejected
