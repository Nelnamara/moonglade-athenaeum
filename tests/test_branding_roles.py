"""The Branding tab's named roles (Session X, Branding Roles Handoff; hidden, unlock-gated).

Four role slots join the three banners in BRANDING_SLOTS -- the login companion, the job
tracker's mascots, the reward icons and the power poses -- each with its own image keys.
An override is one file written where the app's own art is looked for first (the coded tree,
loose-then-container), so every screen that already shows the art wears it with no change of
its own; the pack's default is the container's copy and is never touched.

What these tests hold:
  * the table: exactly four role slots, their image keys, and the public names they own;
  * the spec is checked on the SERVER (format, transparency, aspect, minimum size), whatever the
    client said, and a refusal names the rule and the measured value and writes nothing;
  * the upload route stays one readable function, from disk or from the library;
  * restore removes only the install's file and never the pack's;
  * fail-soft: an override that will not decode is served as the pack's default, silently, and
    the payload says so;
  * the banners are untouched: their payload, routes and render passes see only their own slots.
All hermetic: conftest points branding_root() at tmp_path."""
import io
import json

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


def test_the_specs_are_the_ones_drawn():
    spec = lambda s: g.ROLE_SLOTS[s]["spec"]
    assert spec("login_companion") == {"formats": ["WEBP", "PNG"], "transparent": True,
                                       "aspect": [3, 4], "min_axis": "height", "min_px": 600}
    assert spec("tracker_mascots") == {"formats": ["PNG"], "transparent": True, "aspect": [1, 1],
                                       "min_axis": "side", "min_px": 128}
    assert spec("reward_icons") == {"formats": ["PNG"], "transparent": True, "aspect": [1, 1],
                                    "min_axis": "side", "min_px": 64}
    assert spec("power_poses") == {"formats": ["PNG"], "transparent": True, "aspect": [1, 1],
                                   "min_axis": "side", "min_px": 256}


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
    data = _img((600, 800))
    assert _post(cli, "login_companion", "companion", data, "me.png").status_code == 200
    path = _override_path("login_companion", "companion")
    assert path.name == "login_nel.webp"
    with Image.open(path) as im:
        assert im.format == "WEBP" and im.size == (600, 800)
        assert im.convert("RGBA").getpixel((2, 400))[3] == 0          # the clear half stayed clear
        assert im.convert("RGBA").getpixel((590, 400))[3] == 255
    r = cli.get("/branding/login_nel.webp")
    assert r.status_code == 200 and r.mimetype == "image/webp"


def test_a_webp_companion_is_accepted_too(tmp_path):
    cli = _client(tmp_path)
    assert _post(cli, "login_companion", "companion", _img((600, 800), fmt="WEBP", lossless=True), "a.webp").status_code == 200


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
    ("the wrong shape", "login_companion", "companion", _img((800, 800)),
     ["aspect"], ["3:4"], ["1:1"],
     "Refused: the Login companion must be 3:4. This one is 1:1. Your current art is unchanged."),
    ("too small", "reward_icons", "claim", _img((48, 48)),
     ["size"], ["at least 64 px"], ["48 px"],
     "Refused: the Reward icons must be at least 64 px. This one is 48 px. Your current art is unchanged."),
    ("too short", "login_companion", "companion", _img((450, 600)),
     ["size"], ["at least 600 px tall"], ["600 px tall"], None),
    ("two things wrong", "tracker_mascots", "done", _img((96, 64)),
     ["aspect", "size"], ["square", "at least 128 px"], ["3:2", "64 px"],
     "Refused: the Job tracker mascots must be square (this one is 3:2) and at least 128 px "
     "(this one is 64 px). Your current art is unchanged."),
]


@pytest.mark.parametrize("name,slot,key,data,rules,needs,gots,sentence", REFUSALS, ids=[r[0] for r in REFUSALS])
def test_a_file_that_breaks_the_spec_is_refused_naming_the_rule_and_writes_nothing(
        tmp_path, name, slot, key, data, rules, needs, gots, sentence):
    if name == "too short":
        # 450x600 meets 3:4 and is exactly 600 tall: it PASSES; 450x598 is 2 px short of 600
        data = _img((449, 598))
        rules, needs, gots = ["size"], ["at least 600 px tall"], ["598 px tall"]
        sentence = ("Refused: the Login companion must be at least 600 px tall. This one is 598 px tall. "
                    "Your current art is unchanged.")
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
    """Exactly the minimum, and an aspect a pixel off, are accepted; 3:4 within 2 %."""
    cli = _client(tmp_path)
    assert _post(cli, "reward_icons", "gift", _img((64, 64))).status_code == 200
    assert _post(cli, "tracker_mascots", "spinner", _img((566, 560))).status_code == 200     # the owner's spinner
    assert _post(cli, "login_companion", "companion", _img((450, 600))).status_code == 200


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
    assert _post(cli, "tracker_mascots", "failed", _img((256, 256))).status_code == 200
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
    assert _post(cli, "tracker_mascots", "empty", _img((256, 256))).status_code == 200
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
