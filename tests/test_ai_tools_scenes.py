"""The AI-Tools scene catalog: /api/scenes and the normalization behind it.

ISSUE #36. The AI-Tools modal rendered a hardcoded 28-entry array, so the scenes PixAI has
added since (daily-fortune, daily-setlog, mini-mart-ad) had no tile and were unreachable in
the UI. The grid now reads the LIVE catalog, which means the server owes the modal a row it
can draw a tile from -- a label, a shape chip, a detail line, a thumbnail, a tier -- derived
from a catalog whose every human-readable string is an i18n key.

The fixture below is the SHAPE of real rows captured read-only from listChatEditingScenes on
2026-09-04 (31 scenes; no submits, no spend), trimmed to the fields the app reads.
"""
import time

import pytest

import moonglade_gallery as g
from moonglade_gallery import save_catalog

from tests.conftest import login_client

_CDN = "https://images-ng.pixai.art/images/thumb/"


def _sc(scene_id, presets=(), custom=False, ref_min=None, tier=None, demo=(), selectors=()):
    """One raw chatEditingScene, shaped like the live capture."""
    row = {"sceneId": scene_id, "modelId": "2006468692917575683",
           "title": "growth:chat-editing-scene.%s.title" % scene_id,
           "name": "growth:chat-editing-scene.%s.name" % scene_id,
           "tags": ["pixai_" + scene_id.replace("-", "_")],
           "presets": [{"key": k, "name": None, "i18nKey": None} for k in presets],
           "custom": ({"label": "l", "description": "d", "placeholder": "p"} if custom else None),
           "images": {"background": "", "demo": list(demo)},
           "permission": {"membershipTier": tier},
           "refImages": ({"minCount": ref_min, "maxCount": ref_min} if ref_min else None),
           "selectors": list(selectors)}
    return row


# One of each shipped shape, plus the two scenes issue #36 named.
CATALOG = [
    _sc("plushie", demo=[_CDN + "aaa", _CDN + "bbb"]),                       # click
    _sc("tarot-card", presets=("auto", "the-sun", "the-hermit", "the-high-priestess")),  # select
    _sc("vtuber", presets=("custom",), custom=True, tier=1),                 # text
    _sc("chatfic", presets=("en", "ja", "ko", "zh-tw"), tier=1),             # lang
    _sc("character-card", presets=("english", "japanese", "chinese", "korean"),
        custom=True, tier=1),                                               # lang beats text
    _sc("dual-character-generator", presets=("facing-hug", "back-hug"), ref_min=2, tier=1,
        selectors=[{"id": "aspect-ratio", "label": None, "defaultKey": "3:4",
                    "options": [{"key": "3:4", "label": None}, {"key": "1:1", "label": None}]}]),
    _sc("daily-fortune", presets=("english", "japanese", "korean", "traditional-chinese"),
        tier=1, demo=[_CDN + "ccc"]),
    _sc("daily-setlog", presets=("0830", "1030", "1830", "2300"), tier=1),
    {"sceneId": None},                                                       # dropped by the route
]


@pytest.fixture(autouse=True)
def _clear_scene_memo():
    """The catalog memo is module-level (shared by every consumer, contest_board pattern), so
    a test that fills it must not decide the next one's answer."""
    g._scenes_cache.clear()
    yield
    g._scenes_cache.clear()


class _Upstream:
    """A stub chat_editing_scenes that counts calls and can be told to fail."""

    def __init__(self, rows=None, raises=None):
        self.rows, self.raises, self.calls = (rows if rows is not None else CATALOG), raises, 0

    def __call__(self, session):
        self.calls += 1
        if self.raises:
            raise self.raises
        return self.rows


def _core(up):
    """A stand-in `core` carrying only what scene_catalog touches."""
    return type("C", (), {"chat_editing_scenes": staticmethod(up)})


# --- normalization -------------------------------------------------------------------

