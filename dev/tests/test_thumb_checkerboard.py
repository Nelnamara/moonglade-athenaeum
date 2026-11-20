"""See-through pictures' thumbnails sit on a dim checkerboard; opaque ones are unchanged;
old thumbnails of see-through sources rebuild themselves exactly once."""
import io

from moonglade import gallery as g
from moonglade.gallery import CATALOG_FIELDS


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _holey_png(path, size=(100, 100)):
    """Opaque red square in the middle, fully see-through everywhere else."""
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    im.paste((220, 30, 30, 255), (30, 30, 70, 70))
    im.save(path)


def _close(a, b, tol=6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_see_through_png_gets_checkerboard(tmp_path):
    from PIL import Image
    src, dst = tmp_path / "a.png", tmp_path / "t" / "a.jpg"
    _holey_png(src)
    assert g.make_thumbnail(src, dst) is True
    with Image.open(dst) as t:
        t = t.convert("RGB")
        assert t.size == (100, 100)
        # top-left 12px square is the first colour, the next one over the second
        assert _close(t.getpixel((5, 5)), g.CHECKER_A)
        assert _close(t.getpixel((17, 5)), g.CHECKER_B)
        assert _close(t.getpixel((5, 17)), g.CHECKER_B)
        # the opaque middle shows the picture
        assert _close(t.getpixel((50, 50)), (220, 30, 30), tol=12)


def test_opaque_thumbnail_is_unchanged(tmp_path):
    from PIL import Image
    src, dst = tmp_path / "o.png", tmp_path / "o.jpg"
    Image.effect_mandelbrot((90, 60), (-3, -2.5, 2, 2.5), 30).convert("RGB").save(src)
    assert g.make_thumbnail(src, dst) is True
    with Image.open(src) as im:                      # the old path, spelled out
        im = im.convert("RGB")
        im.thumbnail(g.THUMB_SIZE, Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=g.THUMB_QUALITY)
    assert dst.read_bytes() == buf.getvalue()
    # an RGBA picture with no see-through pixel takes the same path
    src2 = tmp_path / "o2.png"
    Image.open(src).convert("RGBA").save(src2)
    dst2 = tmp_path / "o2.jpg"
    g.make_thumbnail(src2, dst2)
    assert dst2.read_bytes() == buf.getvalue()


def test_gif_first_frame_with_transparency_gets_checkerboard(tmp_path):
    from PIL import Image
    src, dst = tmp_path / "g.gif", tmp_path / "g.jpg"
    f1 = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    f2 = Image.new("RGBA", (40, 40), (0, 255, 0, 255))
    f1.save(src, save_all=True, append_images=[f2], loop=0, disposal=2)
    g.make_thumbnail(src, dst)
    with Image.open(dst) as t:
        assert _close(t.convert("RGB").getpixel((5, 5)), g.CHECKER_A, tol=8)


def test_old_see_through_thumbnails_rebuild_once(tmp_path):
    from PIL import Image
    thumbs = tmp_path / "gallery" / "thumbs"
    thumbs.mkdir(parents=True)
    _holey_png(tmp_path / "a_1.png")
    Image.new("RGB", (50, 50), (9, 9, 9)).save(tmp_path / "b_2.png")
    for mid in ("1", "2"):                               # old-style thumbs: black box / flat
        Image.new("RGB", (50, 50), (0, 0, 0)).save(thumbs / (mid + ".jpg"))
    old_opaque = (thumbs / "2.jpg").read_bytes()
    rows = [_row(media_id="1", filename="a_1.png"), _row(media_id="2", filename="b_2.png")]

    g.build_thumbnails(rows, tmp_path, thumbs, workers=1)
    with Image.open(thumbs / "1.jpg") as t:
        assert _close(t.convert("RGB").getpixel((5, 5)), g.CHECKER_A)
    assert (thumbs / "2.jpg").read_bytes() == old_opaque     # opaque one not rebuilt
    assert (thumbs / g.CHECKER_MARKER).exists()

    # second pass: marker present, nothing is re-examined or rebuilt
    (thumbs / "1.jpg").write_bytes(b"sentinel")
    g.build_thumbnails(rows, tmp_path, thumbs, workers=1)
    assert (thumbs / "1.jpg").read_bytes() == b"sentinel"
