"""The Branding tab's named roles (Session X, Branding Roles Handoff; hidden, unlock-gated).

Four role slots join the three banners in BRANDING_SLOTS -- the login companion, the job
tracker's mascots, the reward icons and the power poses -- each with its own image keys.
An override is one file written where the app's own art is looked for first (the coded tree,
loose-then-container), so every screen that already shows the art wears it with no change of
its own; the pack's default is the container's copy and is never touched.

What these tests hold:
  * the table: exactly four role slots, their image keys, and the public names they own;
  * the spec is checked on the SERVER (format, transparency, animation, aspect, minimum size), whatever the
    client said, and a refusal names the rule and the measured value and writes nothing;
  * the upload route stays one readable function, from disk or from the library;
  * restore removes only the install's file and never the pack's;
  * fail-soft: an override that will not decode is served as the pack's default, silently, and
    the payload says so;
  * the banners are untouched: their payload, routes and render passes see only their own slots.
All hermetic: conftest points branding_root() at tmp_path."""
import io
import json
from pathlib import Path

import pytest
from PIL import Image

import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import clear_sealed_caches, login_test_client, session_csrf

ROLE_ORDER = ["login_companion", "tracker_mascots", "reward_icons", "power_poses"]
KEYS = {
    "login_companion": ["companion"],
    "tracker_mascots": ["spinner", "done", "failed", "empty"],
    "reward_icons": ["claim", "gift"],
    "power_poses": ["restart", "shutdown"],
}
PUBLIC = {
    ("login_companion", "companion"): "login_nel.webp",
    ("tracker_mascots", "spinner"): "nel_spinner.png",
    ("tracker_mascots", "done"): "mascots/trk_done.png",
    ("tracker_mascots", "failed"): "mascots/trk_fail.png",
    ("tracker_mascots", "empty"): "mascots/trk_empty.png",
    ("reward_icons", "claim"): "rewards/claim.png",
    ("reward_icons", "gift"): "rewards/gift.png",
    ("power_poses", "restart"): "mascots/nel_restart.png",
    ("power_poses", "shutdown"): "mascots/nel_shutdown.png",
}


def _client(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "1", "filename": "a.png",
                                           "created_at": "2025-01-01T00:00:00"}])
    return login_test_client(create_app(tmp_path))


