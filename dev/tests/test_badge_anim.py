"""The ANIMATED badge master: `/badge-thumb/<id>.webp`.

An animated medallion is a `<id>.webp` dropped beside the stills in the badges role.
The still-PNG route PIL-thumbnails its master, which would flatten an animation to one
frame, so the webp is served THROUGH instead -- byte-for-byte, unresized, un-re-encoded
(moonglade_gallery._badge_anim explains why: Pillow reads an animated webp's frames but
reports every frame's `duration` as None, so a re-encode invents the cadence the art was
authored at, and re-compresses the chroma-keyed alpha while it is at it).

Two things this file exists to hold still:

  * the STILL path must be untouched. `test_the_still_png_is_unchanged_byte_for_byte`
    serves the same master before and after an animation lands beside it and compares
    the bodies -- the feature is additive or it is a regression.
  * the animation must pass the SAME gate as the still. Both extensions land on one view
    function precisely so the roster / hidden-feat gate cannot be half-applied; the gate
    tests below re-prove it against the .webp rule anyway, because "we wrote it once" is
    an argument and a 404 is evidence.

Hermetic like dev/tests/test_unlock_split.py: conftest's _isolated_branding redirects
branding_root() into tmp_path, so every fake master here lives and dies with its test.
"""
import io

import pytest
from PIL import Image, ImageSequence

from moonglade import gallery as g
from moonglade.gallery import CATALOG_FIELDS, save_catalog

from tests.conftest import STARFALL_EVENT, ach_event, login_client


@pytest.fixture(autouse=True)
def _fresh_seal_cache():
    """Same isolation test_unlock_split takes: the earned-ids cache is module-global,
    and one test's earns must not leak an allow into the next one's fresh tmp_path."""
    g._earned_ids_cache.update(t=0.0, ids=frozenset())
    yield
    g._earned_ids_cache.update(t=0.0, ids=frozenset())


def _client(tmp_path):
    rows = [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "1", "filename": "a_1.png", "created_at": "2025-01-01T00:00:00"}]
    save_catalog(tmp_path / "catalog.db", rows)
    return login_client(tmp_path)


def _still(aid, size=300, color=(10, 20, 30, 255)):
    """Seed a loose STILL master at its coded rel and return its bytes."""
    bdir = g._role_dir("badges")
    bdir.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (size, size), color).save(bdir / (aid + ".png"))
    return (bdir / (aid + ".png")).read_bytes()


def _anim_bytes(frames=4, size=300):
    """An honest animated webp: several frames, real per-frame durations, live alpha."""
    ims = []
    for i in range(frames):
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))       # transparent ground
        im.paste((200, 40 * i % 255, 90, 255), (i * 10, i * 10, i * 10 + 120, i * 10 + 120))
        ims.append(im)
    buf = io.BytesIO()
    ims[0].save(buf, format="WEBP", save_all=True, append_images=ims[1:],
                duration=66, loop=0, lossless=True)
    return buf.getvalue()


def _anim(aid, **kw):
    """Seed a loose ANIMATED master beside the stills and return its bytes."""
    bdir = g._role_dir("badges")
    bdir.mkdir(parents=True, exist_ok=True)
    raw = _anim_bytes(**kw)
    (bdir / (aid + ".webp")).write_bytes(raw)
    return raw


def _visible_id():
    """A roster id that is NOT a hidden feat -- its art serves earned or not."""
    return "loremaster" if "loremaster" in g._ach_ids() else sorted(
        g._ach_ids() - g._ach_hidden())[0]


# ---- the still path is untouched --------------------------------------------

def test_the_still_png_is_unchanged_byte_for_byte(tmp_path, sealed_donor_present):
    """The whole feature is additive: dropping an animation beside a still must not
    change one byte of what the .png route already served."""
    cli = _client(tmp_path)
    aid = _visible_id()
    _still(aid)

    before = cli.get("/badge-thumb/" + aid + ".png")
    assert before.status_code == 200
    assert before.mimetype == "image/png"

    _anim(aid)                                   # the animation lands beside the still
    after = cli.get("/badge-thumb/" + aid + ".png")

    assert after.status_code == 200
    assert after.mimetype == "image/png"
    assert after.data == before.data
    assert after.headers["Cache-Control"] == before.headers["Cache-Control"]
    # ...and the 384px toast bucket is equally untouched.
    assert (cli.get("/badge-thumb/" + aid + ".png?size=384").status_code == 200)


def test_a_still_only_badge_404s_the_webp_and_still_serves_the_png(tmp_path, sealed_donor_present):
    """The normal case for almost every id: no animated master. The .webp 404 IS the
    fallback signal the client's chain drops to the .png on -- it is not an error."""
    cli = _client(tmp_path)
    aid = _visible_id()
    _still(aid)
    assert cli.get("/badge-thumb/" + aid + ".webp").status_code == 404
    assert cli.get("/badge-thumb/" + aid + ".png").status_code == 200