def test_scene_row_derives_the_tile_fields_the_modal_draws():
    r = g.scene_row(_sc("daily-fortune",
                        presets=("english", "japanese", "korean", "traditional-chinese"),
                        tier=1, demo=[_CDN + "ccc"]))
    assert r["sceneId"] == "daily-fortune"
    # PixAI's `title` is an i18n key, so the label is the title-cased slug -- never the key.
    assert r["label"] == "Daily Fortune"
    assert "growth:" not in r["label"]
    assert r["shape"] == "lang" and r["detail"] == "EN / JP / KR / TC"
    assert r["tier"] == 1
    assert r["thumb"].startswith("/api/pixai-cdn/thumb?u=")


def test_scene_row_keeps_the_control_schema_the_gen_drawer_reads():
    """The tile fields are ADDITIVE -- SceneTab still finds its scene by sceneId and renders
    presets/selectors/custom/refMin from the same row."""
    r = g.scene_row(CATALOG[5])   # dual-character-generator
    assert [p["key"] for p in r["presets"]] == ["facing-hug", "back-hug"]
    assert r["presets"][0]["label"] == "Facing Hug"
    assert r["selectors"][0]["id"] == "aspect-ratio"
    assert r["selectors"][0]["default"] == "3:4"
    assert [o["key"] for o in r["selectors"][0]["options"]] == ["3:4", "1:1"]
    assert r["refMin"] == 2 and r["refMax"] == 2
    assert r["custom"] is False


@pytest.mark.parametrize("scene_id,expected", [
    ("plushie", "click"),                       # no presets: one tap
    ("tarot-card", "select"),                   # preset chips
    ("vtuber", "text"),                         # a custom text field
    ("chatfic", "lang"),                        # presets ARE the language list
    ("character-card", "lang"),                 # lang beats text when it has both
    ("dual-character-generator", "dual"),       # two source images
    ("daily-setlog", "select"),                 # times, not languages
    ("daily-fortune", "lang"),
])
def test_shape_is_derived_from_the_live_schema(scene_id, expected):
    """Derivation, not a table: it reproduced all 28 shipped tile shapes against the live
    catalog on 2026-09-04, which is what lets a scene PixAI adds classify itself."""
    row = next(s for s in CATALOG if s.get("sceneId") == scene_id)
    assert g.scene_row(row)["shape"] == expected


def test_refless_scene_defaults_to_one_source():
    assert g.scene_row(_sc("plushie"))["refMin"] == 1


@pytest.mark.parametrize("images,expected", [
    ({"background": "", "demo": [_CDN + "x", _CDN + "y"]},
     "/api/pixai-cdn/thumb?u=https%3A%2F%2Fimages-ng.pixai.art%2Fimages%2Fthumb%2Fx"),
    ({"background": _CDN + "bg", "demo": []},
     "/api/pixai-cdn/thumb?u=https%3A%2F%2Fimages-ng.pixai.art%2Fimages%2Fthumb%2Fbg"),
    ({"background": "", "demo": []}, ""),          # a scene that ships no art
    (None, ""),
    ({"demo": ["https://example.invalid/a.webp"]}, "https://example.invalid/a.webp"),
])
def test_catalog_thumbnail_goes_through_the_cdn_proxy_only_for_the_cdn_host(images, expected):
    """The proxy's SSRF guard accepts exactly images-ng.pixai.art, so pointing anything else
    at it would 403. Off-host urls pass through untouched instead."""
    assert g.scene_thumb_url(images) == expected


def test_the_catalog_carries_no_price_so_no_row_pretends_to():
    """PixAI exposes no scene task-price op and no price/credit/cost field anywhere in the
    catalog (checked over all 31 live scenes). SceneTab's confirm names the spend instead;
    a row must not grow a fake one."""
    r = g.scene_row(CATALOG[0])
    assert not {k for k in r if k.lower() in ("price", "cost", "credit", "credits")}


# --- the memo ------------------------------------------------------------------------