def _img(size=(256, 256), mode="RGBA", fmt="PNG", see_through=True, color=(120, 80, 200), **save):
    """An image's bytes. RGBA with its left half clear unless see_through is False."""
    im = Image.new(mode, size, color + ((255,) if mode == "RGBA" else ()))
    if mode == "RGBA" and see_through:
        for x in range(size[0] // 2):
            for y in range(0, size[1], 1):
                im.putpixel((x, y), (0, 0, 0, 0))
    buf = io.BytesIO()
    im.save(buf, format=fmt, **save)
    return buf.getvalue()


def _fit(slot, key, h=256):
    """A size with the shape of that image's pack default (so it clears the shape rule): `h` tall."""
    d = g.ROLE_SLOTS[slot]["images"][key]["default"]
    return (round(h * d["w"] / d["h"]), h)


def _disc(size, color):
    """A filled disc on a clear ground: a mascot-shaped picture that stays transparent when animated (a
    frame that is one opaque block on a clear half is cropped by the WebP animation encoder, which can
    drop the file's alpha flag)."""
    from PIL import ImageDraw
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((size[0] * .1, size[1] * .1, size[0] * .9, size[1] * .9), fill=color + (255,))
    return im


def _anim_webp(size=(500, 490), frames=3, junk=b""):
    """A small animated WebP (RGBA discs on a clear ground), the shape the login companion may be."""
    base = [_disc(size, (60 * i + 40, 80, 200)) for i in range(frames)]
    buf = io.BytesIO()
    base[0].save(buf, format="WEBP", save_all=True, append_images=base[1:], duration=80, loop=0, lossless=True)
    return buf.getvalue() + junk


def _anim_bytes(fmt, size=(300, 300), frames=3):
    buf = io.BytesIO()
    base = [_disc(size, (40 * i + 20, 90, 200)) for i in range(frames)]
    extra = dict(lossless=True) if fmt == "WEBP" else {}
    base[0].save(buf, format=fmt, save_all=True, append_images=base[1:], duration=80, loop=0, **extra)
    return buf.getvalue()


def _post(cli, slot, key, data, name="x.png"):
    return cli.post("/api/branding/role", content_type="multipart/form-data", data={
        "csrf": session_csrf(cli), "slot": slot, "key": key, "file": (io.BytesIO(data), name)})


def _override_path(slot, key):
    return g.branding_root() / g._public_rel_to_coded(PUBLIC[(slot, key)])


def _pack(assets):
    """A container beside branding_root() carrying `assets` ({coded rel: bytes}) -- the pack."""
    g.moonglade_container.write_container(g._container_path(), assets)
    clear_sealed_caches()


def _role(cli, slot):
    d = cli.get("/api/branding").get_json()
    return next(r for r in d["roles"] if r["slot"] == slot)


# ---- the table ---------------------------------------------------------------------------

def test_branding_slots_are_the_banners_plus_exactly_the_four_roles():
    assert g.BRANDING_SLOTS == ("banner_main", "banner_login", "banner_loom") + tuple(ROLE_ORDER)
    assert g.BANNER_SLOTS == ("banner_main", "banner_login", "banner_loom")
    assert list(g.ROLE_SLOTS) == ROLE_ORDER
    for slot in ROLE_ORDER:
        assert list(g.ROLE_SLOTS[slot]["images"]) == KEYS[slot], slot


def test_each_image_owns_the_public_name_the_app_already_asks_for():
    for (slot, key), public in PUBLIC.items():
        assert g.ROLE_SLOTS[slot]["images"][key]["public"] == public, (slot, key)


def test_every_role_image_is_open_chrome_never_sealed_art():
    """A role may only name art the seal serves to anyone: system chrome, the mascots/ poses and the
    two reward icons the claim UI fetches. A name the seal denies or gates cannot be a role."""
    for public in PUBLIC.values():
        mode, _ = g._seal_rule(g._public_rel_to_coded(public))
        assert mode == "open", public


def test_each_roles_base_rules_and_each_images_effective_rule():
    """The drawn minimums and formats are the role's; the SHAPE and (where the pack's own art is
    smaller) the minimum size are each image's, taken from the pack default it replaces."""
    base = lambda s: g.ROLE_SLOTS[s]["spec"]
    assert base("login_companion") == {"formats": ["WEBP", "PNG"], "transparent": True,
                                       "animated_formats": ["WEBP"], "min_axis": "height", "min_px": 600}
    assert base("tracker_mascots") == {"formats": ["PNG"], "transparent": True, "animated_formats": [],
                                       "min_axis": "side", "min_px": 128}
    assert base("reward_icons") == {"formats": ["PNG"], "transparent": True, "animated_formats": [],
                                    "min_axis": "side", "min_px": 64}
    assert base("power_poses") == {"formats": ["PNG"], "transparent": True, "animated_formats": [],
                                   "min_axis": "side", "min_px": 256}
    eff = g.role_image_spec
    # the login default is 488 x 480 and animated: shape within 8 % of it, and the drawn 600 px
    # minimum gives way to the default's own 480
    assert eff("login_companion", "companion") == {
        "formats": ["WEBP", "PNG"], "transparent": True, "animated_formats": ["WEBP"],
        "aspect": [488, 480], "aspect_tolerance": 0.08, "min_axis": "height", "min_px": 480}
    shapes = {("tracker_mascots", "spinner"): [566, 560], ("tracker_mascots", "done"): [329, 364],
              ("tracker_mascots", "failed"): [324, 365], ("tracker_mascots", "empty"): [402, 356],
              ("reward_icons", "claim"): [128, 128], ("reward_icons", "gift"): [128, 119],
              ("power_poses", "restart"): [406, 401], ("power_poses", "shutdown"): [401, 398]}
    for (slot, key), aspect in shapes.items():
        e = eff(slot, key)
        assert e["aspect"] == aspect and e["aspect_tolerance"] == 0.08, (slot, key)
        assert e["min_px"] == base(slot)["min_px"], "the pack default is bigger than the drawn minimum"
        assert e["animated_formats"] == [] and e["formats"] == ["PNG"] and e["transparent"] is True


def test_the_payload_carries_each_images_effective_spec(tmp_path):
    cli = _client(tmp_path)
    for role in cli.get("/api/branding").get_json()["roles"]:
        for img in role["images"]:
            want = dict(g.role_image_spec(role["slot"], img["key"]),
                        see_through_min=g.ROLE_SEE_THROUGH_MIN)
            assert img["spec"] == want, (role["slot"], img["key"])


def test_the_roles_payload_is_in_meeting_order_with_no_override_on_a_fresh_install(tmp_path):
    cli = _client(tmp_path)
    roles = cli.get("/api/branding").get_json()["roles"]
    assert [r["slot"] for r in roles] == ROLE_ORDER
    assert [r["name"] for r in roles] == ["Login companion", "Job tracker mascots", "Reward icons",
                                          "Power poses"]
    for r in roles:
        assert [i["key"] for i in r["images"]] == KEYS[r["slot"]]
        for i in r["images"]:
            assert i["url"] == "/branding/" + PUBLIC[(r["slot"], i["key"])]
            assert i["yours"] is False and i["unreadable"] is False
    # the Control Panel reads its branding from the summary route too
    summary = cli.get("/api/panel/summary").get_json()["branding"]
    assert [r["slot"] for r in summary["roles"]] == ROLE_ORDER


def test_the_banner_payload_and_routes_are_unchanged(tmp_path):
    cli = _client(tmp_path)
    d = cli.get("/api/branding").get_json()
    assert set(d["slots"]) == {"banner_main", "banner_login", "banner_loom"}
    for slot in ROLE_ORDER:
        assert cli.post("/api/branding/slot/crop", json={"slot": slot, "id": "x", "zoom": 120}).status_code == 400
        assert cli.post("/api/branding/slot/active", json={"slot": slot, "id": "x"}).status_code == 400
    assert g.list_slot_assets(tmp_path, "power_poses") == []
    assert g.set_slot_active(tmp_path, "power_poses", "x") is False
    # the banner door takes banners only; the role door takes roles only; mascots and rewards
    # themselves are still not slots at either
    for slot in ROLE_ORDER + ["mascots", "rewards", "marks", "system"]:
        r = cli.post("/api/branding/slot", data={"slot": slot, "key": "x"})
        assert r.status_code == 400 and r.get_json()["error"] == "unknown slot", slot
    for slot in ["banner_main", "mascots", "rewards", "marks", "system", ""]:
        r = cli.post("/api/branding/role", data={"csrf": session_csrf(cli), "slot": slot, "key": "x"})
        assert r.status_code == 400 and r.get_json()["error"] == "unknown slot", slot


# ---- the upload --------------------------------------------------------------------------

def test_a_good_file_becomes_the_override_where_the_app_already_looks(tmp_path):
    cli = _client(tmp_path)
    data = _img((300, 300))
    r = _post(cli, "power_poses", "restart", data)
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["slot"] == "power_poses" and d["key"] == "restart"
    path = _override_path("power_poses", "restart")
    assert path.is_file()
    with Image.open(path) as im:
        assert im.format == "PNG" and im.size == (300, 300) and im.mode == "RGBA"
    got = next(i for i in d["role"]["images"] if i["key"] == "restart")
    assert got["yours"] is True and got["unreadable"] is False
    other = next(i for i in d["role"]["images"] if i["key"] == "shutdown")
    assert other["yours"] is False
    # the app's own URL now answers with the override, and the payload (GET) agrees
    served = cli.get("/branding/mascots/nel_restart.png")
    assert served.status_code == 200 and served.data == path.read_bytes()
    assert _role(cli, "power_poses")["images"][0]["yours"] is True


def test_the_upload_is_re_encoded_not_stored_as_sent(tmp_path):
    """A PNG with junk appended after its end still decodes; what lands on disk is Pillow's own
    encoding of the decoded pixels, so nothing the sender tacked on rides into the tree."""
    cli = _client(tmp_path)
    data = _img((256, 256)) + b"<script>alert(1)</script>"
    assert _post(cli, "power_poses", "shutdown", data).status_code == 200
    stored = _override_path("power_poses", "shutdown").read_bytes()
    assert b"<script>" not in stored


def test_the_login_companion_is_stored_as_webp_whatever_format_it_arrived_in(tmp_path):
    """The sign-in page asks for login_nel.webp first; a PNG upload must land under that name as
    a real WebP (alpha kept), or the pack's copy would still win."""
    cli = _client(tmp_path)
    data = _img((600, 590))
    assert _post(cli, "login_companion", "companion", data, "me.png").status_code == 200
    path = _override_path("login_companion", "companion")
    assert path.name == "login_nel.webp"
    with Image.open(path) as im:
        assert im.format == "WEBP" and im.size == (600, 590)
        assert im.convert("RGBA").getpixel((2, 300))[3] == 0          # the clear half stayed clear
        assert im.convert("RGBA").getpixel((590, 300))[3] == 255
    r = cli.get("/branding/login_nel.webp")
    assert r.status_code == 200 and r.mimetype == "image/webp"


def test_a_webp_companion_is_accepted_too(tmp_path):
    cli = _client(tmp_path)
    assert _post(cli, "login_companion", "companion", _img((500, 490), fmt="WEBP", lossless=True), "a.webp").status_code == 200


REFUSALS = [
    # (name, slot, key, bytes, rule, need, got, sentence)
    ("a JPEG for a PNG role", "power_poses", "restart", _img((256, 256), mode="RGB", fmt="JPEG"),
     ["format", "transparent"], ["PNG", "a transparent background"], ["JPEG", "opaque"],
     "Refused: the Power poses must be PNG (this one is JPEG) and have a transparent background "
     "(this one is opaque). Your current art is unchanged."),
    ("a GIF for a PNG role", "power_poses", "restart", _img((256, 256), mode="RGBA", fmt="GIF"),
     ["format"], ["PNG"], ["GIF"],
     "Refused: the Power poses must be PNG. This one is GIF. Your current art is unchanged."),
    ("an opaque PNG", "power_poses", "restart", _img((256, 256), see_through=False),
     ["transparent"], ["a transparent background"], ["opaque"],
     "Refused: the Power poses must have a transparent background. This one is opaque. "
     "Your current art is unchanged."),
    ("the wrong shape", "login_companion", "companion", _img((600, 800)),
     ["aspect"], ["about square"], ["3:4"],
     "Refused: the Login companion must be about square. This one is 3:4. Your current art is unchanged."),
    ("a square for a portrait-shaped default", "tracker_mascots", "done", _img((256, 256)),
     ["aspect"], ["about 9:10"], ["1:1"],
     "Refused: the Job tracker mascots must be about 9:10. This one is 1:1. Your current art is unchanged."),
    ("an animated PNG", "power_poses", "restart", None,
     ["animation"], ["a still picture"], ["animated"],
     "Refused: the Power poses must be a still picture. This one is animated. Your current art is unchanged."),
    ("an animated WebP for a PNG role", "reward_icons", "claim", None,
     ["format", "animation"], ["PNG", "a still picture"], ["WEBP", "animated"],
     "Refused: the Reward icons must be PNG (this one is WEBP) and a still picture (this one is animated). "
     "Your current art is unchanged."),
    ("an animated PNG for the login companion", "login_companion", "companion", None,
     ["animation"], ["a still picture"], ["animated"],
     "Refused: the Login companion must be a still picture. This one is animated. Your current art is unchanged."),
    ("too small", "reward_icons", "claim", _img((48, 48)),
     ["size"], ["at least 64 px"], ["48 px"],
     "Refused: the Reward icons must be at least 64 px. This one is 48 px. Your current art is unchanged."),
    ("too short", "login_companion", "companion", _img((470, 470)),
     ["size"], ["at least 480 px tall"], ["470 px tall"],
     "Refused: the Login companion must be at least 480 px tall. This one is 470 px tall. "
     "Your current art is unchanged."),
    ("two things wrong", "tracker_mascots", "done", _img((96, 64)),
     ["aspect", "size"], ["about 9:10", "at least 128 px"], ["3:2", "64 px"],
     "Refused: the Job tracker mascots must be about 9:10 (this one is 3:2) and at least 128 px "
     "(this one is 64 px). Your current art is unchanged."),
]


@pytest.mark.parametrize("name,slot,key,data,rules,needs,gots,sentence", REFUSALS, ids=[r[0] for r in REFUSALS])
def test_a_file_that_breaks_the_spec_is_refused_naming_the_rule_and_writes_nothing(
        tmp_path, name, slot, key, data, rules, needs, gots, sentence):
    if data is None:                       # the animated ones, built here (a PNG that moves, a WebP that moves)
        data = _anim_bytes("WEBP" if name.startswith("an animated WebP") else "PNG",
                           size=(500, 490) if slot == "login_companion" else (300, 300))
    cli = _client(tmp_path)
    r = _post(cli, slot, key, data)
    assert r.status_code == 400, name
    d = r.get_json()
    assert [f["rule"] for f in d["failed"]] == rules
    assert [f["need"] for f in d["failed"]] == needs
    assert [f["got"] for f in d["failed"]] == gots
    assert d["error"] == sentence
    assert not _override_path(slot, key).exists(), "a refused file is never written"
    assert not list((g.branding_root()).rglob("*.tmp")), "no half-written file is left behind"


def test_the_boundaries_pass(tmp_path):
    """Exactly the minimum, and a shape within 8 % of the pack default's, are accepted; past 8 % is not."""
    cli = _client(tmp_path)
    assert _post(cli, "reward_icons", "gift", _img((64, 64))).status_code == 200            # 64 px, 7 % off 128 x 119
    assert _post(cli, "tracker_mascots", "spinner", _img((566, 560))).status_code == 200     # the owner's spinner
    assert _post(cli, "login_companion", "companion", _img((480, 480))).status_code == 200   # exactly 480 tall
    assert _post(cli, "login_companion", "companion", _img((488, 480))).status_code == 200   # the pack's own size
    # power_poses/restart is 406 x 401 (1.0125): 7.6 % wider is in, 8.8 % wider is out
    assert _post(cli, "power_poses", "restart", _img((279, 256))).status_code == 200
    r = _post(cli, "power_poses", "restart", _img((282, 256)))
    assert r.status_code == 400 and r.get_json()["failed"][0]["rule"] == "aspect"


def test_the_wording_of_a_non_simple_ratio_is_a_decimal(tmp_path):
    cli = _client(tmp_path)
    d = _post(cli, "power_poses", "restart", _img((1007, 600))).get_json()
    assert d["failed"][0]["got"] == "1.68:1"


def test_an_oversized_image_is_refused_before_it_is_decoded(tmp_path):
    cli = _client(tmp_path)
    r = _post(cli, "power_poses", "restart", _img((4400, 300)))
    assert r.status_code == 400
    assert "larger than" in r.get_json()["error"] and "4,096" in r.get_json()["error"]
    assert not _override_path("power_poses", "restart").exists()


def test_an_oversized_file_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "ROLE_MAX_BYTES", 2000)
    cli = _client(tmp_path)
    r = _post(cli, "power_poses", "restart", _img((256, 256), see_through=True) + b"\0" * 5000)
    assert r.status_code == 400 and "too large" in r.get_json()["error"].lower()


