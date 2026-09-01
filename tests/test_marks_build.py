"""The marks build (2026-08-31): the settled animation roster, the four owner-tunable
settings, and the animated-webp lane.

Self-computing on purpose -- nothing here restates the roster or a threshold, so these
tests keep meaning what they say the next time the owner votes some animations out.
Hermetic: conftest's _isolated_branding points branding_root() at tmp_path, so every
mark written here lands in the test's own tree and never near a real install's art."""
import json

import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_test_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _client(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    return login_test_client(create_app(tmp_path))


def _png_bytes(color=(200, 30, 30)):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, format="PNG")
    return buf.getvalue()


def _webp_bytes(color=(30, 90, 200)):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, format="WEBP")
    return buf.getvalue()


# ---- the roster ------------------------------------------------------------

def test_retired_animation_falls_back_to_classic(tmp_path):
    """The animations the workshop killed. A stored pick of one is somebody's real
    branding.json, so it must degrade -- to classic, silently -- rather than error or
    render nothing. Driven off the retired tuple, never a hand-typed id."""
    assert g.MARK_ANIMS_RETIRED                        # the roster really retired some
    assert not (set(g.MARK_ANIMS_RETIRED) & set(g.MARK_ANIMS))
    for dead in g.MARK_ANIMS_RETIRED:
        g._branding_path(tmp_path).write_text(
            json.dumps({"mark": "logo", "anim": dead}), encoding="utf-8")
        assert g.load_branding(tmp_path)["anim"] == "classic", dead
        assert g.brand_context(tmp_path)["mark_anim"] == "classic", dead


def test_picker_offers_exactly_the_live_roster(tmp_path):
    """What the Control Panel may offer IS MARK_ANIMS -- from both the standalone route
    and the panel summary, which have to agree or the two surfaces disagree about what
    counts as a valid pick."""
    cli = _client(tmp_path)
    assert cli.get("/api/branding").get_json()["anims"] == g.MARK_ANIMS
    summary = cli.get("/api/panel/summary").get_json()
    assert summary["branding"]["anims"] == g.MARK_ANIMS
    for dead in g.MARK_ANIMS_RETIRED:                  # and never a retired one
        assert dead not in summary["branding"]["anims"]
        assert cli.post("/api/branding", json={"anim": dead}).status_code == 400
    for live in g.MARK_ANIMS:                          # every offered id is acceptable
        assert cli.post("/api/branding", json={"anim": live}).status_code == 200


# ---- the four settings -----------------------------------------------------

def test_animation_tuning_round_trips_and_clamps(tmp_path):
    """They persist, they come back on every read, and the SERVER decides the bounds --
    a slider is a suggestion."""
    cli = _client(tmp_path)
    d = cli.get("/api/branding").get_json()
    assert (d["anim_speed"], d["anim_scale"], d["glow_angle"]) == (1.0, 1.0, 0.0)
    assert d["glow_color"] == "#94e2d5"

    saved = cli.post("/api/branding", json={"anim_speed": 0.8, "anim_scale": 1.4,
                                            "glow_color": "#ffAA00",
                                            "glow_angle": 90}).get_json()
    assert (saved["anim_speed"], saved["anim_scale"]) == (0.8, 1.4)
    assert saved["glow_color"] == "#ffAA00" and saved["glow_angle"] == 90.0
    assert g.load_branding(tmp_path)["anim_speed"] == 0.8      # persisted, not just echoed
    assert cli.get("/api/branding").get_json()["anim_scale"] == 1.4

    # Out of range CLAMPS rather than refuses: dragging past the end should land on the
    # honest ceiling, not raise an error toast.
    for key, sent in (("anim_speed", 99), ("anim_scale", 0), ("glow_angle", -40)):
        lo, hi = g._BRAND_NUM_RANGES[key]
        got = cli.post("/api/branding", json={key: sent}).get_json()[key]
        assert got in (lo, hi), key

    # A colour that is not a colour IS refused -- this string reaches a stylesheet.
    assert cli.post("/api/branding", json={"glow_color": "red; --x:y"}).status_code == 400
    assert g.load_branding(tmp_path)["glow_color"] == "#ffAA00"   # refusal changed nothing


def test_tuning_reaches_the_page_boot_payload(tmp_path):
    """The header can only wear a setting that rides MG_BOOT. Both mark-rendering
    shells are checked: the login page and the gallery."""
    cli = _client(tmp_path)
    cli.post("/api/branding", json={"anim_speed": 2.0, "glow_color": "#123456"})
    for path in ("/login", "/next"):
        html = cli.get(path).get_data(as_text=True)
        assert '"anim_speed": 2.0' in html or '"anim_speed":2.0' in html, path
        assert "#123456" in html, path


