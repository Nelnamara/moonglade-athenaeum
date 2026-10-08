"""Serving the bespoke moments (pack v5): the clips' buckets and routing, HTTP Range for
container-sourced assets, and the roster flags /api/achievements adds once a feat is earned.

Hidden-feat ids and the moments' sealed copy never appear here as literals: the ids are
looked up through the roster's `moment` flag and the copy is read from the private donor at
runtime, so this public file is no more of a spoiler than the code it tests. The tests that
need the real roster carry `sealed_donor_present`; the routing, seal and Range mechanics run
everywhere on stubbed lookups and a container built in the test's own tmp dir.

The clip every test serves is dev/tests/fixtures/moment_fixture.mp4 (tiny, public, colour bars),
which conftest seeds into the pinned test container under each moment clip's key."""
import io
import json
from pathlib import Path

import pytest

from moonglade import container as mc
from moonglade import gallery as g
from moonglade.gallery import CATALOG_FIELDS, save_catalog

from tests.conftest import (STARFALL_EVENT, _SEALED_DONOR, MOMENT_FIXTURE_CLIP, ach_event, clear_sealed_caches,
                            first_party_sources, login_client, moment_clip_keys)

_REPO = Path(__file__).resolve().parents[2]
_KEYTURN_URL = "/branding/" + g._MOMENT_CLIPS["keyturn"]
_STARFALL_URL = "/branding/" + g._MOMENT_CLIPS["starfall"]
_COPY_KEYS = {"starfall": {"line"},
              "keyturn": {"title1", "line1", "title2", "line2", "button", "caption"}}


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _client(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    return login_client(tmp_path)


def _png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _donor_roster():
    return json.loads(_SEALED_DONOR.read_text(encoding="utf-8"))["roster"]


def _write_box(tmp_path, assets):
    """Replace this test's container with one carrying only `assets` (no roster), then
    drop every cache that remembers the old one."""
    mc.write_container(g._container_path(), assets, {})
    clear_sealed_caches()


def _earn_keyturn(cli):
    """The REAL road to the keyturn feat: a file dropped into a banner slot, adopted by
    the sweep the next /api/achievements read runs."""
    (g._role_dir("banner_login") / "my_art.png").write_bytes(_png_bytes())
    cli.get("/api/achievements")


# ---- routing: neutral URLs, their own buckets --------------------------------

def test_each_moment_clip_routes_to_its_own_bucket():
    """The keyturn clip has a rule of its own AHEAD of the bare ee_* rule, so it lands in
    its own bucket; the starfall clip rides the bare rule into starfall's."""
    assert (g._public_rel_to_coded(g._MOMENT_CLIPS["keyturn"])
            == g._role_rel("keyturn", g._MOMENT_CLIPS["keyturn"]))
    assert (g._public_rel_to_coded(g._MOMENT_CLIPS["starfall"])
            == g._role_rel("starfall", g._MOMENT_CLIPS["starfall"]))
    # every other bare ee_* still goes to starfall, as before
    assert g._public_rel_to_coded("ee_nelstarfall.png") == g._role_rel("starfall", "ee_nelstarfall.png")


def test_keyturn_bucket_does_not_nest_under_any_other_role():
    """A prefix-judged seal means a folder nested in another role's folder inherits that
    role's gate. The keyturn bucket must sit beside starfall's, never inside it (or any
    other), and nothing may sit inside it."""
    code = g.ROLE_CODE["keyturn"].lower()
    for role, other in g.ROLE_CODE.items():
        if role == "keyturn":
            continue
        other = other.lower()
        assert not code.startswith(other + "/"), role
        assert not other.startswith(code + "/"), role


def test_clip_urls_are_neutral():
    """The URL shows in the network tab: it may name the moment, never the feat."""
    for name in g._MOMENT_CLIPS.values():
        low = name.lower()
        assert "uth" not in low and "hood" not in low and "konami" not in low, name


def test_clip_urls_name_no_roster_feat(sealed_donor_present):
    """Donor-backed half of the check above: no roster feat's id or name (in any of the
    spellings a filename would use) appears in a clip's public name."""
    for a in _donor_roster():
        forms = {a["id"], a["id"].replace("-", "_"), a["id"].replace("-", ""),
                 a["name"].lower().replace(" ", "_"), a["name"].lower().replace(" ", "")}
        for name in g._MOMENT_CLIPS.values():
            for f in forms:
                if len(f) >= 4:
                    assert f.lower() not in name.lower(), "a clip URL names a feat"


# ---- the seal resolves by the `moment` flag, and fails closed without it -------

def test_moment_buckets_are_gated_on_the_flagged_feat(monkeypatch):
    monkeypatch.setattr(g, "_moment_ach", lambda: {"starfall": "feat-a", "keyturn": "feat-b"})
    rr = g._role_rel
    assert g._seal_rule(rr("starfall", "ee_nelstarfall.png")) == ("earned", "feat-a")
    assert g._seal_rule(rr("starfall", g._MOMENT_CLIPS["starfall"])) == ("earned", "feat-a")
    assert g._seal_rule(rr("breadcrumb", "README.txt")) == ("earned", "feat-a")
    assert g._seal_rule(rr("keyturn", g._MOMENT_CLIPS["keyturn"])) == ("earned", "feat-b")
    # case-variants of a coded path face the same verdict (the FS is case-insensitive)
    for rel, want in ((rr("keyturn", "x.mp4"), ("earned", "feat-b")),
                      (rr("starfall", "x.mp4"), ("earned", "feat-a"))):
        head, _, tail = rel.rpartition("/")
        assert g._seal_rule(head.upper() + "/" + tail) == want, rel
        assert g._seal_rule(rel.upper()) == want, rel


def test_moment_buckets_deny_when_no_feat_carries_the_flag(monkeypatch):
    """An older pack (no `moment` flags) or no pack at all: both buckets DENY. Falling
    through would be the seal's fail-open default -- sealed art served to anyone."""
    monkeypatch.setattr(g, "_moment_ach", lambda: {})
    for rel in (g._role_rel("starfall", "ee_nelstarfall.png"),
                g._role_rel("breadcrumb", "README.txt"),
                g._role_rel("keyturn", g._MOMENT_CLIPS["keyturn"])):
        assert g._seal_rule(rel) == ("deny", None), rel


def test_a_roster_without_flags_derives_no_moments():
    defs = g._derive_sealed({"roster": [{"id": "x", "hidden": True}]})
    assert defs["_moment_ach"] == {}
    defs = g._derive_sealed({"roster": [{"id": "a", "moment": "starfall"},
                                        {"id": "b", "moment": "starfall"},
                                        {"id": "c", "moment": ""}]})
    assert defs["_moment_ach"] == {"starfall": "a"}          # first entry wins; "" is no flag


def test_the_sealed_roster_flags_both_moments_on_hidden_feats(sealed_donor_present):
    moments = g._moment_ach()
    assert set(moments) >= {"starfall", "keyturn"}
    for m in ("starfall", "keyturn"):
        assert moments[m] in g._ach_hidden(), m
    assert moments["starfall"] != moments["keyturn"]


# ---- HTTP Range on container-sourced assets ----------------------------------

def _open_asset_client(tmp_path, body):
    """A client whose container carries one OPEN (unsealed) asset, so the Range mechanics
    are exercised with no roster at all -- they run on public CI too."""
    rel = g._role_rel("mystery", "range_probe.png")
    cli = _client(tmp_path)
    _write_box(tmp_path, {rel: body})
    return cli, "/branding/mystery/range_probe.png"


_BODY = bytes(range(256)) * 40          # 10240 bytes, every offset distinguishable


@pytest.mark.parametrize("header,status,span", [
    ("bytes=0-1", 206, (0, 2)),
    ("bytes=100-199", 206, (100, 200)),
    ("bytes=-500", 206, (len(_BODY) - 500, len(_BODY))),            # suffix
    ("bytes=-999999", 206, (0, len(_BODY))),                        # suffix longer than the body
    ("bytes=10000-", 206, (10000, len(_BODY))),                     # open end
    ("bytes=10000-999999", 206, (10000, len(_BODY))),               # end past the body clamps
])
def test_container_asset_serves_a_byte_range(tmp_path, header, status, span):
    cli, url = _open_asset_client(tmp_path, _BODY)
    r = cli.get(url, headers={"Range": header})
    assert r.status_code == status
    start, stop = span
    assert r.data == _BODY[start:stop]
    assert r.headers["Content-Range"] == "bytes %d-%d/%d" % (start, stop - 1, len(_BODY))
    assert r.headers["Accept-Ranges"] == "bytes"
    assert int(r.headers["Content-Length"]) == stop - start


@pytest.mark.parametrize("header", ["bytes=10240-", "bytes=20000-20010"])
def test_a_range_past_the_end_is_416(tmp_path, header):
    cli, url = _open_asset_client(tmp_path, _BODY)
    r = cli.get(url, headers={"Range": header})
    assert r.status_code == 416
    assert r.headers["Content-Range"] == "bytes */%d" % len(_BODY)


@pytest.mark.parametrize("header", ["bytes=abc", "bytes=5-2", "items=0-1", "bytes=0-1,4-5"])
def test_a_range_it_does_not_serve_is_ignored_not_refused(tmp_path, header):
    """Malformed, another unit, several ranges: the whole body as 200 (RFC 9110 lets a
    server ignore Range), never a broken partial."""
    cli, url = _open_asset_client(tmp_path, _BODY)
    r = cli.get(url, headers={"Range": header})
    assert r.status_code == 200 and r.data == _BODY
    assert "Content-Range" not in r.headers


def test_no_range_is_the_whole_body_advertising_ranges(tmp_path):
    cli, url = _open_asset_client(tmp_path, _BODY)
    r = cli.get(url)
    assert r.status_code == 200 and r.data == _BODY
    assert r.headers["Accept-Ranges"] == "bytes"
    assert r.headers["Cache-Control"] == "no-cache, must-revalidate"


def test_an_if_range_request_gets_the_whole_body(tmp_path):
    """These responses carry no validator an If-Range could match, so the range is
    dropped rather than risk splicing two different versions."""
    cli, url = _open_asset_client(tmp_path, _BODY)
    r = cli.get(url, headers={"Range": "bytes=0-1", "If-Range": '"whatever"'})
    assert r.status_code == 200 and r.data == _BODY


def test_a_loose_file_still_ranges_through_send_from_directory(tmp_path):
    """The loose-file path is unchanged: a real file wins over the container and ranges
    the way send_from_directory always has."""
    cli, url = _open_asset_client(tmp_path, _BODY)
    loose = g.branding_root() / g._role_rel("mystery", "range_probe.png")
    loose.parent.mkdir(parents=True, exist_ok=True)
    loose.write_bytes(b"LOOSE" * 10)
    r = cli.get(url)
    assert r.status_code == 200 and r.data == b"LOOSE" * 10
    r = cli.get(url, headers={"Range": "bytes=0-4"})
    assert r.status_code == 206 and r.data == b"LOOSE"


# ---- the clips: verified once, sliced from memory ----------------------------

def _clip_client(tmp_path, monkeypatch, assets):
    """A client whose container carries `assets`, with the keyturn moment flagged on a
    stub feat that is earned -- the clip mechanics without a roster."""
    cli = _client(tmp_path)
    _write_box(tmp_path, assets)
    monkeypatch.setattr(g, "_moment_ach", lambda: {"keyturn": "feat-k"})
    monkeypatch.setattr(g, "_earned_achievement_ids", lambda *a, **k: frozenset({"feat-k"}))
    return cli


def test_a_clip_is_read_and_verified_once_then_sliced(tmp_path, monkeypatch):
    clip = MOMENT_FIXTURE_CLIP.read_bytes()
    key = g._public_rel_to_coded(g._MOMENT_CLIPS["keyturn"])
    cli = _clip_client(tmp_path, monkeypatch, {key: clip})
    reads = []
    real_get = mc.Container.get

    def counting_get(self, rel):
        reads.append(rel)
        return real_get(self, rel)

    monkeypatch.setattr(mc.Container, "get", counting_get)
    got = b""
    for start in range(0, len(clip), 1000):                  # a <video> walking the file
        r = cli.get(_KEYTURN_URL, headers={"Range": "bytes=%d-%d" % (start, start + 999)})
        assert r.status_code == 206
        got += r.data
    assert got == clip
    assert cli.get(_KEYTURN_URL).data == clip
    assert reads.count(key) == 1, "the clip must be read and verified once, then served from memory"


def test_a_corrupt_clip_is_404_and_never_cached(tmp_path, monkeypatch):
    """The whole blob is checked against its TOC digest before any slice goes out; a blob
    that fails it is absent, not served in pieces."""
    clip = MOMENT_FIXTURE_CLIP.read_bytes()
    key = g._public_rel_to_coded(g._MOMENT_CLIPS["keyturn"])
    cli = _clip_client(tmp_path, monkeypatch, {key: clip})
    dat = g._container_path()
    off = mc.open_container(dat)._toc["assets"][key][0]
    raw = bytearray(dat.read_bytes())
    raw[off + len(clip) // 2] ^= 0xFF
    dat.write_bytes(bytes(raw))
    clear_sealed_caches()
    assert cli.get(_KEYTURN_URL, headers={"Range": "bytes=0-1"}).status_code == 404
    assert cli.get(_KEYTURN_URL).status_code == 404
    assert not g._moment_clip_cache


# ---- the real roster: 404 before the earn, served after ----------------------

def test_the_keyturn_clip_404s_until_its_feat_is_earned(tmp_path, sealed_donor_present):
    cli = _client(tmp_path)
    assert cli.get(_KEYTURN_URL).status_code == 404
    assert cli.get(_KEYTURN_URL, headers={"Range": "bytes=0-1"}).status_code == 404
    _earn_keyturn(cli)
    r = cli.get(_KEYTURN_URL)
    assert r.status_code == 200 and r.data == MOMENT_FIXTURE_CLIP.read_bytes()
    assert r.mimetype == "video/mp4"
    r = cli.get(_KEYTURN_URL, headers={"Range": "bytes=0-1"})
    assert r.status_code == 206 and len(r.data) == 2
    # its own gate: earning keyturn opens nothing in the starfall bucket
    assert cli.get(_STARFALL_URL).status_code == 404


def test_the_starfall_clip_404s_until_its_feat_is_earned(tmp_path, sealed_donor_present):
    cli = _client(tmp_path)
    assert cli.get(_STARFALL_URL).status_code == 404
    ach_event(cli, STARFALL_EVENT)
    r = cli.get(_STARFALL_URL, headers={"Range": "bytes=-100"})
    assert r.status_code == 206 and r.data == MOMENT_FIXTURE_CLIP.read_bytes()[-100:]
    assert cli.get(_KEYTURN_URL).status_code == 404


def test_the_seeded_test_container_carries_the_fixture_under_each_clip_key(sealed_donor_present):
    box = g._get_container()
    assert box is not None
    for key in moment_clip_keys():
        assert box.get(key) == MOMENT_FIXTURE_CLIP.read_bytes(), key


# ---- /api/achievements: the flags go out only once earned ---------------------

_FLAG_KEYS = ("moment", "moment_clip", "moment_copy", "unlocks")


def _donor_copy():
    """{moment: its sealed copy}, from the private donor -- never spelled out here."""
    return {a["moment"]: a.get("moment_copy") or {} for a in _donor_roster() if a.get("moment")}


def test_moment_flags_are_absent_before_the_earn(tmp_path, sealed_donor_present):
    cli = _client(tmp_path)
    r = cli.get("/api/achievements")
    d = r.get_json()
    for a in d["achievements"]:
        for k in _FLAG_KEYS:
            assert k not in a, "%s present on an unearned payload entry" % k
    body = r.get_data(as_text=True)
    for moment, copy in _donor_copy().items():
        for v in copy.values():
            assert v not in body, "sealed %s copy served before the earn" % moment
        assert g._MOMENT_CLIPS[moment] not in body


def test_moment_flags_arrive_with_the_earn(tmp_path, sealed_donor_present):
    cli = _client(tmp_path)
    _earn_keyturn(cli)
    ach_event(cli, STARFALL_EVENT)
    d = cli.get("/api/achievements").get_json()
    by_moment = {a["moment"]: a for a in d["achievements"] if a.get("moment")}
    assert set(by_moment) == {"starfall", "keyturn"}
    donor = _donor_copy()
    for moment, a in by_moment.items():
        assert a["earned"] is True
        assert a["id"] == g._moment_ach()[moment]
        assert a["moment_clip"] == "/branding/" + g._MOMENT_CLIPS[moment]
        assert set(a["moment_copy"]) == _COPY_KEYS[moment], moment
        assert a["moment_copy"] == donor[moment]
        assert all(isinstance(v, str) and v for v in a["moment_copy"].values())
        assert cli.get(a["moment_clip"]).status_code == 200
    assert by_moment["keyturn"]["unlocks"] == "branding_tab"
    assert "unlocks" not in by_moment["starfall"]
    # the flags ride only the feats that carry them
    for a in d["achievements"]:
        if not a.get("moment"):
            assert not any(k in a for k in ("moment_clip", "moment_copy")), a["id"]


def test_one_earn_reveals_only_its_own_moment(tmp_path, sealed_donor_present):
    cli = _client(tmp_path)
    ach_event(cli, STARFALL_EVENT)
    d = cli.get("/api/achievements")
    moments = [a["moment"] for a in d.get_json()["achievements"] if a.get("moment")]
    assert moments == ["starfall"]
    for v in _donor_copy()["keyturn"].values():
        assert v not in d.get_data(as_text=True)


def test_earned_roster_flags_shape():
    assert g._earned_roster_flags(None) == {}
    assert g._earned_roster_flags({"id": "x"}) == {}
    out = g._earned_roster_flags({"id": "x", "moment": "keyturn", "unlocks": "branding_tab",
                                  "moment_copy": {"title1": "t", "n": 3}})
    assert out == {"unlocks": "branding_tab", "moment": "keyturn",
                   "moment_clip": "/branding/" + g._MOMENT_CLIPS["keyturn"],
                   "moment_copy": {"title1": "t"}}
    # a moment this build has no clip for still names itself, with an empty clip URL
    assert g._earned_roster_flags({"id": "x", "moment": "later"})["moment_clip"] == ""


# ---- the sealed copy never reaches a public file -----------------------------

_PUBLIC_TEXT = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".css", ".html", ".htm", ".json",
                ".md", ".txt", ".svg", ".map")


def _public_files():
    roots = [_REPO / "gallery" / "src", _REPO / "gallery" / "dist", _REPO / "loom",
             _REPO / "wiki", _REPO / "docs"]
    seen = set()
    for top in ("README.md", "CHANGELOG.md"):
        p = _REPO / top
        if p.is_file():
            seen.add(p)
            yield p
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p in seen or not p.is_file() or "node_modules" in p.parts:
                continue
            if p.suffix.lower() in _PUBLIC_TEXT:
                seen.add(p)
                yield p


def test_no_public_file_carries_moment_copy(sealed_donor_present):
    """Every moment's copy is sealed: it reaches a browser only in an earned
    /api/achievements answer. It must never be written into the front-end source, the Loom,
    the wiki, the docs, the README, the CHANGELOG or a built bundle."""
    needles = [(m, k, v) for m, copy in _donor_copy().items() for k, v in copy.items() if v]
    assert needles, "no moment copy in the donor -- the guard would be a no-op"
    scanned, leaks = 0, []
    for path in _public_files():
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for moment, key, needle in needles:
            if needle in text:
                # never echo the secret itself
                leaks.append("%s: %s moment_copy.%s" % (path.relative_to(_REPO), moment, key))
    assert scanned, "scanned no public file -- the guard would be a no-op"
    assert not leaks, "sealed moment copy in public files:\n  " + "\n  ".join(sorted(leaks))


def test_no_public_file_names_a_moment_feat(sealed_donor_present):
    """The hidden feats that carry a moment or an unlock are keyed in public code by those
    roster flags, never by their ids (pack v5; SCOPE_2026-09-11 id-free public source §5).
    The ids stay internal keys for state files and the sealed roster. Scanned: everything
    test_no_public_file_carries_moment_copy scans, plus the Python modules and the tests."""
    roster = json.loads(_SEALED_DONOR.read_text(encoding="utf-8")).get("roster") or []
    ids = sorted({a["id"] for a in roster
                  if isinstance(a, dict) and a.get("id") and (a.get("moment") or a.get("unlocks"))})
    assert ids, "no moment or unlock feat in the donor -- the guard would be a no-op"
    files = list(_public_files())
    files += first_party_sources()            # the app's modules: the root and moonglade/
    files += [p for p in (_REPO / "dev" / "tests").glob("*.py")]
    leaks = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, fid in enumerate(ids):
            if fid in text:
                leaks.append("%s: moment feat #%d" % (path.relative_to(_REPO), i))
    assert files, "scanned no public file -- the guard would be a no-op"
    assert not leaks, "a hidden feat's id in public files:\n  " + "\n  ".join(sorted(leaks))