# ---- the animation serves THROUGH -------------------------------------------

def test_animated_master_serves_through_untouched(tmp_path, sealed_donor_present):
    """Byte-for-byte, as image/webp, with the badge route's own cache header -- and
    still animated on the far side (the flatten this feature exists to avoid)."""
    cli = _client(tmp_path)
    aid = _visible_id()
    _still(aid)
    raw = _anim(aid, frames=5)

    r = cli.get("/badge-thumb/" + aid + ".webp")

    assert r.status_code == 200
    assert r.mimetype == "image/webp"
    assert r.data == raw, "the master must be passed through, never re-encoded"
    assert r.headers["Cache-Control"] == "public, max-age=86400"
    served = Image.open(io.BytesIO(r.data))
    assert getattr(served, "is_animated", False)
    assert served.n_frames == 5
    assert len(list(ImageSequence.Iterator(served))) == 5


def test_an_animation_serves_with_no_still_beside_it(tmp_path, sealed_donor_present):
    """The two masters are independent: _badge_anim asks for the .webp, not for a pair."""
    cli = _client(tmp_path)
    aid = _visible_id()
    raw = _anim(aid)
    assert cli.get("/badge-thumb/" + aid + ".webp").data == raw
    assert cli.get("/badge-thumb/" + aid + ".png").status_code == 404


def test_an_oversized_animation_falls_back_to_the_still(tmp_path, monkeypatch,
                                                        sealed_donor_present):
    """Pass-through is whole-file, so the cap is the only brake there is. Over it, the
    .webp 404s and the client lands on the still -- a big animation degrades, never
    hangs a page on a multi-megabyte badge."""
    cli = _client(tmp_path)
    aid = _visible_id()
    _still(aid)
    raw = _anim(aid)
    monkeypatch.setattr(g, "_BADGE_ANIM_MAX_BYTES", len(raw) - 1)
    assert cli.get("/badge-thumb/" + aid + ".webp").status_code == 404
    assert cli.get("/badge-thumb/" + aid + ".png").status_code == 200
    monkeypatch.setattr(g, "_BADGE_ANIM_MAX_BYTES", len(raw))       # exactly at the cap
    assert cli.get("/badge-thumb/" + aid + ".webp").status_code == 200


# ---- the SAME gate as the still ---------------------------------------------

def test_hidden_feat_animation_is_gated_exactly_like_its_still(tmp_path, sealed_donor_present):
    """An unearned hidden feat's animation must be no more fishable by id than its
    still (dev/tests/test_unlock_split.py's badge-thumb gate, re-proved on the .webp rule)."""
    cli = _client(tmp_path)
    sf = g._moment_ach()["starfall"]          # the hidden feat the beacon below earns
    _still(sf)
    _anim(sf)
    assert cli.get("/badge-thumb/" + sf + ".webp").status_code == 404
    assert cli.get("/badge-thumb/" + sf + ".png").status_code == 404
    ach_event(cli, STARFALL_EVENT)
    assert cli.get("/badge-thumb/" + sf + ".webp").status_code == 200
    assert cli.get("/badge-thumb/" + sf + ".png").status_code == 200


def test_webp_gate_is_case_insensitive(tmp_path, sealed_donor_present):
    """The resolve is on a case-insensitive FS, so a case-variant URL would read the
    real sealed master while lowercase id-set membership missed it. Same casefold the
    .png rule takes (2026-08-22), now proved on the .webp one."""
    cli = _client(tmp_path)
    hid = g._moment_ach()["keyturn"]          # a hidden feat a fresh install has not earned
    _anim(hid)
    assert cli.get("/badge-thumb/" + hid + ".webp").status_code == 404
    assert cli.get("/badge-thumb/" + hid.upper() + ".webp").status_code == 404
    assert cli.get("/badge-thumb/" + hid.title() + ".webp").status_code == 404


def test_webp_fails_closed_on_unknown_id_and_missing_roster(tmp_path, monkeypatch):
    """Unknown id -> 404. Roster unavailable (no/invalid container) -> 404 for
    everything, including an id whose animation is sitting right there."""
    cli = _client(tmp_path)
    _anim("a-hidden-feat")
    _anim("totally-made-up")
    monkeypatch.setattr(g, "_ach_ids", lambda: frozenset())
    monkeypatch.setattr(g, "_ach_hidden", lambda: frozenset())
    assert cli.get("/badge-thumb/a-hidden-feat.webp").status_code == 404
    assert cli.get("/badge-thumb/totally-made-up.webp").status_code == 404


