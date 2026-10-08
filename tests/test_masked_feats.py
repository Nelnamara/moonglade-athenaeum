"""Masked feats (Session G): the Folio's ONE veil card and what the server will and will not
say about the feat behind it.

The contract these tests hold still (design/notes/masked-feats/NOTES.md, "Server contract"):

  feats.masked   None, or {riddle, mask_url} for the next unfound feat the server picks.
                 mask_url names an ALPHA-ONLY PNG through an opaque token, and the route
                 serves only the CURRENT pick's mask.
  never sent     id, name, description, count, order, points, earned-by, badge art, file
                 name -- of a feat that is still masked.

Every roster here is SYNTHETIC (tests/synthetic_feats.py): invented feats, invented riddles.
Nothing asserts on a real feat, so nothing here needs the private donor and these run in
public CI too.
"""
import io
import json

import pytest
from PIL import Image

from moonglade import gallery as g
from moonglade.gallery import CATALOG_FIELDS, save_catalog

from tests import synthetic_feats as sf
from tests.conftest import login_client


@pytest.fixture(autouse=True)
def _fresh_seal_cache():
    g._earned_ids_cache.update(t=0.0, ids=frozenset())
    yield
    g._earned_ids_cache.update(t=0.0, ids=frozenset())


def _client(tmp_path, **seed_kw):
    """A logged-in client on an install whose sealed roster is the synthetic one, with a
    loose badge for every synthetic feat."""
    rows = [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "1", "filename": "a_1.png", "created_at": "2025-01-01T00:00:00"}]
    save_catalog(tmp_path / "catalog.db", rows)
    sf.seed(g._container_path(), **seed_kw)
    cli = login_client(tmp_path)
    sf.all_badges()                       # after the app exists: create_app sweeps the tree
    return cli


def _feats(cli):
    return cli.get("/api/achievements").get_json()


def _mask_token(d):
    return d["feats"]["masked"]["mask_url"].rsplit("/", 1)[1][:-len(".png")]


# ---- the payload ---------------------------------------------------------------------

def test_the_veil_is_cloaked_until_a_first_feat_is_earned(tmp_path):
    cli = _client(tmp_path)
    d = _feats(cli)
    assert d["feats"] == {"masked": None, "all_found": False}
    assert d["feats_revealed"] is False
    text = json.dumps(d)
    assert "test riddle" not in text and "feat-mask" not in text


def test_the_next_unfound_feat_is_the_one_the_veil_is_drawn_for(tmp_path):
    cli = _client(tmp_path)
    sf.earn(tmp_path, sf.FEAT_IDS[1])                       # any first earn opens the section
    d = _feats(cli)
    m = d["feats"]["masked"]
    assert m["riddle"] == "test riddle one"                 # roster order picks feat one
    assert m["mask_url"].startswith("/feat-mask/") and m["mask_url"].endswith(".png")
    assert set(m) == {"riddle", "mask_url"}                 # nothing else rides it
    assert d["feats"]["all_found"] is False
    sf.earn(tmp_path, sf.FEAT_IDS[0])
    assert _feats(cli)["feats"]["masked"]["riddle"] == "test riddle three"


def test_hidden_feats_ride_the_array_only_once_earned_and_no_placeholder_remains(tmp_path):
    cli = _client(tmp_path)
    sf.earn(tmp_path, sf.FEAT_IDS[1])
    d = _feats(cli)
    ids = [a["id"] for a in d["achievements"]]
    assert sf.FEAT_IDS[1] in ids                            # earned: listed, as before
    for hidden in (sf.FEAT_IDS[0], sf.FEAT_IDS[2], sf.BARE_ID, sf.TRIGGER_ID):
        assert hidden not in ids
    assert "hidden-feat" not in ids
    assert not [a for a in d["achievements"] if a["name"] == "???"]
    assert d["feats_revealed"] is True                      # the flag that opens the section
    # the array is exactly the visible entry plus the one earned feat: its length says
    # nothing about how many secrets are left
    assert len(d["achievements"]) == 2


