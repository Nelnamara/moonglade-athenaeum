"""
moonglade/scenes.py
===================
The AI-Tools scene catalog: `scene_catalog` (PixAI's scene list, memoised for SCENES_TTL under
`_scenes_cache_lock`), the row shaping the modal and the generator read (`scene_row` and its
helpers), `scene_thumb_url`, `scene_local_art` and `pixai_cdn_url_ok`. Moved verbatim out of
moonglade/gallery.py in the 3.22 split (phase 4).

It needs nothing from the gallery or the engine: the scene read is moonglade.gen_road's, the
local art moonglade.branding's.
"""
import threading
import time

from moonglade import branding as _branding
from moonglade import gen_road as _gen_road


# --- the AI-Tools scene catalog ------------------------------------------------------
# PixAI's `listChatEditingScenes`, memoized module-level on the contest_board pattern: ONE
# snapshot every consumer shares, a lock around it, and FAILURES ARE NOT CACHED (a raise
# never reaches the store, and an empty answer is not banked as "the catalog is empty").
#
# Two consumers, one read: the AI-Tools nav modal browses the TILES and the gen drawer's
# scene generator reads the picked scene's CONTROL SCHEMA. Before 2026-09-04 the modal read
# nothing at all -- it rendered a hardcoded 28-entry array, so `daily-fortune`, `daily-setlog`
# and `mini-mart-ad` (live on PixAI, 31 scenes as of this writing) had no tile and were
# unreachable in the UI (issue #36). Both halves now come from here.
#
# TTL stays at an hour, NOT the contest board's 90s: a contest's entries change by the
# minute, the scene catalog gains a scene every few weeks, and the repo's standing rule is
# to be polite to their servers. The shared pattern is the memo, not the number.
SCENES_TTL = 3600.0
_scenes_cache = {}
_scenes_cache_lock = threading.Lock()

# Preset keys PixAI uses for the "pick a language" scenes. Every human-readable string in the
# catalog is an i18n key (`growth:chat-editing-scene.<slug>.title`), so the catalog cannot
# name a scene or a preset for us -- but the KEYS are stable, and these are the ones that mean
# "this scene's presets are languages" (captured live 2026-09-04: character-card
# english/japanese/chinese/korean, chatfic en/ja/ko/zh-tw, character-style-generator +
# daily-fortune + mini-mart-ad english/japanese/korean/traditional-chinese).
_SCENE_LANG_KEYS = {
    "english": "EN", "en": "EN", "japanese": "JP", "ja": "JP", "jp": "JP",
    "korean": "KR", "ko": "KR", "kr": "KR", "chinese": "CN", "zh": "CN", "zh-cn": "CN",
    "traditional-chinese": "TC", "zh-tw": "TC", "tw": "TC",
    "simplified-chinese": "CN", "zh-hant": "TC", "zh-hans": "CN",
}
# The only host the CDN thumbnail proxy will fetch (api_train_cover's SSRF guard). A catalog
# demo image on any other host is passed through as-is rather than pointed at a proxy that
# would 403 it.
_SCENE_CDN_HOST = "images-ng.pixai.art"


def pixai_cdn_url_ok(url):
    """THE host guard for fetching a PixAI picture server-side (api_train_cover's SSRF guard,
    shared with the Loom's frame-thumbnail fill): https, on exactly the PixAI image CDN."""
    import urllib.parse as _up
    try:
        p = _up.urlparse(str(url or ""))
    except ValueError:
        return False
    return p.scheme == "https" and p.netloc == _SCENE_CDN_HOST


def scene_catalog(core, session, force=False):
    """The WHOLE live scene catalog (listChatEditingScenes), memoized for SCENES_TTL.

    The one read both scene consumers go through, so opening the modal and then opening the
    generator costs a single round trip rather than two. `force` drops the memo.

    Failure handling is the point: `core.chat_editing_scenes` raising propagates BEFORE the
    store is touched (the next caller retries against PixAI instead of being served a
    remembered outage), and an empty list is likewise not banked -- an account that briefly
    answers `[]` must not blank the modal for the next hour."""
    now = time.time()
    with _scenes_cache_lock:
        ent = _scenes_cache.get("catalog")
        if not force and ent and (now - ent["at"]) < SCENES_TTL:
            return ent["rows"]
    rows = _gen_road.chat_editing_scenes(session)
    if rows:
        with _scenes_cache_lock:
            _scenes_cache["catalog"] = {"at": time.time(), "rows": rows}
    return rows


def _scene_label(key):
    """A display label for a scene/preset/selector key -- PixAI's own `name` is the full
    workflow prompt (tarot) and its `title` is an i18n key
    (`growth:chat-editing-scene.plushie.title`), so the human-readable form is the
    title-cased key ('the-sun' -> 'The Sun', 'daily-fortune' -> 'Daily Fortune')."""
    return (str(key or "").replace("-", " ").replace("_", " ").strip().title())


def _scene_shape(preset_keys, has_custom, ref_min):
    """Which control row a scene needs, from its live schema alone -- the tile's shape chip.

    Ordered most-specific first, and verified against all 28 curated tiles on 2026-09-04:
    this derivation reproduces every one of the shipped shapes, which is what makes it safe
    to let a scene PixAI adds tomorrow classify itself.
      dual   -- needs two source images (dual-character-generator)
      lang   -- its presets ARE the language list (character-card, chatfic, daily-fortune)
      text   -- it takes a custom text field (polaroid, vtuber, gacha-screen)
      select -- any other preset chips (tarot modes, fantasy classes, setlog times)
      click  -- no presets at all: one tap (plushie, lego, giant-statue)
    `lang` beats `text` deliberately: character-card has BOTH, and its shipped chip is
    Language."""
    keys = [str(k or "").strip().lower() for k in (preset_keys or []) if k]
    if int(ref_min or 1) >= 2:
        return "dual"
    if keys and all(k in _SCENE_LANG_KEYS for k in keys):
        return "lang"
    if has_custom:
        return "text"
    return "select" if keys else "click"