def test_webp_rejects_path_tricks(tmp_path, sealed_donor_present):
    """<aid> takes no slashes and no dot-dot -- the same path-safety the .png rule has."""
    cli = _client(tmp_path)
    assert cli.get("/badge-thumb/...webp").status_code == 404
    assert cli.get("/badge-thumb/..%2Fmoonglade.webp").status_code in (308, 404)


# ---- _badge_anim itself -----------------------------------------------------

def test_badge_anim_reads_through_the_container_path(tmp_path, monkeypatch):
    """No loose file at all: the bytes come from the container via _branding_bytes,
    exactly like the stills, and nothing is written to the thumb cache (there is no
    derived artefact -- the bytes served ARE the master)."""
    raw = _anim_bytes()
    seen = {}

    def _exists(rel):
        seen["exists"] = rel
        return rel.endswith(".webp")

    def _bytes(rel):
        seen["bytes"] = rel
        return raw if rel.endswith(".webp") else None

    monkeypatch.setattr(g, "_branding_exists", _exists)
    monkeypatch.setattr(g, "_branding_bytes", _bytes)

    assert g._badge_anim("first-light") == raw
    assert seen["exists"] == g._role_rel("badges", "first-light.webp")
    assert seen["bytes"] == seen["exists"]
    assert not g.badge_cache_dir(tmp_path).exists()


def test_badge_anim_is_none_when_there_is_no_animation(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "_branding_exists", lambda rel: False)
    assert g._badge_anim("first-light") is None


# ---- nothing is ever served larger than its source --------------------------
# Pack v7 re-encodes every animation at 360 px tall, smaller than the 384 px the celebration
# toast asks for. A request larger than the source serves the source size: the still is cut
# with Pillow's thumbnail(), which only ever shrinks, and the animation is passed through
# whole whatever was asked. These pin that, so a later "resize to the asked size" cannot
# quietly start blowing small art up.

def _only_badges(monkeypatch, *ids):
    """A roster of exactly these visible ids, so no donor is needed."""
    monkeypatch.setattr(g, "_ach_ids", lambda: frozenset(ids))
    monkeypatch.setattr(g, "_ach_hidden", lambda: frozenset())


def _served_size(resp):
    assert resp.status_code == 200
    return Image.open(io.BytesIO(resp.data)).size


def test_a_384_request_for_a_smaller_still_serves_the_still_size(tmp_path, monkeypatch):
    cli = _client(tmp_path)
    _only_badges(monkeypatch, "syn-small")
    _still("syn-small", size=360)
    assert _served_size(cli.get("/badge-thumb/syn-small.png?size=384")) == (360, 360)
    assert _served_size(cli.get("/badge-thumb/syn-small.png")) == (256, 256)   # still shrinks


def test_a_larger_still_is_cut_down_to_the_size_asked(tmp_path, monkeypatch):
    cli = _client(tmp_path)
    _only_badges(monkeypatch, "syn-big")
    _still("syn-big", size=960)
    assert _served_size(cli.get("/badge-thumb/syn-big.png?size=384")) == (384, 384)


def test_the_in_memory_cut_never_upscales_either(tmp_path, monkeypatch):
    """A pack-only master and a cache folder that cannot be written: the cut is made in
    memory and handed back as bytes -- under the same never-larger rule."""
    from moonglade import container as mc
    cli = _client(tmp_path)
    _only_badges(monkeypatch, "syn-small")
    buf = io.BytesIO()
    Image.new("RGBA", (300, 300), (10, 20, 30, 255)).save(buf, format="PNG")
    mc.write_container(g._container_path(),
                       {g._role_rel("badges", "syn-small.png"): buf.getvalue()}, {})
    g._container_cache.update(path=None, mtime=None, box=None)
    blocker = tmp_path / "not-a-folder"
    blocker.write_bytes(b"x")                               # mkdir under a file fails
    monkeypatch.setattr(g, "badge_cache_dir", lambda out_dir: blocker / "_badges")
    assert isinstance(g._badge_thumb(tmp_path, "syn-small", 384), bytes)
    assert _served_size(cli.get("/badge-thumb/syn-small.png?size=384")) == (300, 300)


def test_the_toasts_request_for_a_360px_animation_serves_it_whole(tmp_path, monkeypatch):
    """The toast's animated rung, the 384-size hint and all: a 360 px animation comes back
    byte-for-byte at 360 px, every frame, never resized up to the size the toast draws."""
    cli = _client(tmp_path)
    _only_badges(monkeypatch, "syn-anim")
    raw = _anim("syn-anim", frames=3, size=360)
    for url in ("/badge-thumb/syn-anim.webp", "/badge-thumb/syn-anim.webp?size=384"):
        r = cli.get(url)
        assert r.data == raw
        served = Image.open(io.BytesIO(r.data))
        assert served.size == (360, 360) and served.n_frames == 3