def test_the_masked_feat_leaks_nothing_in_the_payload(tmp_path):
    cli = _client(tmp_path)
    sf.earn(tmp_path, sf.FEAT_IDS[1])
    d = _feats(cli)
    assert d["feats"]["masked"]["riddle"] == "test riddle one"
    text = json.dumps(d)
    leaks = [
        sf.FEAT_IDS[0],                                     # id
        "Synthetic Feat One", "Feat One",                   # name
        "Synthetic description one",                        # description
        "synthetic clean roast one", "synthetic unleashed roast one",   # roasts
        str(sf.DISTINCT_THRESHOLD),                         # count / threshold
        "synth_metric_one",                                 # its metric
        sf.FEAT_IDS[0] + ".png", sf.FEAT_IDS[0] + ".webp",  # badge file names
        "test riddle one, unleashed",                       # the twin, without the unleash gate
    ]
    for needle in leaks:
        assert needle not in text, needle
    # nor do the other still-hidden feats
    for other in (sf.FEAT_IDS[2], "Synthetic Feat Three", "test riddle three",
                  sf.BARE_ID, "Synthetic Feat Bare"):
        assert other not in text, other
    # the earned feat is listed exactly as before (its own name is fair game)
    assert "Synthetic Feat Two" in text


def test_the_riddle_twin_rides_only_with_the_unleash_gate(tmp_path):
    """Gated exactly as roast_nsfw is: present once Triggered is earned, and only then."""
    cli = _client(tmp_path)
    sf.earn(tmp_path, sf.FEAT_IDS[1])
    d = _feats(cli)
    assert d["unleash_available"] is False
    assert "riddle_nsfw" not in d["feats"]["masked"]
    assert "unleashed" not in json.dumps(d["feats"])
    sf.earn(tmp_path, sf.TRIGGER_ID)
    d = _feats(cli)
    assert d["unleash_available"] is True
    assert d["feats"]["masked"]["riddle"] == "test riddle one"
    assert d["feats"]["masked"]["riddle_nsfw"] == "test riddle one, unleashed"


def test_a_pack_with_no_riddles_shows_no_veil_and_invents_nothing(tmp_path):
    cli = _client(tmp_path, riddles=False)
    sf.earn(tmp_path, sf.FEAT_IDS[1])
    d = _feats(cli)
    assert d["feats"]["masked"] is None
    assert d["feats"]["all_found"] is False                 # NOT "every secret found"
    assert "riddle" not in json.dumps(d)


def test_a_feat_without_a_riddle_or_without_art_is_never_picked(tmp_path):
    cli = _client(tmp_path, bare_first=True)                # the riddle-less feat is first
    sf.earn(tmp_path, sf.FEAT_IDS[1])
    assert _feats(cli)["feats"]["masked"]["riddle"] == "test riddle one"
    (g._role_dir("badges") / (sf.FEAT_IDS[0] + ".png")).unlink()    # no art to cut a mask from
    assert _feats(cli)["feats"]["masked"]["riddle"] == "test riddle three"


def test_all_found_only_when_every_hidden_feat_is_earned(tmp_path):
    cli = _client(tmp_path)
    sf.earn(tmp_path, *sf.FEAT_IDS, sf.BARE_ID)
    d = _feats(cli)
    assert d["feats"] == {"masked": None, "all_found": False}   # the trigger feat is still hidden
    sf.earn(tmp_path, sf.TRIGGER_ID)
    assert _feats(cli)["feats"] == {"masked": None, "all_found": True}


def test_no_container_means_no_veil_and_no_crash(tmp_path):
    rows = [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "1", "filename": "a_1.png", "created_at": "2025-01-01T00:00:00"}]
    save_catalog(tmp_path / "catalog.db", rows)
    g._container_path().unlink(missing_ok=True)
    from tests.conftest import clear_sealed_caches
    clear_sealed_caches()
    d = login_client(tmp_path).get("/api/achievements").get_json()
    assert d["feats"] == {"masked": None, "all_found": False}


