"""Edit Pro's outputs once they exist (DESIGN_3.22 5.3, step S5): the format and a GIF's frames
recorded on the catalog row, a GIF's thumbnail drawn from its first frame, an SVG never asked
for a thumbnail and never counted as a failed one, and the picture list the Apple TV client
reads leaving SVG rows out (T-F12). Nothing here touches the network.
"""
import pytest

from moonglade import backup as core
from moonglade import gallery as g

pytest.importorskip("PIL")
from PIL import Image                                         # noqa: E402
from moonglade import catalog as catalog_mod
from moonglade import curation as curation_mod
from moonglade import thumbs as thumbs_mod
from moonglade import full_meta as full_meta_mod


def _task(outputs=None, model_config=None):
    chat = {"prompts": "x", "mediaId": "1", "mediaIds": ["1"], "modelId": "2061589941358465024",
            "modelConfig": dict({"resolution": "1K"}, **(model_config or {}))}
    return {"id": "T1", "parameters": {"chat": chat}, "outputs": dict(outputs or {})}


# ---------------------------------------------------------------------------
# The catalog row
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("outputs, mc, want", [
    ({"outputFormat": "svg"}, {"outputFormat": "svg"}, ("svg", "", "")),
    ({}, {"outputFormat": "gif", "frameCount": 9, "frameDurationMs": 170}, ("gif", "9", "170")),
    ({"outputFormat": "gif"}, {}, ("gif", "", "")),                 # PixAI's own word first
    ({"outputFormat": "SVG"}, {"outputFormat": "gif"}, ("svg", "", "")),
    ({}, {}, ("", "", "")),                                         # a png edit: blank
    ({"outputFormat": "png"}, {"outputFormat": "svg"}, ("", "", "")),
    ({}, {"outputFormat": "gif", "frameCount": True}, ("gif", "", "")),
])
def test_the_format_and_frames_are_recorded_from_the_task(outputs, mc, want):
    fm = full_meta_mod.extract_full_meta(_task(outputs, mc))
    assert (fm["output_format"], fm["frame_count"], fm["frame_duration_ms"]) == want


def test_an_ordinary_picture_records_nothing():
    fm = full_meta_mod.extract_full_meta({"id": "T1", "parameters": {"prompts": "x", "modelId": "1"},
                                 "outputs": {"mediaId": "9"}})
    assert (fm["output_format"], fm["frame_count"], fm["frame_duration_ms"]) == ("", "", "")


def test_the_new_columns_are_catalog_columns_and_surface_fields():
    for f in ("output_format", "frame_count", "frame_duration_ms"):
        assert f in catalog_mod.CATALOG_FIELDS
        assert f in full_meta_mod._GEN_SURFACE_FIELDS and f in full_meta_mod._FULL_META_FIELDS


def test_a_row_saved_with_the_format_reads_back(tmp_path):
    db = tmp_path / "catalog.db"
    row = dict({f: "" for f in catalog_mod.CATALOG_FIELDS}, media_id="5", filename="images/a_5.gif",
               output_format="gif", frame_count="9", frame_duration_ms="200")
    catalog_mod.save_catalog(db, [row])
    back = catalog_mod.get_row(db, "5")
    assert (back["output_format"], back["frame_count"], back["frame_duration_ms"]) == (
        "gif", "9", "200")


# ---------------------------------------------------------------------------
# Thumbnails: a GIF's first frame; an SVG never asked, never a failure
# ---------------------------------------------------------------------------

def _two_frame_gif(path):
    red = Image.new("RGB", (64, 64), (255, 0, 0))
    blue = Image.new("RGB", (64, 64), (0, 0, 255))
    red.save(path, save_all=True, append_images=[blue], duration=200, loop=0)


def test_a_gif_thumbnail_is_its_first_frame(tmp_path):
    src, thumb = tmp_path / "anim.gif", tmp_path / "thumbs" / "5.jpg"
    _two_frame_gif(src)
    with Image.open(src) as im:
        im.seek(1)                       # a reader that left it on frame 2 changes nothing
    assert thumbs_mod.make_thumbnail(src, thumb)
    with Image.open(thumb) as t:
        r, gr, b = t.convert("RGB").getpixel((t.width // 2, t.height // 2))
    assert r > 200 and b < 60


def test_an_svg_row_is_skipped_by_the_thumbnailer_and_never_counted_failed(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "logo_7.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"></svg>', encoding="utf-8")
    Image.new("RGB", (8, 8), (0, 255, 0)).save(tmp_path / "images" / "a_8.png")
    calls, drawn = [], []
    real = thumbs_mod.make_thumbnail
    rows = [{"media_id": "7", "filename": "images/logo_7.svg", "is_video": ""},
            {"media_id": "8", "filename": "images/a_8.png", "is_video": ""}]
    try:
        thumbs_mod.make_thumbnail = lambda src, dst: drawn.append(str(src)) or real(src, dst)
        thumbs_mod.build_thumbnails(rows, tmp_path, tmp_path / "thumbs",
                           progress_cb=lambda *a: calls.append(a), workers=1)
    finally:
        thumbs_mod.make_thumbnail = real
    assert not (tmp_path / "thumbs" / "7.jpg").exists() and (tmp_path / "thumbs" / "8.jpg").exists()
    assert not [d for d in drawn if d.endswith(".svg")]        # never asked for one
    assert calls[-1][:2] == (2, 2)                             # done == total: nothing failed


# ---------------------------------------------------------------------------
# The picture list the Apple TV client (and the create pickers) read
# ---------------------------------------------------------------------------

def test_the_picture_list_leaves_svg_rows_out(tmp_path):
    from tests.conftest import login_test_client
    blank = {f: "" for f in catalog_mod.CATALOG_FIELDS}
    rows = [dict(blank, media_id="1", filename="images/a_1.png", created_at="2026-11-01"),
            dict(blank, media_id="2", filename="images/logo_2.svg", created_at="2026-11-02"),
            dict(blank, media_id="3", filename="images/odd_3.png", output_format="svg",
                 created_at="2026-11-03"),
            dict(blank, media_id="4", filename="images/anim_4.gif", output_format="gif",
                 created_at="2026-11-04"),
            dict(blank, media_id="5", filename="images/LOGO_5.SVG", created_at="2026-11-05")]
    catalog_mod.save_catalog(tmp_path / "catalog.db", rows)
    cli = login_test_client(g.create_app(tmp_path))
    got = cli.get("/api/gallery-images?type=all&limit=100").get_json()
    assert sorted(i["media_id"] for i in got["images"]) == ["1", "4"]
    assert got["total"] == 2
    # the library grid itself still lists every row
    all_rows, total = curation_mod.query_catalog(tmp_path / "catalog.db", page_size=None)
    assert total == 5
