"""A SYNTHETIC sealed roster for the masked-feats tests -- invented names, invented riddles.

The real hidden feats, their riddles and their badges are not test material (and the real
pack carries no riddles yet). Everything here is made up: a test that asserts on the veil
asserts on "test riddle one", never on a real feat. It is written to the SAME place the
private donor is (the sealed container beside branding_root(), via the same container
writer), so it exercises the real seal, the real /api/achievements and the real routes --
and, needing no companion repo, it runs in public CI too.

Feats are earned by PINNING them in achievements.json's `earned_at` (pin-once: an id in that
record stays earned whatever its metric says), which is the honest way to earn a feat that
has no metric to drive in a test.
"""
import json

from PIL import Image, ImageDraw

import moonglade_container as _mc
import moonglade_gallery as g

from tests.conftest import clear_sealed_caches

# The masked feat's distinctive numbers: a leak test greps the serialized payload for these.
DISTINCT_THRESHOLD = 7331
FEAT_IDS = ("synth-feat-one", "synth-feat-two", "synth-feat-three")
BARE_ID = "synth-feat-bare"          # hidden, no riddle in the roster
TRIGGER_ID = "triggered"             # the one id the code itself keys on (the unleash gate)


def _feat(aid, name, n, riddle=True, nsfw=True, threshold=None):
    e = {"id": aid, "name": name, "icon": "X", "desc": "Synthetic description " + n,
         "tier": "feat", "bucket": "feat", "metric": "synth_metric_" + n,
         "threshold": threshold or 4000 + len(n), "hidden": True,
         "roast": "synthetic clean roast " + n, "roast_nsfw": "synthetic unleashed roast " + n}
    if riddle:
        e["riddle"] = "test riddle " + n
    if riddle and nsfw:
        e["riddle_nsfw"] = "test riddle " + n + ", unleashed"
    return e


def roster(riddles=True, nsfw=True, bare_first=False):
    feats = [_feat(FEAT_IDS[0], "Synthetic Feat One", "one", riddles, nsfw,
                  threshold=DISTINCT_THRESHOLD),
             _feat(FEAT_IDS[1], "Synthetic Feat Two", "two", riddles, nsfw),
             _feat(FEAT_IDS[2], "Synthetic Feat Three", "three", riddles, nsfw)]
    bare = _feat(BARE_ID, "Synthetic Feat Bare", "bare", riddle=False)
    trig = _feat(TRIGGER_ID, "Synthetic Trigger", "trig", riddle=False)
    out = ([bare] + feats if bare_first else feats + [bare]) + [trig]
    out.append({"id": "synth-visible", "name": "Synthetic Visible", "icon": "V",
                "desc": "Synthetic visible milestone", "tier": "common", "bucket": "milestone",
                "metric": "synth_visible", "threshold": 999999, "roast": "", "roast_nsfw": ""})
    return out


def seed(container_path, **kw):
    """Write the synthetic roster as the install's sealed container and reset the caches."""
    defs = {"roster": roster(**kw), "skins": [], "skin_unlock": {}, "ach_criteria": {},
            "ladder_tracks": []}
    _mc.write_container(container_path, {"_seed.txt": b"x"},
                        {"achievements": json.dumps(defs).encode("utf-8")})
    clear_sealed_caches()


def badge_png(aid, color=(200, 30, 60, 255), size=300):
    """A loose badge master for `aid`: a coloured disc on a transparent ground, so the mask's
    silhouette is the disc and any colour that leaks into it is visible. Returns the path."""
    bdir = g._role_dir("badges")
    bdir.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((size // 6, size // 6, size - size // 6, size - size // 6), fill=color)
    dst = bdir / (aid + ".png")
    im.save(dst)
    return dst


def all_badges():
    for aid in FEAT_IDS + (BARE_ID, TRIGGER_ID):
        badge_png(aid)


def earn(out_dir, *ids, day="2026-09-01"):
    """Pin `ids` as earned (pin-once), the way a real earn persists."""
    st = g.load_ach_state(out_dir)
    ea = dict(st.get("earned_at") or {})
    for i in ids:
        ea[i] = day
    st["earned_at"] = ea
    assert g.save_ach_state(out_dir, st)
    g._earned_ids_cache.update(t=0.0, ids=frozenset())