def test_a_request_body_far_over_the_limit_is_refused_before_it_is_read(tmp_path, monkeypatch):
    """The route caps the whole request, not just the file it reads afterwards: a body this big
    never reaches the form parser (a 413), so a huge upload cannot be spooled to disk first."""
    monkeypatch.setattr(g, "ROLE_MAX_BYTES", 2000)
    cli = _client(tmp_path)
    r = cli.post("/api/branding/role", content_type="multipart/form-data", data={
        "csrf": session_csrf(cli), "slot": "power_poses", "key": "restart",
        "file": (io.BytesIO(b"\0" * 200_000), "x.png")})
    assert r.status_code == 413
    assert not _override_path("power_poses", "restart").exists()


def test_the_bad_requests(tmp_path):
    cli = _client(tmp_path)
    ok = _img((256, 256))
    assert _post(cli, "power_poses", "", ok).get_json()["error"] == "unknown image"
    assert _post(cli, "power_poses", "claim", ok).get_json()["error"] == "unknown image"
    assert _post(cli, "nope", "restart", ok).get_json()["error"] == "unknown slot"
    r = cli.post("/api/branding/role", data={"csrf": session_csrf(cli), "slot": "power_poses", "key": "restart"},
                 content_type="multipart/form-data")
    assert r.status_code == 400 and r.get_json()["error"] == "no file"
    r = _post(cli, "power_poses", "restart", b"not an image")
    assert r.status_code == 400 and r.get_json()["error"] == "not a readable image"
    assert not _override_path("power_poses", "restart").exists()


