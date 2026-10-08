"""Session Q (Q7), the phone's Data saver: the 256 px thumbnail tier, `/thumbs/<id>.jpg?s=256`.

It is the Sibling Strip's `?s=32` mechanism with a second key on the same allowlist: derived from
the 768 thumb (never the master), cached beside the badge cache, self-healing, read-only, and
additive -- the plain route and every unlisted size are untouched. The 32 px tier's own guards live in
dev/tests/test_siblings.py; these pin what the new key adds, and that the two tiers cannot cross.

Also here: a HEAD on `/full/<id>` answers the file's size without sending it, which is what the
Lightbox's "Tap to load full size · 2.4 MB" reads (Flask answers HEAD on the GET route; the test
pins that the size is really there, and that it costs no image bytes).
"""
import io
import os
import time

from PIL import Image

from moonglade import gallery as G


def _seed(tmp_path, mids):
    (tmp_path / "2026-08").mkdir(parents=True, exist_ok=True)
    rows = []
    for mid in mids:
        name = "2026-08/pic_%s.png" % mid
        Image.new("RGB", (900, 600), (90, 60, 140)).save(tmp_path / name)
        rows.append({f: "" for f in G.CATALOG_FIELDS} | {
            "media_id": mid, "filename": name, "created_at": "2026-08-22T01:02:03Z"})
    G.save_catalog(tmp_path / "catalog.db", rows)


def _seed_768(tmp_path, mid, color=(200, 30, 30), size=(768, 512)):
    d = tmp_path / "gallery" / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(d / (mid + ".jpg"), "JPEG")
    return d / (mid + ".jpg")


def _client(tmp_path):
    from tests.conftest import login_test_client
    return login_test_client(G.create_app(tmp_path))


def _size(data):
    with Image.open(io.BytesIO(data)) as im:
        return im.size


def test_the_256_tier_is_256_on_the_long_side_and_cached_beside_the_strip_cache(tmp_path):
    _seed(tmp_path, ["901"])
    _seed_768(tmp_path, "901")
    cli = _client(tmp_path)
    r = cli.get("/thumbs/901.jpg?s=256")
    assert r.status_code == 200
    w, h = _size(r.data)
    assert w == 256 and h <= 256, (w, h)                  # aspect kept, longest side 256
    assert r.headers["Cache-Control"] == "public, max-age=300"   # the 768's own policy
    cached = tmp_path / "gallery" / "cache" / "_t256" / "901.jpg"
    assert cached.is_file() and _size(cached.read_bytes())[0] == 256
    # nothing landed in the goods tree, and the 32 tier's folder was never touched
    assert not list((tmp_path / "2026-08").glob("*.jpg"))
    assert not (tmp_path / "gallery" / "cache" / "_strip").exists()


def test_the_two_tiers_do_not_cross(tmp_path):
    _seed(tmp_path, ["902"])
    _seed_768(tmp_path, "902")
    cli = _client(tmp_path)
    assert _size(cli.get("/thumbs/902.jpg?s=32").data)[0] == 32
    assert _size(cli.get("/thumbs/902.jpg?s=256").data)[0] == 256
    assert _size(cli.get("/thumbs/902.jpg").data) == (768, 512)       # the plain route is untouched
    assert (tmp_path / "gallery" / "cache" / "_strip" / "902.jpg").is_file()
    assert (tmp_path / "gallery" / "cache" / "_t256" / "902.jpg").is_file()


def test_the_256_tier_recuts_when_the_768_is_newer_and_reuses_an_up_to_date_cache(tmp_path):
    _seed(tmp_path, ["903"])
    src = _seed_768(tmp_path, "903", (10, 10, 200))
    cli = _client(tmp_path)
    assert cli.get("/thumbs/903.jpg?s=256").status_code == 200
    cached = tmp_path / "gallery" / "cache" / "_t256" / "903.jpg"
    first, mtime = cached.read_bytes(), cached.stat().st_mtime
    assert cli.get("/thumbs/903.jpg?s=256").status_code == 200
    assert cached.stat().st_mtime == mtime, "an up-to-date cache must not be re-cut"
    _seed_768(tmp_path, "903", (10, 200, 10))                          # a rebuilt poster
    newer = mtime + 5
    os.utime(src, (newer, newer))
    assert cli.get("/thumbs/903.jpg?s=256").status_code == 200
    assert cached.read_bytes() != first


def test_an_unlisted_size_a_missing_768_and_a_bad_id_all_fall_through(tmp_path):
    _seed(tmp_path, ["904", "905"])
    _seed_768(tmp_path, "904")
    cli = _client(tmp_path)
    r = cli.get("/thumbs/904.jpg?s=257")                               # not on the allowlist
    assert r.status_code == 200 and _size(r.data) == (768, 512)
    assert not (tmp_path / "gallery" / "cache" / "_t256").exists()
    assert cli.get("/thumbs/905.jpg?s=256").status_code == 404         # no 768 to derive from
    for bad in ("C:x", "D:anything", "x;y"):
        assert cli.get("/thumbs/" + bad + ".jpg?s=256").status_code == 404, bad
    assert not (tmp_path / "gallery" / "cache" / "_t256").exists(), "no cache dir for a bad id"


def test_a_thumb_smaller_than_the_tier_is_served_as_it_is_never_enlarged(tmp_path):
    _seed(tmp_path, ["906"])
    _seed_768(tmp_path, "906", size=(120, 80))
    cli = _client(tmp_path)
    assert _size(cli.get("/thumbs/906.jpg?s=256").data) == (120, 80)


def test_the_256_tier_needs_a_login(tmp_path):
    _seed(tmp_path, ["907"])
    _seed_768(tmp_path, "907")
    cli = G.create_app(tmp_path).test_client()                         # no session
    r = cli.get("/thumbs/907.jpg?s=256")
    assert r.status_code in (302, 401, 403)


def test_head_on_full_reports_the_size_without_sending_the_image(tmp_path):
    _seed(tmp_path, ["908"])
    cli = _client(tmp_path)
    on_disk = os.path.getsize(tmp_path / "2026-08" / "pic_908.png")
    r = cli.head("/full/908")
    assert r.status_code == 200
    assert int(r.headers["Content-Length"]) == on_disk
    assert r.data == b""
    assert cli.head("/full/nope").status_code == 404