# ---- the mask route ------------------------------------------------------------------

def test_the_mask_is_an_alpha_only_silhouette_never_the_badge_art(tmp_path):
    cli = _client(tmp_path)
    sf.earn(tmp_path, sf.FEAT_IDS[1])
    m = _feats(cli)["feats"]["masked"]
    r = cli.get(m["mask_url"])
    assert r.status_code == 200 and r.mimetype == "image/png"
    im = Image.open(io.BytesIO(r.data))
    assert im.mode == "RGBA" and max(im.size) <= g.FEAT_MASK_PX
    px = [im.getpixel((x, y)) for x in range(im.width) for y in range(im.height)]
    assert any(a > 0 for *_c, a in px) and any(a == 0 for *_c, a in px)    # a real silhouette
    assert all((r_, g_, b) == (255, 255, 255) for r_, g_, b, _a in px)     # white, never the art
    assert (200, 30, 60) not in {(r_, g_, b) for r_, g_, b, _a in px}
    # the response says nothing about the feat: not in a header, not in the body
    blob = (r.data + repr(dict(r.headers)).encode()).lower()
    for needle in (sf.FEAT_IDS[0], "synthetic", "feat one", "test riddle"):
        assert needle.encode() not in blob, needle
    assert "private" in r.headers["Cache-Control"]


def test_the_route_serves_only_the_current_picks_mask(tmp_path):
    cli = _client(tmp_path)
    assert cli.get("/feat-mask/" + "a" * 32 + ".png").status_code == 404      # before any earn
    sf.earn(tmp_path, sf.FEAT_IDS[1])
    d = _feats(cli)
    good = _mask_token(d)
    assert cli.get("/feat-mask/%s.png" % good).status_code == 200
    unknown = cli.get("/feat-mask/" + "0" * 32 + ".png")
    # the token of a feat that is NOT the current pick (a later one, an earned one, the
    # token of a hidden feat with no riddle) answers exactly as an unknown token does
    secret = cli.application.secret_key
    for aid in (sf.FEAT_IDS[1], sf.FEAT_IDS[2], sf.BARE_ID, sf.TRIGGER_ID):
        r = cli.get("/feat-mask/%s.png" % g._feat_mask_token(secret, aid))
        assert r.status_code == 404 and r.get_data() == unknown.get_data(), aid
    assert unknown.status_code == 404
    # malformed tokens: the same bare 404
    for bad in ("nothex", "A" * 32, "0" * 31, "0" * 33, sf.FEAT_IDS[0]):
        r = cli.get("/feat-mask/%s.png" % bad)
        assert r.status_code == 404 and r.get_data() == unknown.get_data(), bad


def test_earning_the_veils_feat_moves_the_mask_and_retires_the_old_token(tmp_path):
    cli = _client(tmp_path)
    sf.earn(tmp_path, sf.FEAT_IDS[1])
    first = _mask_token(_feats(cli))
    assert cli.get("/feat-mask/%s.png" % first).status_code == 200
    sf.earn(tmp_path, sf.FEAT_IDS[0])                       # the veil's feat is found
    second = _mask_token(_feats(cli))
    assert second != first
    assert cli.get("/feat-mask/%s.png" % second).status_code == 200
    assert cli.get("/feat-mask/%s.png" % first).status_code == 404


def test_the_mask_is_served_the_moment_the_earn_lands_not_after_the_cache_expires(tmp_path):
    """The client asks for the mask right after the payload that named it. The earned-ids
    cache (5 s) must not answer that request with the state from before the earn."""
    cli = _client(tmp_path)
    assert cli.get("/feat-mask/" + "1" * 32 + ".png").status_code == 404   # warms the cache: nothing earned
    st = g.load_ach_state(tmp_path)
    st["earned_at"] = {sf.FEAT_IDS[1]: "2026-09-01"}
    g.save_ach_state(tmp_path, st)                          # NOT clearing the cache, on purpose
    m = _feats(cli)["feats"]["masked"]
    assert cli.get(m["mask_url"]).status_code == 200