def test_the_upload_needs_a_session(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "1", "filename": "a.png", "created_at": "2025-01-01T00:00:00"}])
    anon = create_app(tmp_path).test_client()
    r = anon.post("/api/branding/role", data={"slot": "power_poses", "key": "restart",
                  "file": (io.BytesIO(_img()), "x.png")}, content_type="multipart/form-data")
    assert r.status_code in (401, 302, 403)
    assert not _override_path("power_poses", "restart").exists()
    assert anon.post("/api/branding/role/restore", json={"slot": "power_poses", "key": "restart"}).status_code in (401, 302, 403)


def test_the_role_routes_refuse_a_post_without_the_sessions_token(tmp_path):
    cli = _client(tmp_path)
    r = cli.post("/api/branding/role", content_type="multipart/form-data", data={
        "slot": "power_poses", "key": "restart", "file": (io.BytesIO(_img()), "x.png")})
    assert r.status_code == 400 and "session expired" in r.get_json()["error"].lower()
    assert not _override_path("power_poses", "restart").exists()
    assert _post(cli, "power_poses", "restart", _img()).status_code == 200
    r = cli.post("/api/branding/role/restore", json={"slot": "power_poses", "key": "restart"})
    assert r.status_code == 400 and "session expired" in r.get_json()["error"].lower()
    assert _override_path("power_poses", "restart").exists(), "no token, nothing removed"
    r = cli.post("/api/branding/role/restore", json={"csrf": "wrong", "slot": "power_poses", "key": "restart"})
    assert r.status_code == 400 and _override_path("power_poses", "restart").exists()