def _scene_detail(shape, preset_keys):
    """The tile's small grey line under the name, derived for scenes we carry no curated copy
    for. Deliberately modest -- it says what the live schema actually shows (language codes,
    the first few preset names, a count) and never invents flavour text."""
    keys = [str(k or "").strip().lower() for k in (preset_keys or []) if k]
    if shape == "lang":
        seen, codes = set(), []
        for k in keys:
            code = _SCENE_LANG_KEYS.get(k)
            if code and code not in seen:
                seen.add(code)
                codes.append(code)
        return " / ".join(codes)
    if shape == "dual":
        return "2 refs · %d poses" % len(keys) if keys else "2 refs"
    if shape == "text":
        return "custom text"
    if shape == "select":
        if 0 < len(keys) <= 3:
            return " / ".join(_scene_label(k) for k in keys)
        return "%d options" % len(keys) if keys else ""
    return ""


def scene_thumb_url(images):
    """The catalog's OWN thumbnail for a scene, as a URL this app can actually load.

    PixAI serves scene demo art from its image CDN, which the browser cannot fetch
    cross-origin from localhost -- so a CDN url is handed back through the existing
    /api/pixai-cdn/thumb proxy (the same one the Train panel and My Art's LoRA cards use)
    rather than growing a second one. `images.demo` is a LIST of urls used directly as an
    <img src> by PixAI's own /ai-tools/<slug> page; `images.background` was empty on every
    one of the 31 scenes captured 2026-09-04, so demo[0] is the picture. Anything off the
    CDN host is passed through untouched -- the proxy's SSRF guard would refuse it, and a
    raw url at least has a chance of loading. Returns "" when the scene ships no art."""
    import urllib.parse as _up
    imgs = images if isinstance(images, dict) else {}
    cands = []
    for field in ("demo", "background"):
        val = imgs.get(field)
        if isinstance(val, str):
            cands.append(val)
        elif isinstance(val, (list, tuple)):
            cands.extend(val)
    for raw in cands:
        url = str(raw or "").strip()
        if not url:
            continue
        try:
            parsed = _up.urlparse(url)
        except ValueError:
            continue
        if parsed.scheme == "https" and parsed.netloc == _SCENE_CDN_HOST:
            return "/api/pixai-cdn/thumb?u=" + _up.quote(url, safe="")
        return url
    return ""


def scene_local_art(slug):
    """True when a curated local picture for this scene exists: bridge/scene_<slug>.webp, loose
    in the branding tree or packed in the container (the order /branding/<path> serves them).
    The AI Tools grid asks this before it requests the file, so a scene with no local art goes
    straight to the catalog's own picture instead of a 404 per tile."""
    slug = str(slug or "")
    if not slug or "/" in slug or "\\" in slug or ".." in slug:
        return False
    try:
        coded = _branding._public_rel_to_coded("bridge/scene_{}.webp".format(slug))
        if (_branding.branding_root() / coded).is_file():
            return True
        box = _branding._get_container()
        return bool(box is not None and box.has(coded))
    except Exception:
        return False


def scene_row(sc):
    """One raw chatEditingScene -> the row both scene surfaces render.

    The CONTROL half (presets / selectors / custom / refMin) is what the gen drawer's scene
    generator builds its form from. The TILE half (label / shape / detail / thumb / tier) is
    what the AI-Tools modal's grid draws, and exists so a scene PixAI adds gets a tile with
    no code change -- the whole point of issue #36.

    Every human string in the catalog is an i18n key, so `label` is the title-cased sceneId,
    not PixAI's `title`. The modal still overlays its own curated copy where it has some
    ("Character Style Generator" ships as "Character Style"); this is the floor, not a
    redesign of the shipped tiles.

    NO price: the catalog carries no price/credit/cost field anywhere (confirmed over all 31
    live scenes, 2026-09-04), which is the same reason SceneTab's confirm names the spend
    instead of quoting it."""
    presets = [{"key": p.get("key"), "label": _scene_label(p.get("key"))}
               for p in (sc.get("presets") or []) if p.get("key")]
    selectors = [{"id": x.get("id"), "label": x.get("label") or _scene_label(x.get("id")),
                  "default": x.get("defaultKey"),
                  "options": [{"key": o.get("key"),
                               "label": o.get("label") or _scene_label(o.get("key"))}
                              for o in (x.get("options") or []) if o.get("key")]}
                 for x in (sc.get("selectors") or []) if x.get("id")]
    refs = sc.get("refImages") or {}
    ref_min = int(refs.get("minCount") or 1)
    ref_max = int(refs.get("maxCount") or max(ref_min, 1))
    keys = [p["key"] for p in presets]
    shape = _scene_shape(keys, bool(sc.get("custom")), ref_min)
    return {"sceneId": sc.get("sceneId"), "modelId": sc.get("modelId"),
            "tier": (sc.get("permission") or {}).get("membershipTier"),
            "refMin": ref_min, "refMax": ref_max,
            "presets": presets, "selectors": selectors,
            "custom": bool(sc.get("custom")),
            "label": _scene_label(sc.get("sceneId")),
            "shape": shape,
            "detail": _scene_detail(shape, keys),
            "thumb": scene_thumb_url(sc.get("images"))}