def test_catalog_is_memoized_so_both_scene_surfaces_share_one_upstream_read():
    up = _Upstream()
    core = _core(up)
    assert g.scene_catalog(core, object()) == CATALOG
    assert g.scene_catalog(core, object()) == CATALOG
    assert up.calls == 1


def test_memo_expires_after_the_ttl():
    up = _Upstream()
    core = _core(up)
    g.scene_catalog(core, object())
    g._scenes_cache["catalog"]["at"] = time.time() - g.SCENES_TTL - 1
    g.scene_catalog(core, object())
    assert up.calls == 2


def test_force_drops_the_memo():
    up = _Upstream()
    core = _core(up)
    g.scene_catalog(core, object())
    g.scene_catalog(core, object(), force=True)
    assert up.calls == 2


def test_a_failure_is_not_cached():
    """A raise must reach the caller AND leave the store untouched, so the next open retries
    PixAI instead of being served a remembered outage for an hour."""
    bad = _Upstream(raises=RuntimeError("upstream down"))
    with pytest.raises(RuntimeError):
        g.scene_catalog(_core(bad), object())
    assert "catalog" not in g._scenes_cache
    good = _Upstream()
    assert g.scene_catalog(_core(good), object()) == CATALOG
    assert good.calls == 1


def test_an_empty_answer_is_not_cached():
    """An account that briefly answers [] must not blank the modal for the whole TTL."""
    empty = _Upstream(rows=[])
    assert g.scene_catalog(_core(empty), object()) == []
    assert "catalog" not in g._scenes_cache
    assert g.scene_catalog(_core(empty), object()) == []
    assert empty.calls == 2


# --- the route -----------------------------------------------------------------------

def _armed(monkeypatch, up):
    import moonglade_backup as core
    monkeypatch.setattr(core, "mirror_enabled", lambda: True)
    monkeypatch.setattr(core, "make_mirror_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "chat_editing_scenes", up)


def test_api_scenes_serves_every_live_scene_with_its_tile_fields(tmp_path, monkeypatch):
    up = _Upstream()
    _armed(monkeypatch, up)
    save_catalog(tmp_path / "catalog.db", [])
    d = login_client(tmp_path).get("/api/scenes").get_json()
    ids = [s["sceneId"] for s in d["scenes"]]
    # the rows with no sceneId are dropped; the new scenes are NOT
    assert None not in ids
    assert "daily-fortune" in ids and "daily-setlog" in ids
    assert len(ids) == len([s for s in CATALOG if s.get("sceneId")])
    fortune = next(s for s in d["scenes"] if s["sceneId"] == "daily-fortune")
    assert fortune["label"] == "Daily Fortune" and fortune["shape"] == "lang"
    assert fortune["thumb"].startswith("/api/pixai-cdn/thumb?u=")


def test_api_scenes_refuses_when_the_mirror_is_not_armed(tmp_path, monkeypatch):
    import moonglade_backup as core
    monkeypatch.setattr(core, "mirror_enabled", lambda: False)
    save_catalog(tmp_path / "catalog.db", [])
    r = login_client(tmp_path).get("/api/scenes")
    assert r.status_code == 409 and "Mirror" in r.get_json()["error"]


def test_api_scenes_answers_an_upstream_failure_as_an_error_body(tmp_path, monkeypatch):
    """The gallery's one error rule: the BODY carries the refusal (HTTP 200), and the client
    falls back to its offline tiles rather than opening onto an empty grid."""
    _armed(monkeypatch, _Upstream(raises=RuntimeError("boom")))
    save_catalog(tmp_path / "catalog.db", [])
    d = login_client(tmp_path).get("/api/scenes").get_json()
    assert d.get("error") and not d.get("scenes")


def test_two_route_reads_share_the_memo(tmp_path, monkeypatch):
    up = _Upstream()
    _armed(monkeypatch, up)
    save_catalog(tmp_path / "catalog.db", [])
    cli = login_client(tmp_path)
    cli.get("/api/scenes")
    cli.get("/api/scenes")
    assert up.calls == 1