def test_a_library_picture_can_be_the_source_and_meets_the_same_spec(tmp_path):
    """'From the gallery': a media id resolves to the library's own file, and the same checks apply."""
    (tmp_path / "a_1.png").write_bytes(_img((256, 256)))
    (tmp_path / "b_2.jpg").write_bytes(_img((256, 256), mode="RGB", fmt="JPEG"))
    save_catalog(tmp_path / "catalog.db", [
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "1", "filename": "a_1.png", "created_at": "2025-01-01T00:00:00"},
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "2", "filename": "b_2.jpg", "created_at": "2025-01-01T00:00:00"}])
    cli = login_test_client(create_app(tmp_path))
    r = cli.post("/api/branding/role", data={"csrf": session_csrf(cli), "slot": "power_poses", "key": "shutdown", "media_id": "1"})
    assert r.status_code == 200, r.get_json()
    assert _override_path("power_poses", "shutdown").is_file()
    r = cli.post("/api/branding/role", data={"csrf": session_csrf(cli), "slot": "power_poses", "key": "restart", "media_id": "2"})
    assert r.status_code == 400 and r.get_json()["failed"][0]["rule"] == "format"
    assert not _override_path("power_poses", "restart").exists()


def test_a_check_only_post_measures_a_library_picture_and_writes_nothing(tmp_path):
    """The phone and the desktop tick a library picture's rules before 'Use this'. The picture is
    already on this machine, so it is measured here: the same facts the client's rules read, and
    not a byte written."""
    (tmp_path / "a_1.png").write_bytes(_img((300, 200)))
    (tmp_path / "b_2.jpg").write_bytes(_img((256, 256), mode="RGB", fmt="JPEG"))
    save_catalog(tmp_path / "catalog.db", [
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "1", "filename": "a_1.png", "created_at": "2025-01-01T00:00:00"},
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "2", "filename": "b_2.jpg", "created_at": "2025-01-01T00:00:00"}])
    cli = login_test_client(create_app(tmp_path))

    def check(mid, slot="power_poses", key="restart"):
        return cli.post("/api/branding/role", data={"csrf": session_csrf(cli), "slot": slot, "key": key,
                                                    "media_id": mid, "check": "1"})
    r = check("1")
    assert r.status_code == 200
    f = r.get_json()["facts"]
    assert (f["format"], f["w"], f["h"]) == ("PNG", 300, 200) and 0.45 < f["see_through"] < 0.55
    assert f["animated"] is False
    r = check("2")
    assert r.status_code == 200 and r.get_json()["facts"]["format"] == "JPEG"
    assert r.get_json()["facts"]["see_through"] == 0
    assert check("3").status_code == 400                                   # not in the library
    assert check("1", key="nope").get_json()["error"] == "unknown image"
    assert not _override_path("power_poses", "restart").exists()
    assert {p.name for p in g.branding_root().rglob("*") if p.is_file()} <= {"README.txt"}, "nothing written"
    # the check needs the token like the write does
    r = cli.post("/api/branding/role", data={"slot": "power_poses", "key": "restart", "media_id": "1", "check": "1"})
    assert r.status_code == 400


def test_an_upload_is_the_apps_own_write_not_a_file_dropped_in_the_tree(tmp_path):
    """The tree scan reads a file the install did not put there as a drop; the app's own write is
    folded into the baseline at once (as every other Branding upload is)."""
    cli = _client(tmp_path)
    assert g._branding_tree_has_new_art(tmp_path) is False         # takes the first snapshot
    assert _post(cli, "reward_icons", "claim", _img((128, 128))).status_code == 200
    assert g._branding_tree_has_new_art(tmp_path) is False


# ---- restore, and the pack ---------------------------------------------------------------

def test_restore_removes_only_the_installs_file_and_the_pack_answers_again(tmp_path):
    cli = _client(tmp_path)
    rel = g._public_rel_to_coded("mascots/nel_restart.png")
    pack_bytes = _img((256, 256), color=(1, 2, 3))
    _pack({rel: pack_bytes})
    pack_file = g._container_path()
    before = pack_file.read_bytes()
    assert cli.get("/branding/mascots/nel_restart.png").data == pack_bytes
    assert _post(cli, "power_poses", "restart", _img((300, 300))).status_code == 200
    assert cli.get("/branding/mascots/nel_restart.png").data != pack_bytes
    r = cli.post("/api/branding/role/restore", json={"csrf": session_csrf(cli), "slot": "power_poses", "key": "restart"})
    assert r.status_code == 200 and r.get_json()["removed"] is True
    assert not _override_path("power_poses", "restart").exists()
    assert cli.get("/branding/mascots/nel_restart.png").data == pack_bytes
    assert pack_file.read_bytes() == before, "the pack is never touched"
    img = next(i for i in r.get_json()["role"]["images"] if i["key"] == "restart")
    assert img["yours"] is False


def test_restore_when_nothing_is_overridden_is_a_quiet_no_op_and_never_the_pack(tmp_path):
    cli = _client(tmp_path)
    rel = g._public_rel_to_coded("rewards/claim.png")
    _pack({rel: _img((128, 128))})
    before = g._container_path().read_bytes()
    r = cli.post("/api/branding/role/restore", json={"csrf": session_csrf(cli), "slot": "reward_icons", "key": "claim"})
    assert r.status_code == 200 and r.get_json()["removed"] is False
    assert g._container_path().read_bytes() == before
    assert cli.post("/api/branding/role/restore", json={"csrf": session_csrf(cli), "slot": "reward_icons", "key": "nope"}).status_code == 400
    assert cli.post("/api/branding/role/restore", json={"csrf": session_csrf(cli), "slot": "banner_main", "key": "x"}).status_code == 400


def test_the_pack_default_is_served_for_the_row_to_show_beside_yours(tmp_path):
    cli = _client(tmp_path)
    rel = g._public_rel_to_coded("rewards/gift.png")
    pack_bytes = _img((128, 119), color=(9, 9, 9))
    _pack({rel: pack_bytes})
    assert _post(cli, "reward_icons", "gift", _img((200, 200))).status_code == 200
    img = next(i for i in _role(cli, "reward_icons")["images"] if i["key"] == "gift")
    assert img["yours"] is True and img["default_url"] == "/api/branding/role/default/reward_icons/gift"
    r = cli.get(img["default_url"])
    assert r.status_code == 200 and r.data == pack_bytes and r.mimetype == "image/png"
    # an image the pack does not carry has no default to show
    other = next(i for i in _role(cli, "reward_icons")["images"] if i["key"] == "claim")
    assert other["default_url"] is None
    assert cli.get("/api/branding/role/default/reward_icons/claim").status_code == 404
    assert cli.get("/api/branding/role/default/banner_main/x").status_code == 404
    assert cli.get("/api/branding/role/default/reward_icons/nope").status_code == 404