def test_corrupt_tuning_values_degrade_to_defaults(tmp_path):
    """A hand-edited branding.json must never be the reason a page fails to render."""
    g._branding_path(tmp_path).write_text(json.dumps(
        {"mark": "logo", "anim": "glow", "anim_speed": "fast", "anim_scale": None,
         "glow_color": "not-a-colour", "glow_angle": []}), encoding="utf-8")
    cfg = g.load_branding(tmp_path)
    assert (cfg["anim_speed"], cfg["anim_scale"], cfg["glow_angle"]) == (1.0, 1.0, 0.0)
    assert cfg["glow_color"] == "#94e2d5"


def test_saved_branding_file_only_ever_holds_acceptable_values(tmp_path):
    """save_branding clamps on the way out as well as in, so the file itself can never
    hold a value the app would refuse."""
    g.save_branding(tmp_path, dict(g._BRAND_DEFAULTS, mark="logo", anim="glow",
                                   anim_speed=50, anim_scale=-3, glow_color="nope",
                                   glow_angle=999))
    raw = json.loads(g._branding_path(tmp_path).read_text(encoding="utf-8"))
    assert raw["anim_speed"] == g._BRAND_NUM_RANGES["anim_speed"][1]
    assert raw["anim_scale"] == g._BRAND_NUM_RANGES["anim_scale"][0]
    assert raw["glow_angle"] == g._BRAND_NUM_RANGES["glow_angle"][1]
    assert raw["glow_color"] == "#94e2d5"


# ---- the animated-webp lane ------------------------------------------------

def test_webp_marks_are_enumerated_and_served(tmp_path):
    """An animated webp plays natively in an <img>, so the pipeline's only job is to
    carry the file rather than insist on .png."""
    mdir = g._role_dir("marks")
    mdir.mkdir(parents=True)
    (mdir / "mark_png.png").write_bytes(_png_bytes())
    (mdir / "mark_webp.webp").write_bytes(_webp_bytes())
    (mdir / "marks.json").write_text(json.dumps({"marks": [
        {"id": "mark_png", "label": "png one", "kind": "tile"},
        {"id": "mark_webp", "label": "webp one", "kind": "tile"}]}), encoding="utf-8")
    by_id = {m["id"]: m for m in g.list_marks(tmp_path)}
    assert set(by_id) == {"mark_png", "mark_webp"}
    assert by_id["mark_webp"]["png"] == "/branding/marks/mark_webp.webp"
    assert by_id["mark_webp"]["animated"] is True and by_id["mark_png"]["animated"] is False
    assert g.mark_art_ext("mark_webp") == ".webp" and g.mark_art_ext("nope") == ""
    # the URL the payload advertises actually serves
    cli = _client(tmp_path)
    r = cli.get("/branding/marks/mark_webp.webp")
    assert r.status_code == 200 and r.data == (mdir / "mark_webp.webp").read_bytes()


def test_dropped_webp_mark_is_adopted_byte_for_byte(tmp_path):
    """The point of the lane: re-encoding through Pillow keeps frame one and throws the
    animation away, so a dropped webp's bytes have to survive the trip untouched."""
    mdir = g._role_dir("marks")
    mdir.mkdir(parents=True)
    raw = _webp_bytes()
    (mdir / "grok-mark.webp").write_bytes(raw)
    assert g.sweep_branding_drops(tmp_path) is True
    assert (mdir / "grok-mark.webp").read_bytes() == raw
    by_id = {m["id"]: m for m in g.list_marks(tmp_path)}
    assert by_id["grok-mark"]["png"].endswith(".webp")
    assert g.load_branding(tmp_path)["mark"] == "grok-mark"      # and it becomes active


def test_a_renamed_non_image_is_still_refused(tmp_path):
    """Verbatim adoption is not unchecked adoption."""
    mdir = g._role_dir("marks")
    mdir.mkdir(parents=True)
    (mdir / "fake.webp").write_bytes(b"this is not an image")
    g.sweep_branding_drops(tmp_path)
    assert "fake" not in {m["id"] for m in g.list_marks(tmp_path)}
    assert not g._is_readable_image(mdir / "fake.webp")


def test_custom_webp_upload_and_removal(tmp_path):
    mark = g.add_custom_mark(tmp_path, _webp_bytes(), label="Grok mark", ext=".webp")
    assert mark["png"].endswith(".webp") and mark["animated"] is True
    assert (g._role_dir("marks") / (mark["id"] + ".webp")).is_file()
    assert g.remove_custom_mark(tmp_path, mark["id"]) is True
    assert not (g._role_dir("marks") / (mark["id"] + ".webp")).exists()
    assert g.list_marks(tmp_path) == []


def test_png_stays_the_default_shape(tmp_path):
    """The webp lane is additive: a plain png mark is untouched by any of it."""
    mark = g.add_custom_mark(tmp_path, _png_bytes())
    assert mark["png"].endswith(".png") and mark["animated"] is False
    assert g.mark_art_ext(mark["id"]) == ".png"