def test_the_token_is_opaque_and_install_specific():
    t1 = g._feat_mask_token("secret-a", "some-id")
    t2 = g._feat_mask_token("secret-b", "some-id")
    assert len(t1) == 32 and all(c in "0123456789abcdef" for c in t1)
    assert t1 != t2                                         # not computable without the secret
    assert "some-id" not in t1 and t1 == g._feat_mask_token("secret-a", "some-id")   # stable
    assert g._feat_mask_token("secret-a", "other-id") != t1


def test_the_route_needs_a_login(tmp_path):
    cli = _client(tmp_path)
    anon = cli.application.test_client()
    r = anon.get("/feat-mask/" + "0" * 32 + ".png")
    assert r.status_code in (302, 401, 403)


def test_the_cut_is_cached_by_token_never_by_id(tmp_path):
    cli = _client(tmp_path)
    sf.earn(tmp_path, sf.FEAT_IDS[1])
    m = _feats(cli)["feats"]["masked"]
    token = _mask_token({"feats": {"masked": m}})
    assert cli.get(m["mask_url"]).status_code == 200
    d = g.feat_mask_cache_dir(tmp_path)
    assert d == tmp_path / "cache" / "masks"      # local/cache/masks (conftest's local_dir)
    names = [p.name for p in d.iterdir()]
    assert names == [token + ".png"]
    assert not any(sf.FEAT_IDS[0] in n for n in names)
    assert g.branding_root() not in d.parents               # outside the coded tree
    # a re-cut badge master heals the cache
    before = (d / names[0]).read_bytes()
    src = sf.badge_png(sf.FEAT_IDS[0], size=120)
    import os, time
    os.utime(src, (time.time() + 5, time.time() + 5))
    assert cli.get(m["mask_url"]).status_code == 200
    assert (d / names[0]).read_bytes() != before


# ---- the pure helper -------------------------------------------------------------------

def _png(im):
    b = io.BytesIO()
    im.save(b, format="PNG")
    return b.getvalue()


def test_feat_mask_png_keeps_the_alpha_and_drops_the_colour():
    src = Image.new("RGBA", (40, 40), (10, 200, 30, 0))
    for x in range(10, 30):
        for y in range(10, 30):
            src.putpixel((x, y), (10, 200, 30, 180))        # semi-opaque square
    out = Image.open(io.BytesIO(g.feat_mask_png(_png(src))))
    assert out.mode == "RGBA" and out.size == (40, 40)
    assert out.getpixel((20, 20)) == (255, 255, 255, 180)
    assert out.getpixel((2, 2)) == (255, 255, 255, 0)


def test_feat_mask_png_caps_the_size_and_handles_odd_inputs():
    big = Image.new("RGBA", (1000, 600), (0, 0, 0, 255))
    out = Image.open(io.BytesIO(g.feat_mask_png(_png(big), max_px=128)))
    assert max(out.size) == 128 and out.size[0] > out.size[1]
    opaque = Image.new("RGB", (30, 30), (5, 6, 7))          # no alpha: a solid silhouette
    solid = Image.open(io.BytesIO(g.feat_mask_png(_png(opaque))))
    assert solid.getpixel((15, 15)) == (255, 255, 255, 255)
    pal = Image.new("P", (20, 20), 0)
    pal.info["transparency"] = 0                            # palette + transparent index
    assert Image.open(io.BytesIO(g.feat_mask_png(_png(pal)))).getpixel((5, 5))[3] == 0
    assert g.feat_mask_png(b"not an image") is None
    assert g.feat_mask_png(b"") is None