# ---- fail-soft ---------------------------------------------------------------------------

def test_an_override_that_will_not_decode_shows_the_packs_default_silently(tmp_path):
    cli = _client(tmp_path)
    rel = g._public_rel_to_coded("mascots/trk_fail.png")
    pack_bytes = _img((256, 256), color=(5, 5, 5))
    _pack({rel: pack_bytes})
    assert _post(cli, "tracker_mascots", "failed", _img(_fit("tracker_mascots", "failed"))).status_code == 200
    path = _override_path("tracker_mascots", "failed")
    path.write_bytes(b"\x89PNG\r\n\x1a\n this is not a picture any more")
    r = cli.get("/branding/mascots/trk_fail.png")
    assert r.status_code == 200 and r.data == pack_bytes, "the app shows the default, no error"
    img = next(i for i in _role(cli, "tracker_mascots")["images"] if i["key"] == "failed")
    assert img["yours"] is True and img["unreadable"] is True
    # mending the file mends it: the answer is not cached past the file's change
    path.write_bytes(_img((256, 256), color=(77, 77, 77)))
    assert cli.get("/branding/mascots/trk_fail.png").data == path.read_bytes()
    assert next(i for i in _role(cli, "tracker_mascots")["images"] if i["key"] == "failed")["unreadable"] is False


def test_an_unreadable_override_with_no_pack_default_is_left_as_it_always_was(tmp_path):
    """The fallback is the pack's default; with none to fall back to there is nothing better to
    serve, so the file is served as before (and the page's own onerror handles a broken image)."""
    cli = _client(tmp_path)
    assert _post(cli, "tracker_mascots", "empty", _img(_fit("tracker_mascots", "empty"))).status_code == 200
    _override_path("tracker_mascots", "empty").write_bytes(b"garbage")
    r = cli.get("/branding/mascots/trk_empty.png")
    assert r.status_code == 200 and r.data == b"garbage"
    img = next(i for i in _role(cli, "tracker_mascots")["images"] if i["key"] == "empty")
    assert img["unreadable"] is True and img["default_url"] is None


def test_a_missing_override_is_just_the_default(tmp_path):
    cli = _client(tmp_path)
    rel = g._public_rel_to_coded("nel_spinner.png")
    pack_bytes = _img((256, 256), color=(8, 8, 8))
    _pack({rel: pack_bytes})
    assert _post(cli, "tracker_mascots", "spinner", _img((256, 256))).status_code == 200
    _override_path("tracker_mascots", "spinner").unlink()
    assert cli.get("/branding/nel_spinner.png").data == pack_bytes
    img = next(i for i in _role(cli, "tracker_mascots")["images"] if i["key"] == "spinner")
    assert img["yours"] is False and img["unreadable"] is False


# ---- an animated login companion, kept animated -------------------------------------------------

def test_an_animated_webp_companion_is_kept_animated_and_stripped_of_what_was_appended(tmp_path):
    """The pack's own login companion is an animated WebP, so the login companion may be one. It is
    validated frame by frame and stored as sent (re-encoding every frame would be slow and could
    not be faster than the sender's own encoder), cut at the end of the RIFF container so nothing
    appended after the picture survives."""
    cli = _client(tmp_path)
    junk = b"<script>alert(1)</script>"
    data = _anim_webp(junk=junk)
    r = _post(cli, "login_companion", "companion", data, "me.webp")
    assert r.status_code == 200, r.get_json()
    stored = _override_path("login_companion", "companion").read_bytes()
    assert junk not in stored and stored == data[:-len(junk)]
    with Image.open(_override_path("login_companion", "companion")) as im:
        assert im.format == "WEBP" and im.is_animated and im.n_frames == 3
    served = cli.get("/branding/login_nel.webp")
    assert served.status_code == 200 and served.mimetype == "image/webp" and served.data == stored


def test_an_animated_webp_that_stops_decoding_part_way_is_refused_and_writes_nothing(tmp_path):
    cli = _client(tmp_path)
    data = _anim_webp(frames=4)
    cut = data[: len(data) * 3 // 4]           # a stream cut off in the later frames
    r = _post(cli, "login_companion", "companion", cut, "cut.webp")
    assert r.status_code == 400
    assert not _override_path("login_companion", "companion").exists()


def test_an_animation_past_the_budget_is_refused_before_its_frames_are_decoded(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "ROLE_MAX_ANIM_PIXELS", 500 * 490 * 2)       # room for two frames of this size
    cli = _client(tmp_path)
    r = _post(cli, "login_companion", "companion", _anim_webp(frames=3), "long.webp")
    assert r.status_code == 400 and "animation" in r.get_json()["error"].lower()
    assert not _override_path("login_companion", "companion").exists()


# ---- the pack's own art is always acceptable -------------------------------------------------------
# The drawn stand-in specs would have refused the pack's own login companion (488 x 480, animated),
# the tracker's done / failed / empty and the gift icon. A role's rules are now each image's own
# pack default (shape within 8 %, the drawn minimum unless the default is smaller, animation where
# the default is animated), so replacing a role with the art it already wears must work. These need
# the pack's art: the private repo's mirror of it, so they carry the donor gate.

_MIRROR = (Path(__file__).resolve().parents[1].parent / "moonglade-internal" / "design"
           / "handoff-2026-09-04" / "assets" / "branding")
_MIRROR_FILE = {
    ("login_companion", "companion"): "login_nel.webp",
    ("tracker_mascots", "spinner"): "system/nel_spinner.png",
    ("tracker_mascots", "done"): "mascots/trk_done.png",
    ("tracker_mascots", "failed"): "mascots/trk_fail.png",
    ("tracker_mascots", "empty"): "mascots/trk_empty.png",
    ("reward_icons", "claim"): "rewards/claim.png",
    ("reward_icons", "gift"): "rewards/gift.png",
    ("power_poses", "restart"): "mascots/nel_restart.png",
    ("power_poses", "shutdown"): "mascots/nel_shutdown.png",
}


@pytest.fixture()
def pack_art(sealed_donor_present):
    """{(slot, key): bytes} of the pack's nine role images, from the private repo's mirror of the pack."""
    missing = [f for f in _MIRROR_FILE.values() if not (_MIRROR / f).is_file()]
    if missing:
        pytest.skip("the pack's art (private repo mirror) is not checked out: %s" % missing[:2])
    return {k: (_MIRROR / f).read_bytes() for k, f in _MIRROR_FILE.items()}


def test_every_pack_default_passes_its_own_roles_check(pack_art):
    for (slot, key), raw in pack_art.items():
        facts, _ = g.role_measure(raw)
        assert g.role_spec_failures(g.role_image_spec(slot, key), facts) == [], (slot, key, facts)
        # ...and the table's idea of the default is the pack's real one, so a repainted default
        # that changes shape fails HERE, by name, until the table is told
        d = g.ROLE_SLOTS[slot]["images"][key]["default"]
        assert (facts["w"], facts["h"], facts["animated"]) == (d["w"], d["h"], d.get("animated", False)), (slot, key)


def test_every_pack_default_can_be_uploaded_as_the_override_of_itself(pack_art, tmp_path):
    cli = _client(tmp_path)
    for (slot, key), raw in pack_art.items():
        r = _post(cli, slot, key, raw, _MIRROR_FILE[(slot, key)].rsplit("/", 1)[-1])
        assert r.status_code == 200, (slot, key, r.get_json())
        assert _override_path(slot, key).is_file()
    with Image.open(_override_path("login_companion", "companion")) as im:
        assert im.format == "WEBP" and im.is_animated, "the login companion stayed animated"
    with Image.open(_override_path("tracker_mascots", "done")) as im:
        assert im.format == "PNG" and im.size == (329, 364)


def test_the_shape_rule_is_not_vacuous_on_the_packs_own_art(pack_art):
    """Stretch each static default 12 % wider and its own role refuses it; a square is refused for the
    tracker's done / failed images, whose defaults are taller than wide."""
    for (slot, key), raw in pack_art.items():
        if key == "companion":
            continue
        with Image.open(io.BytesIO(raw)) as im:
            wide = im.convert("RGBA").resize((round(im.width * 1.12), im.height))
        buf = io.BytesIO()
        wide.save(buf, format="PNG")
        facts, _ = g.role_measure(buf.getvalue())
        rules = [f["rule"] for f in g.role_spec_failures(g.role_image_spec(slot, key), facts)]
        assert rules == ["aspect"], (slot, key, rules)


# ---- a WebP's declared canvas is read from its header, before anything opens it ---------------------
# libwebp commits the whole declared canvas when Pillow OPENS a WebP (a 138-byte file claiming
# 16383 x 16383 took ~2 GB before the size check ran). The header is read first, by hand, and a
# WebP over the limit, or whose header cannot be read, is refused without ever being opened.

def _riff(chunk_fourcc, chunk_payload):
    body = b"WEBP" + chunk_fourcc + len(chunk_payload).to_bytes(4, "little") + chunk_payload
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def _webp_claiming(kind, w, h, pad=0):
    """A WebP header that DECLARES a w x h canvas and holds no picture (the crafted file)."""
    if kind == "VP8X":
        payload = bytes(4) + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    elif kind == "VP8 ":
        payload = bytes([0x10, 0, 0]) + b"\x9d\x01\x2a" + w.to_bytes(2, "little") + h.to_bytes(2, "little")
    else:                                  # VP8L: signature, then width-1 and height-1 in 14 bits each
        payload = b"\x2f" + ((w - 1) | ((h - 1) << 14)).to_bytes(4, "little")
    return _riff(kind.encode("ascii"), payload + bytes(pad))


@pytest.fixture()
def no_open(monkeypatch):
    """Image.open that fails the test if it is reached, and counts the calls."""
    calls = []

    def _open(*a, **k):
        calls.append((a, k))
        raise AssertionError("Image.open was called on a file that should have been refused first")
    monkeypatch.setattr(Image, "open", _open)
    return calls


def test_the_header_reader_gets_the_same_canvas_as_pillow_for_every_webp_encoding():
    for mode, kw, kind in (("RGB", {"lossless": False, "quality": 80}, b"VP8 "), ("RGB", {"lossless": True}, b"VP8L"),
                           ("RGBA", {"lossless": False}, b"VP8X")):
        buf = io.BytesIO()
        Image.new(mode, (321, 123), (9, 8, 7) + ((200,) if mode == "RGBA" else ())).save(buf, "WEBP", **kw)
        raw = buf.getvalue()
        assert raw[12:16] == kind, (mode, raw[12:16])
        assert g.webp_declared_size(raw[:64]) == (321, 123), kind
    assert g.webp_declared_size(_anim_webp((50, 40), frames=2)[:64]) == (50, 40)
    assert g.webp_declared_size(b"\x89PNG\r\n\x1a\n" + bytes(40)) is None, "not a WebP: nothing to say"


@pytest.mark.parametrize("kind", ["VP8X", "VP8 ", "VP8L"])
def test_a_tiny_webp_declaring_a_huge_canvas_is_refused_before_it_is_opened(tmp_path, no_open, kind):
    cli = _client(tmp_path)
    crafted = _webp_claiming(kind, 16383, 16383, pad=100)          # ~140 bytes, claims a ~1 GB canvas
    assert len(crafted) < 200
    r = _post(cli, "login_companion", "companion", crafted, "x.webp")
    assert r.status_code == 400
    assert r.get_json()["error"] == "That picture is larger than 4,096 px on a side."
    assert not _override_path("login_companion", "companion").exists()
    assert no_open == [], "refused from the header alone"
    # the check-only road (a library picture) reads the same header
    (tmp_path / "evil_1.webp").write_bytes(crafted)
    save_catalog(tmp_path / "catalog.db", [
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "1", "filename": "evil_1.webp", "created_at": "2025-01-01T00:00:00"}])
    r = cli.post("/api/branding/role", data={"csrf": session_csrf(cli), "slot": "login_companion",
                                             "key": "companion", "media_id": "1", "check": "1"})
    assert r.status_code == 400 and no_open == []


def test_a_webp_canvas_at_the_limit_is_not_refused_by_the_header_reader():
    g.guard_webp_canvas(_webp_claiming("VP8X", 4096, 4096), 4096)               # exactly the limit: allowed
    with pytest.raises(g.ImageRefused):
        g.guard_webp_canvas(_webp_claiming("VP8X", 4097, 10), 4096)
    with pytest.raises(g.ImageRefused):
        g.guard_webp_canvas(_webp_claiming("VP8X", 10, 4097), 4096)


@pytest.mark.parametrize("header", [
    b"RIFF\x10\x00\x00\x00WEBPVP8X\x0a\x00\x00\x00",                       # a VP8X cut off before its canvas
    b"RIFF\x20\x00\x00\x00WEBPJUNK" + bytes(30),                               # no picture chunk a WebP may start with
    b"RIFF\x20\x00\x00\x00WEBPVP8 " + bytes(30),                               # a lossy header without its start code
    b"RIFF\x20\x00\x00\x00WEBPVP8L" + bytes(30),                               # a lossless header without its signature
], ids=["cut", "junk", "no-start-code", "no-signature"])
def test_a_webp_whose_header_cannot_be_read_is_refused_without_being_opened(tmp_path, no_open, header):
    cli = _client(tmp_path)
    r = _post(cli, "power_poses", "restart", header, "x.webp")
    assert r.status_code == 400 and r.get_json()["error"] == "not a readable image"
    assert no_open == []


def test_the_banner_upload_reads_the_same_header_first(tmp_path, no_open):
    """/api/branding/slot decodes the same way, so it asks the same question first (its own, larger
    limit: banners are wide). Its CSRF debt is the security review's, untouched here."""
    cli = _client(tmp_path)
    r = cli.post("/api/branding/slot", data={"slot": "banner_main",
                 "file": (io.BytesIO(_webp_claiming("VP8X", 16383, 16383, pad=100)), "b.webp")},
                 content_type="multipart/form-data")
    assert r.status_code == 400 and r.get_json()["error"] == "That picture is larger than 8,192 px on a side."
    assert no_open == []
    assert g.list_slot_assets(tmp_path, "banner_main") == []


def test_an_ordinary_banner_webp_still_uploads(tmp_path):
    cli = _client(tmp_path)
    buf = io.BytesIO()
    Image.new("RGB", (600, 150), (30, 20, 90)).save(buf, "WEBP")
    r = cli.post("/api/branding/slot", data={"slot": "banner_main", "file": (io.BytesIO(buf.getvalue()), "b.webp")},
                 content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["item"]["id"]


# ---- only the everyday formats are ever opened -------------------------------------------------------
# Pillow identifies dozens of formats, some with decoders that shell out or are old and sprawling (EPS
# through Ghostscript, TIFF, PSD, ...). The role upload names the four a person might plausibly send
# (PNG and WebP are what a role takes; JPEG and GIF are refused BY NAME in the editor's ticks) and
# opens only those: anything else never reaches a decoder.

@pytest.mark.parametrize("fmt", ["TIFF", "BMP", "EPS", "ICO", "PPM", "PCX"])
def test_a_format_outside_the_allowlist_is_refused_before_a_decoder_runs(tmp_path, monkeypatch, fmt):
    real_open, seen = Image.open, []

    def spy(*a, **k):
        seen.append(k.get("formats"))
        return real_open(*a, **k)
    monkeypatch.setattr(Image, "open", spy)
    from PIL import EpsImagePlugin

    def no_gs(*a, **k):
        raise AssertionError("an EPS reached its decoder (Ghostscript)")
    monkeypatch.setattr(EpsImagePlugin.EpsImageFile, "load", no_gs)
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 100, 50)).save(buf, fmt)
    cli = _client(tmp_path)
    r = _post(cli, "power_poses", "restart", buf.getvalue(), "x.png")
    assert r.status_code == 400 and r.get_json()["error"] == "not a readable image", fmt
    assert seen and all(f and fmt not in f for f in seen), "opened with an allowlist that excludes %s: %r" % (fmt, seen)
    assert not _override_path("power_poses", "restart").exists()


def test_the_allowlist_is_the_four_everyday_formats_and_no_more():
    assert tuple(g.ROLE_OPEN_FORMATS) == ("PNG", "WEBP", "JPEG", "GIF")


def test_the_everyday_formats_still_open_and_a_jpeg_is_refused_by_name(tmp_path):
    cli = _client(tmp_path)
    r = _post(cli, "power_poses", "restart", _img((256, 256), mode="RGB", fmt="JPEG"), "x.jpg")
    assert [f["rule"] for f in r.get_json()["failed"]] == ["format", "transparent"]
    assert r.get_json()["failed"][0]["got"] == "JPEG"
    r = _post(cli, "power_poses", "restart", _img((256, 256), mode="RGBA", fmt="GIF"), "x.gif")
    assert r.get_json()["failed"][0]["got"] == "GIF"
    assert _post(cli, "power_poses", "restart", _img((256, 256)), "x.png").status_code == 200
