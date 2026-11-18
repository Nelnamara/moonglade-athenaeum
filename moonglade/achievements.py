"""
moonglade/achievements.py
=========================
Achievements and skins: the sealed roster readers (the definitions live in the art pack,
read lazily and cached, with the free-skins-only fallback), the metrics, points, criteria and
compute, the progress lines, the toast state, and the badge thumbnails and animations. Moved
verbatim out of moonglade/gallery.py in the 3.21.0 split (phase 3), from its two places there.

It reaches telemetry as `_telemetry.X`, as the gallery did once telemetry moved out. The names
it needs from the gallery (the catalog and its counts, the pack and branding-tree readers) are
imported inside each function that uses them, never at the top, so importing this module never
imports the gallery.
"""
import json
import re
import sqlite3
import threading
import time

from moonglade import paths as _paths
from moonglade import telemetry as _telemetry
# ---------------------------------------------------------------------------
# Achievements & Skins -- WoW-flavored milestones computed from local catalog
# stats (read-only, no spend). Earning an epic tier unlocks a cosmetic skin
# (a CSS-variable palette swap in the browser). State (which unlocks the user
# has already been *toasted* for, plus the active skin) persists to
# out_dir/_moonglade/records/achievements.json. See ACHIEVEMENTS/SKINS below for the catalog.
# ---------------------------------------------------------------------------
# ACHIEVEMENTS roster: SEALED into the art pack (see _sealed_defs below). Read via _roster().

# ---------------------------------------------------------------------------
# The achievement roster + its ancillary tables (skins, skin-unlock text, the
# closed-set criteria labels, ladder-track names) are DEFINITIONS. They used to sit
# inline here, readable in a public `git clone`; they now live SEALED in
# the art pack's "achievements" payload (a dict), built from the private donor
# ../moonglade-internal/achievements_folio_donor.json by dev/tools/build_container.py.
# Loaded LAZILY + cached (out_dir -- so the container path -- is not known at import).
# A container-less install degrades to the free-skins-only fallback (empty Folio,
# like missing art), never a crash. See ACHIEVEMENT_SEALING_SPEC.md; this is what
# lets the /api/achievements ??? masking finally protect something.
# The free skins are the app's DEFAULT dress (not rewards), so their non-spoiler
# names stay public as the no-container fallback.
_FALLBACK_DEFS = {
    "roster": [], "skin_unlock": {}, "ach_criteria": {}, "ladder_tracks": [],
    "skins": [
        {"id": "moonglade",   "name": "Moonglade",   "free": True,
         "desc": "The default -- lavender leads, emerald magic."},
        {"id": "nightfallen", "name": "Nightfallen", "free": True,
         "desc": "Void-touched violet and star-ash."},
    ],
}
_sealed_cache = {"path": None, "mtime": None, "defs": None}
_sealed_lock = threading.Lock()


def _sealed_defs():
    """The sealed achievement definitions {roster, skins, skin_unlock, ach_criteria,
    ladder_tracks} from the art pack's "achievements" payload, plus the derived id /
    hidden / rung / skin-id sets. Cached per (container path, mtime) and computed UNDER
    the lock, so a cold-cache race (N workers hitting /api/achievements at once) decodes
    it once, not once per request. Fallback (free skins only) when there is no valid
    container OR the sealed roster is malformed -- the Folio degrades, never 500s."""
    from moonglade.gallery import _container_path, _get_container
    p = _container_path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = None
    # Open the container OUTSIDE _sealed_lock (it has its own _container_lock). The
    # decode+derive below runs UNDER _sealed_lock -- it re-enters neither lock, so holding
    # it here just serializes concurrent cold misses instead of decoding the payload N
    # times (box.payload does XOR + zlib.decompress; a few ms, not free).
    box = _get_container()
    with _sealed_lock:
        c = _sealed_cache
        if c["path"] == p and c["mtime"] == mtime and c["defs"] is not None:
            return c["defs"]
        defs = None
        raw = box.payload("achievements") if box is not None else None
        if raw:
            try:
                d = json.loads(raw)
                if isinstance(d, dict) and "roster" in d:
                    defs = d
            except ValueError:
                defs = None
        # A checksum-valid but MALFORMED roster (valid JSON, but "roster" not a list of
        # well-shaped entries) must degrade like a missing one, not 500 the whole Folio:
        # derive from it, and on any shape error fall back to the free-skins defaults.
        try:
            computed = _derive_sealed(defs if defs is not None else _FALLBACK_DEFS)
        except (KeyError, TypeError, AttributeError):
            computed = _derive_sealed(_FALLBACK_DEFS)
        _sealed_cache.update(path=p, mtime=mtime, defs=computed)
        return computed


def _derive_sealed(defs):
    """Normalize a raw sealed-defs dict and attach the derived id / hidden / rung /
    skin-id sets. Raises (KeyError/TypeError/AttributeError) on a malformed roster so
    _sealed_defs can catch it and fall back to the free-skins defaults. _FALLBACK_DEFS is
    well-formed, so _derive_sealed(_FALLBACK_DEFS) is the guaranteed-safe last resort."""
    roster = defs.get("roster") or []
    defs = dict(defs)
    defs.setdefault("skins", [])
    defs.setdefault("skin_unlock", {})
    defs.setdefault("ach_criteria", {})
    defs.setdefault("ladder_tracks", [])
    # The narrator's poke lines (moonglade.narrator.clean_pools' shape). Carried whole from
    # the pack like the roster; a pack that has none leaves the narrator on its neutral line.
    if not isinstance(defs.get("poke_lines"), dict):
        defs["poke_lines"] = {}
    defs["_ach_ids"] = frozenset(a["id"] for a in roster)
    defs["_ach_hidden"] = frozenset(a["id"] for a in roster if a.get("hidden"))
    defs["_ach_rung"] = _build_ach_rung(roster)
    defs["_skin_ids"] = {s["id"] for s in defs["skins"]}
    # The roster FLAGS the code keys on instead of an id (pack v5): `moment` names the
    # bespoke moment a feat plays, `unlocks` what it opens. {moment: achievement id},
    # first roster entry wins -- the seal rule and the API resolve "which feat" here,
    # so no hidden id is ever a literal in this source. A roster without the flag (an
    # older pack) yields no entry, and every caller fails closed on a missing one.
    moment_ach = {}
    for a in roster:
        m = a.get("moment")
        if isinstance(m, str) and m:
            moment_ach.setdefault(m, a["id"])
    defs["_moment_ach"] = moment_ach
    return defs


def _roster():        return _sealed_defs()["roster"]          # noqa: E704
def _skins():         return _sealed_defs()["skins"]           # noqa: E704
def _skin_unlock():   return _sealed_defs()["skin_unlock"]     # noqa: E704
def _ach_criteria():  return _sealed_defs()["ach_criteria"]    # noqa: E704
def _ladder_tracks(): return _sealed_defs()["ladder_tracks"]   # noqa: E704
def _ach_ids():       return _sealed_defs()["_ach_ids"]        # noqa: E704
def _ach_hidden():    return _sealed_defs()["_ach_hidden"]     # noqa: E704
def _ach_rung():      return _sealed_defs()["_ach_rung"]       # noqa: E704
def _skin_ids():      return _sealed_defs()["_skin_ids"]       # noqa: E704
def _moment_ach():    return _sealed_defs()["_moment_ach"]     # noqa: E704
def _poke_lines():    return _sealed_defs()["poke_lines"]      # noqa: E704


# Prompt word-cloud vocabulary, shared by the /health word cloud and the Watchword
# achievement so both count the identical set of meaningful prompt words. Hoisted from
# collection_health()'s own inline block (kept byte-identical) so top_word_uses can never
# drift from what the dashboard shows.
_PROMPT_STOPWORDS = frozenset({
    "the", "and", "a", "an", "of", "with", "in", "on", "at", "to", "for",
    "is", "by", "as", "or", "from", "best", "quality", "masterpiece",
    "highres", "detailed", "very", "high", "score", "up", "1girl", "1boy",
    "solo", "looking", "viewer"})


def _prompt_word_counter(rows):
    """Counter of meaningful prompt words across prompt_preview values. `rows` is an
    iterable of 1-tuples (the SELECT prompt_preview shape) or bare strings. Pure; drops the
    shared stopwords. Sealing note: the word itself is only ever surfaced as a COUNT by
    callers (Watchword takes most_common(1)[0][1]) -- the word never leaves this layer."""
    from collections import Counter
    c = Counter()
    for r in rows:
        pp = r if isinstance(r, str) else r[0]   # a 1-tuple / sqlite3.Row / list -> its first col
        for w in re.findall(r"[a-z][a-z']{2,}", (pp or "").lower()):
            if w not in _PROMPT_STOPWORDS:
                c[w] += 1
    return c


# The achievement-metrics cache. Keyed by db_path (so a test's tmp catalog never
# collides) and invalidated on the same cheap `(COUNT(*), MAX(media_id))` key the
# series cache uses.
#
# DELIBERATELY NO TIME FLOOR, unlike that cache. A floor means a catalog change is
# bounded-stale, and one of this bundle's consumers is the ACHIEVEMENT GATE: earning
# something unlocks its art, and "your banner appears within thirty seconds" is a bug,
# not a bounded staleness (caught by dev/tests/test_unlock_split.py, which earns mid-test
# and asks for the art immediately). The key alone is enough for the case that was
# actually slow -- repeatedly opening overlays against a catalog nobody is writing to,
# which is every open outside a sync. During a sync it recomputes per request, exactly
# as it did before this cache existed, so nothing regressed there either.
#
# It exists because this bundle is NOT the "cheap COUNTs" its docstring once claimed
# on its own: four of its passes read every matching row -- rated, the LoRA CSV
# split, the palindrome seed scan and the prompt word counter -- and the whole
# bundle reran on EVERY /api/achievements call. That is the Folio opening, the
# Control Panel opening, and every achievement re-check, each paying a full-library
# walk. On a modest machine with a real library that is the overlay-open stall the
# owner reported (2026-09-03).
_ACH_METRICS_CACHE = {}
_ACH_METRICS_LOCK = threading.Lock()


def achievement_metrics(db_path, use_cache=True):
    """The metric bundle every achievement threshold is measured against. Read-only over
    the local catalog -- no network, no spend. Fails soft.

    NOT the "cheap COUNTs" this docstring used to claim, which is why the memo below
    exists: most of it is indexed COUNTs, but four passes read every matching ROW and
    process it in Python -- `rated`, the LoRA CSV split, the palindrome seed scan, and the
    prompt word counter. On a real library that is the expensive part of opening the Folio
    or the Control Panel, and it ran on every /api/achievements call before 2026-09-03.

    CACHED (see _ACH_METRICS_CACHE): recomputed whenever the catalog's cheap key
    changes, and served from the memo when it has not. `use_cache=False` forces a real
    read -- what a test asserting the computation itself wants."""
    from moonglade.gallery import catalog, catalog_counts
    if use_cache:
        try:
            with catalog(db_path) as con:
                cheap = tuple(con.execute(
                    "SELECT COUNT(*), MAX(media_id) FROM catalog").fetchone())
            with _ACH_METRICS_LOCK:
                ent = _ACH_METRICS_CACHE.get(str(db_path))
                if ent is not None and ent["key"] == cheap:
                    return dict(ent["metrics"])          # a COPY: callers .update() it
            fresh = achievement_metrics(db_path, use_cache=False)
            with _ACH_METRICS_LOCK:
                _ACH_METRICS_CACHE[str(db_path)] = {
                    "key": cheap, "computed_at": time.time(), "metrics": dict(fresh)}
            return fresh
        except sqlite3.Error:
            pass          # a broken/missing catalog falls through to the real read
    m = catalog_counts(db_path)   # images, videos, collections
    with catalog(db_path) as con:
        try:
            def _scalar(sql):
                return int(con.execute(sql).fetchone()[0] or 0)
            m["models"] = _scalar(
                "SELECT COUNT(DISTINCT COALESCE(NULLIF(model_name,''), NULLIF(model_id,''))) "
                "FROM catalog WHERE COALESCE(model_name,'') != '' OR COALESCE(model_id,'') != ''")
            m["published"] = _scalar("SELECT COUNT(*) FROM catalog WHERE is_published = '1'")
            m["tagged"] = _scalar("SELECT COUNT(*) FROM catalog WHERE COALESCE(art_tags,'') != ''")
            # The Moonforge: gens made IN the app -- same set as the gallery's
            # "made locally" filter (source api OR local), NOT just api.
            m["local_gens"] = _scalar(
                "SELECT COUNT(*) FROM catalog WHERE source IN ('api','local')")
            # Marathon: the busiest single calendar day of in-app conjuring.
            m["gens_in_a_day"] = _scalar(
                "SELECT COALESCE(MAX(c), 0) FROM (SELECT COUNT(*) AS c FROM catalog "
                "WHERE source IN ('api','local') AND COALESCE(created_at,'') != '' "
                "GROUP BY substr(created_at, 1, 10))")
            # The Lexicon: distinct keywords across every tagged piece (art_tags is
            # a comma list; the split has to happen Python-side).
            kw = set()
            for (tags,) in con.execute(
                    "SELECT art_tags FROM catalog WHERE COALESCE(art_tags,'') != ''"):
                for t in (tags or "").split(","):
                    t = t.strip().lower()
                    if t:
                        kw.add(t)
            m["distinct_keywords"] = len(kw)
            # --- Folio expansion catalog metrics (all COUNT-only integers; no rating value,
            # LoRA name, seed value, or prompt word ever leaves this function) ---
            # The Bench (rated): health-panel-identical -- a non-empty, non-zero rating.
            m["rated"] = _scalar(
                "SELECT COUNT(*) FROM catalog "
                "WHERE COALESCE(NULLIF(rating,''),'0') NOT IN ('0')")
            # The Atelier (loras_distinct): distinct LoRA NAME-keys across the per-row `loras`
            # CSV (drop ':weight'), parsed exactly like collection_health's top-LoRAs block,
            # over the WHOLE library.
            # The same pass counts the IN-APP rows (source api/local, the Moonforge's set) for
            # the three LoRA honors that used to be bumped on an accepted submit (owner
            # 2026-10-02: evidence-based counts): lora_used = distinct in-app generations that
            # used one, lora_stacked = the most on one generation, lora_distinct = distinct
            # names across them. A submit that never produced a picture counts nothing now.
            lk, in_app_names, lora_tasks, stacked = set(), set(), set(), 0
            for (loras, src, tid, mid) in con.execute(
                    "SELECT loras, source, task_id, media_id FROM catalog "
                    "WHERE COALESCE(loras,'') != ''"):
                names = [part.strip().rsplit(":", 1)[0].strip()   # drop ":weight"
                         for part in (loras or "").split(",")]
                names = [n for n in names if n]
                lk.update(names)
                if names and src in ("api", "local"):
                    in_app_names.update(names)
                    lora_tasks.add(tid or ("media:" + str(mid)))
                    stacked = max(stacked, len(names))
            m["loras_distinct"] = len(lk)
            m["lora_used"] = len(lora_tasks)
            m["lora_stacked"] = stacked
            m["lora_distinct"] = len(in_app_names)
            # The Restoration Wing (edits): in-app generations that ARE edits by their own
            # lineage (derive_kind, read off the task PixAI stored), one per task -- not a
            # count of accepted submits (owner 2026-10-02).
            m["edits"] = _scalar(
                "SELECT COUNT(DISTINCT task_id) FROM catalog WHERE derive_kind = 'edit' "
                "AND source IN ('api','local') AND COALESCE(task_id,'') != ''")
            # Seven Candles (gen_streak): the best run of consecutive LOCAL days with an in-app
            # generation, from PixAI's own timestamps on the rows rather than a day ledger.
            m["gen_streak"] = _telemetry._best_day_streak([
                d for (d,) in con.execute(
                    "SELECT DISTINCT date(created_at, 'localtime') FROM catalog "
                    "WHERE source IN ('api','local') AND COALESCE(created_at,'') != ''")
                if d])
            # Mirror Seed (palindrome_seeds): distinct numeric-palindrome seeds of >=5 digits.
            # COUNT ONLY -- no seed value is ever emitted.
            pal = set()
            for (seed,) in con.execute(
                    "SELECT DISTINCT seed FROM catalog WHERE COALESCE(seed,'') != ''"):
                s = str(seed or "").lstrip("-")
                if len(s) >= 5 and s.isdigit() and s == s[::-1]:
                    pal.add(s)                              # dedupe '12321' vs '-12321'
            m["palindrome_seeds"] = len(pal)
            # Watchword (top_word_uses): uses of the single most-common prompt word, via the
            # shared /health word cloud. COUNT ONLY -- the word itself never leaves.
            _wc = _prompt_word_counter(con.execute(
                "SELECT prompt_preview FROM catalog "
                "WHERE COALESCE(prompt_preview,'') != ''"))
            m["top_word_uses"] = _wc.most_common(1)[0][1] if _wc else 0
        except sqlite3.Error:
            for k in ("models", "published", "tagged", "local_gens",
                      "gens_in_a_day", "distinct_keywords",
                      "rated", "loras_distinct", "palindrome_seeds", "top_word_uses",
                      "lora_used", "lora_stacked", "lora_distinct", "edits", "gen_streak"):
                m.setdefault(k, 0)
    return m


_TIER_POINTS = {"common": 5, "rare": 10, "epic": 25, "legendary": 50, "feat": 0}

# PLAIN WORDS FOR WHAT A LADDER COUNTS (owner walk 2026-09-29). The Folio's ladder headers read
# "<track> — measured in <metric>", and the metric is the roster's own key: "images" reads fine,
# "local_gens" is a code name on screen. Every metric a ladder track uses has its words here,
# sent on each track as `metric_words`; a metric this list does not know yet (a roster that grows
# a track before this does) falls back to its key with the underscores spaced out, so no header
# can ever show one. dev/tests/test_achievements.py holds every live track to an entry here.
LADDER_METRIC_WORDS = {
    "images": "images",
    "videos": "videos",
    "local_gens": "pictures made in the app",
    "collections": "collections",
    "models": "models used",
    "tagged": "tagged pictures",
    "published": "published pictures",
    "edits": "edits",
    "culled": "pictures deleted",
    "days_used": "days you opened the app",
    "rated": "rated pictures",
    "loras_trained": "LoRAs trained",
    "contest_entries": "contest entries",
    "jobs_concurrent": "jobs running at once",
    "loras_distinct": "different LoRAs used",
    "distinct_active_days": "days you made or sorted pictures",
}


def metric_words(metric):
    """What a ladder's metric counts, in words a person reads (never a code name)."""
    m = str(metric or "")
    return LADDER_METRIC_WORDS.get(m) or " ".join(m.replace("_", " ").split())


def _build_ach_rung(roster):
    """Rung = the ordinal step within a ladder family. A ladder family = the
    bucket=='ladder' achievements that share a metric, ordered by threshold;
    non-ladder (milestone/mastery) achievements are rung 1. Derived (not a
    hand-kept field) so it reproduces the owner's Archive ladder exactly
    (5/15/35/65/70). Shared metrics stay safe: milestone/feat entries that reuse
    a metric are NOT bucket=='ladder', so they never join the family."""
    fam = {}
    for a in roster:
        if a.get("bucket") == "ladder":
            fam.setdefault(a["metric"], []).append(a)
    rung = {}
    for members in fam.values():
        for i, a in enumerate(sorted(members, key=lambda x: x["threshold"]), 1):
            rung[a["id"]] = i
    return rung


# The rung map is derived from the sealed roster once per load; read via _ach_rung().


def achievement_points(a):
    """Rung-scaled score for one achievement: tier base + 5*(rung-1). Feats score
    0 by design (pure bragging-rights flair), so the points total never reveals a
    masked feat."""
    if a.get("tier") == "feat":
        return 0
    return _TIER_POINTS.get(a.get("tier"), 0) + 5 * (_ach_rung().get(a["id"], 1) - 1)


# Closed-universe set achievements -> a per-criterion checklist (WHICH members are done),
# not just an N/M count. Maps achievement id -> (telemetry set key, ordered
# [(member, label)] universe). ONLY closed sets belong here; open-ended distinct-counts
# (loras, enhance_workflows) have no finite universe and stay count-only. `video_modes`
# tracks only i2v/flf/r2v (V2V is deliberately not counted -- see the loom/generate bump).
# The closed-set criteria labels are SEALED in the container too; read via _ach_criteria()
# -> {aid: [set_key, [[member, label], ...]]} (JSON tuples arrive as lists, unpacked below).


def achievement_criteria(sets):
    """For each closed-universe set achievement, which of its criteria are met. `sets` =
    telemetry.json's 'sets' block (id -> list of members). Returns
    {achievement_id: [{"key","label","done"}, ...]}. Pure + fail-soft: a missing or
    non-list set reads as 'nothing done' rather than raising."""
    out = {}
    for aid, (set_key, universe) in _ach_criteria().items():
        have = sets.get(set_key) if isinstance(sets, dict) else None
        have = set(have) if isinstance(have, list) else set()
        out[aid] = [{"key": k, "label": lbl, "done": k in have} for k, lbl in universe]
    return out


def compute_achievements(metrics, seen=(), sets=None, earned_at=None):
    """Pure: given the metric bundle + the set of already-seen achievement ids,
    return {achievements, skins, newly}. An achievement is *earned* when its metric
    reaches the threshold; a skin is *earned* if it's free or any earned achievement
    unlocks it. `newly` = earned-but-not-yet-seen (drives the one-shot unlock toast).

    PIN-ONCE (#37, owner: "a Failure -- Colossal"): `earned_at` is the stamped
    id->date record from achievements.json, and any id present in it stays earned
    even when its live metric has since dropped below the threshold. Catalog-count
    metrics are snapshots, not counters -- the web Duplicate Review's last-copy
    delete (quarantine_duplicate_file -> delete_from_catalog) and every real bulk
    delete shrink them, and before this pin an earned badge visibly un-earned in
    the Folio after a prune. The record is append-only or it isn't a record.
    Callers that render or GATE on earned-ness must pass it; omitting it (pure
    metric tests) keeps the old live-threshold behavior.

    Two metrics are self-referential and resolved in post-passes here (they cannot
    be a metrics.get() lookup): skins_unlocked (Skin Changer) counts the skins this
    very computation unlocked, and all_non_feat_earned (Completionist) requires
    every non-feat, non-banner achievement to be earned."""
    seen = set(seen or [])
    pinned = set(earned_at or ())
    metrics = dict(metrics or {})
    # per-criterion checklists for the closed-universe set achievements (only when the
    # caller supplies the raw telemetry sets; tests that pass metrics-only skip it)
    crit = achievement_criteria(sets) if sets is not None else {}
    earned_skins = set()
    achs = []
    for a in _roster():
        cur = int(metrics.get(a["metric"], 0) or 0)
        earned = cur >= a["threshold"] or a["id"] in pinned
        if earned and a.get("skin"):
            earned_skins.add(a["skin"])
        entry = {
            "id": a["id"], "name": a["name"], "icon": a["icon"], "desc": a["desc"],
            "tier": a["tier"], "metric": a["metric"], "threshold": a["threshold"],
            "current": cur, "earned": earned, "skin": a.get("skin", ""),
            "bucket": a.get("bucket", "ladder"), "hidden": bool(a.get("hidden")),
            "banner_reward": bool(a.get("banner_reward")), "points": achievement_points(a),
            "roast": a.get("roast", ""), "roast_nsfw": a.get("roast_nsfw", ""),
        }
        if a.get("bucket") == "ladder":
            entry["track"] = a["track"]
            entry["rung"] = a["rung"]
            entry["rungs_total"] = a["rungs_total"]
        if a["id"] in crit:
            entry["criteria"] = crit[a["id"]]
        achs.append(entry)
    by_id = {x["id"]: x for x in achs}
    # Generic `requires` meta-loop (Glories of the Curator/Forgewright + The Way Is Shut):
    # an achievement carrying a `requires` prereq list earns when every prereq id is earned
    # (or it is pin-once). Iterates the SEALED roster -- which carries `requires` -- rather
    # than the built entries, which deliberately never copy it, so no prereq list ever
    # reaches the payload/client. `current` reflects how many prereqs are met (for a masked
    # feat this stays cloaked until earned anyway).
    #
    # A FIXED POINT, and ABOVE the two post-passes -- both of those matter:
    #   * it used to read ONE `earned_ids` snapshot taken before the loop, so a meta whose
    #     prereq is ITSELF a meta could never earn: the prereq earned during the same pass
    #     and the snapshot never heard about it. Iterating until nothing new earns is what
    #     makes a chain of any depth resolve.
    #   * it used to run AFTER Skin Changer and Completionist, so a skin granted by a meta
    #     was invisible to Skin Changer count, and a meta earned here never counted toward
    #     Completionist "everything earned". Resolving first means both post-passes see the
    #     finished picture.
    # Bounded by construction: a round can only ADD earns, so it converges in at most one
    # pass per requires-carrying achievement.
    _reqs = [a for a in _roster() if a.get("requires")]
    for _ in range(len(_reqs) + 1):
        earned_ids = {x["id"] for x in achs if x["earned"]}
        changed = False
        for a in _reqs:
            e = by_id.get(a["id"])
            if e is None:
                continue
            req = a["requires"]
            met = sum(1 for r in req if r in earned_ids)
            e["current"] = met
            was = e["earned"]
            e["earned"] = (met == len(req)) or e["id"] in pinned
            if e["earned"] and a.get("skin"):
                earned_skins.add(a["skin"])
            if e["earned"] and not was:
                changed = True
        if not changed:
            break
    # post-pass: Skin Changer counts unlocked skins (free ones + this pass's earns)
    sc = by_id.get("skin-changer")
    if sc:
        n = sum(1 for s in _skins() if s.get("free") or s["id"] in earned_skins)
        sc["current"] = n
        sc["earned"] = n >= sc["threshold"] or sc["id"] in pinned
    # post-pass: Completionist = every non-feat, non-banner achievement earned
    comp = by_id.get("completionist")
    if comp:
        pool = [x for x in achs if x["tier"] != "feat" and not x["banner_reward"]]
        done = sum(1 for x in pool if x["earned"])
        comp["current"] = 1 if done == len(pool) else 0
        comp["earned"] = done == len(pool) or comp["id"] in pinned
    skins = [{"id": s["id"], "name": s["name"], "desc": s["desc"],
              "earned": bool(s.get("free")) or s["id"] in earned_skins,
              "unlock": _skin_unlock().get(s["id"])}
             for s in _skins()]
    newly = [a["id"] for a in achs if a["earned"] and a["id"] not in seen]
    earned_points = sum(x["points"] for x in achs if x["earned"])
    possible_points = sum(x["points"] for x in achs)
    # Each track also carries its metric in plain words, for the Folio's "measured in" header
    # (copies: the sealed defs are cached and shared, never written into).
    ladders = [dict(t, metric_words=metric_words(t.get("metric"))) if isinstance(t, dict) else t
               for t in _ladder_tracks()]
    return {"achievements": achs, "skins": skins, "ladders": ladders, "newly": newly,
            "earned_points": earned_points, "possible_points": possible_points}


# THE METRICS THIS SERVER MEASURES THAT A FRESH INSTALL DOES NOT YET HOLD A KEY FOR. The bundle
# behind /api/achievements is open-ended: a telemetry counter, maximum or flag exists in it only
# once something has bumped it, so "the key is absent" cannot tell "measured, and still zero"
# from "a metric nobody counts". The first is a true 0-of-N; only the second shows no count.
# Every name below is one code in this app bumps (telem_bump / telem_max), plus the metrics
# compute_achievements() resolves ITSELF in a post-pass (Skin Changer counts the skins that very
# computation unlocked). Feat metrics are deliberately NOT listed: achievement_progress refuses
# a feat before it ever reads this set. dev/tests/test_achievement_progress.py pins that every
# non-feat metric in the sealed roster is either in the bundle or here, so a new honor added
# without its metric being declared fails a test instead of silently losing its count.
_MEASURED_METRICS = frozenset({
    "claims", "enhances", "free_cards_applied", "jobs_concurrent",
    "organize_runs", "similar_uses",
    "skin_changed_runs", "storyboards", "uploads",
    "skins_unlocked",
})
# (edits, culled, the LoRA counts and loras_trained left this list on 2026-10-02: they are
# counted from evidence now -- the catalog, or a set telemetry_metrics always measures -- so
# every bundle carries them, a fresh install's as a true 0.)


def achievement_progress(entry, metrics):
    """The "N to go" numbers for ONE unearned achievement entry (Folio for completionists, O1),
    or None when there is nothing true to say:

        {"current": int, "threshold": int, "left": int, "fraction": float}

    `left` is threshold - current from the server's own metric, never negative; `fraction` is
    current / threshold clamped to [0, 1] -- the true fraction the moon gauge draws.

    NONE for every case that must show no count, no moon and no pin:
      * a FEAT of any kind (tier or bucket feat, or a meta): feats leak nothing (Session G), so
        this function refuses them by construction rather than trusting a caller to skip them;
      * an entry already earned (there is nothing to go);
      * a metric this server does not measure (neither in the bundle nor in _MEASURED_METRICS --
        compute_achievements reads a missing metric as 0, which would draw a false "N to go"
        from a metric nobody counts);
      * a threshold that is not a positive whole number.
    Pure: it reads the entry and the metric bundle it is handed."""
    if not isinstance(entry, dict) or entry.get("earned"):
        return None
    if entry.get("tier") == "feat" or entry.get("bucket") in ("feat", "meta"):
        return None
    metric = entry.get("metric")
    if not isinstance(metrics, dict) or (
            metric not in metrics and metric not in _MEASURED_METRICS):
        return None
    try:
        threshold = int(entry.get("threshold") or 0)
        current = int(entry.get("current") or 0)
    except (TypeError, ValueError):
        return None
    if threshold <= 0 or current < 0:
        return None
    return {"current": current, "threshold": threshold,
            "left": max(0, threshold - current),
            "fraction": min(1.0, current / threshold)}


def claim_job_label(claimed, credits):
    """The activity-tracker line for a successful claim.

    Credits are the headline when there are any -- "+1,200 credits claimed" -- because
    that is the number the owner came to see, grouped the same way every other figure in
    the tracker is. A claim can also be worth zero credits (a stamina-only reward is
    still a real claim), and "+0 credits claimed" would read as a bug rather than a
    fact, so that case counts the rewards instead."""
    try:
        credits = int(credits or 0)
    except (TypeError, ValueError):
        credits = 0
    if credits > 0:
        return "+{:,} credits claimed".format(credits)
    n = max(1, int(claimed or 1))
    return "{} reward{} claimed".format(n, "" if n == 1 else "s")


def _ach_state_path(out_dir):
    return _paths.records_path(out_dir, "achievements.json")


def load_ach_state(out_dir):
    """Persisted cosmetic state: {seen:[ids already toasted], skin:'active id',
    earned_at:{id: iso-date}}. Fails soft to an empty default so a missing/corrupt
    file never breaks a page."""
    try:
        d = json.loads(_ach_state_path(out_dir).read_text(encoding="utf-8"))
        seen = [s for s in (d.get("seen") or []) if isinstance(s, str)]
        # Preserve the stored skin id verbatim -- do NOT coerce it to the default
        # just because it isn't in the CURRENT _skin_ids(). That set comes from the
        # sealed container, so during an undressed window (the pack still
        # downloading, or briefly unreadable) it collapses to the two free skins;
        # coercing here would rewrite a legitimately-earned skin to "moonglade" and
        # the next save_ach_state would PERSIST that reset -- permanent loss for a
        # purely cosmetic value the container has nothing to do with. Every skin's
        # CSS is hard-coded server-side (html[data-skin=...]) and applied client-
        # side, so an id we can't validate right now still renders correctly; a
        # genuinely unknown id just renders the default tokens, harmlessly. The
        # write gate (/api/skin: earned + known) is what refuses a bogus/locked
        # skin -- read is trust, write is checked. (Adversarial M1, 2026-08-22.)
        skin = d.get("skin") if isinstance(d.get("skin"), str) and d.get("skin") else "moonglade"
        earned_at = {k: v for k, v in (d.get("earned_at") or {}).items()
                     if isinstance(k, str) and isinstance(v, str)}
        return {"seen": seen, "skin": skin, "earned_at": earned_at}
    except (OSError, ValueError):
        return {"seen": [], "skin": "moonglade", "earned_at": {}}


def save_ach_state(out_dir, state):
    """Persist {seen, skin, earned_at} atomically-ish. Best-effort; swallows write errors."""
    try:
        _ach_state_path(out_dir).write_text(
            json.dumps({"seen": sorted(set(state.get("seen") or [])),
                        "skin": state.get("skin", "moonglade"),
                        "earned_at": state.get("earned_at") or {}}, indent=2),
            encoding="utf-8")
        return True
    except OSError:
        return False


def badge_cache_dir(out_dir=None):
    """Where the regenerable badge-thumb cache lives: local/cache/badges/. OUTSIDE the coded
    branding tree on purpose (SCOPE_bundle-v2-branding constraint 3: the tree must keep
    reading as the empty slot scaffold -- a folder of PNGs named by achievement id beside the
    coded folders published the sealed roster's own contents to anyone who opened it), and
    outside every library: the thumbs are cut from the art pack, identical for any library,
    so they live with the install that has the pack. local/cache/ is the general home for
    rebuildable caches; add siblings beside badges/, not elsewhere. (`out_dir` is accepted
    and unused.)"""
    return _paths.cache_dir() / "badges"


def _badge_thumb(out_dir, aid, size=256):
    """Lazily cache a ~size px copy of a badge master and return its Path (or PNG bytes when the cache dir can't be written). The 57
    badge masters are 2000px (~300 MB total); the Folio of Honors renders these thumbs so
    a full open doesn't pull the masters. Masters stay the source of truth; the cache
    self-heals when a master is re-cut (mtime check). Falls back to the master on any
    trouble, so a tile always resolves to *something*. Cache home: badge_cache_dir().

    NEVER LARGER THAN THE SOURCE: `size` is a ceiling, not a target. Pillow's thumbnail()
    only ever shrinks, so a master smaller than the size asked (the toast's 384 against a
    smaller drop-in) is served at its own size, never blown up; keep it that way in both
    cuts below rather than resizing to `size` (dev/tests/test_badge_anim.py holds it)."""
    from moonglade.gallery import (_branding_bytes, _branding_exists, _branding_mtime, _role_dir,
                                   _role_rel)
    rel = _role_rel("badges", aid + ".png")
    if not _branding_exists(rel):
        return None
    src = _role_dir("badges") / (aid + ".png")
    dst = badge_cache_dir(out_dir) / ((aid + ".png") if size == 256 else (aid + "." + str(size) + ".png"))
    src_mtime = _branding_mtime(rel)   # loose master's own mtime, or the container file's
    try:
        if dst.is_file() and src_mtime is not None and dst.stat().st_mtime >= src_mtime:
            return dst
        raw = _branding_bytes(rel)
        if raw is None:
            return None
        dst.parent.mkdir(parents=True, exist_ok=True)
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im.thumbnail((size, size))
        im.save(dst)
        return dst
    except Exception:
        if src.is_file():
            return src         # loose master exists -- serve it full-size
        # Container-sourced master AND a cache we couldn't write (unwritable dir,
        # read-only mount, full disk): don't fall through to a 404 -> emoji. Hand
        # bytes back for the route to serve from memory -- resized if PIL can, else
        # the raw master (adversarial-review 2026-08-22).
        raw = _branding_bytes(rel)
        if raw is None:
            return None
        try:
            import io
            from PIL import Image
            im = Image.open(io.BytesIO(raw))
            im.thumbnail((size, size))
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            return raw


# An ANIMATED badge master is a `<id>.webp` dropped beside the stills in the badges
# role -- the same "drop it in and it moves" move the toast mascot already takes
# (notify/ach.js's mascot chain). It is served THROUGH, byte-for-byte, never down a
# PIL path: measured here on Pillow 12.2.0, reading an animated webp hands back every
# frame but reports each frame's `duration` as None (the masters carry a real 66 ms in
# their ANMF chunks), so a re-encode silently invents the cadence the art was authored
# at -- and re-compresses the artist's chroma-keyed alpha on top of it. Pass-through
# keeps frames, timing, loop count and alpha exactly as made. The still-PNG path below
# is untouched by any of this: a badge with no .webp beside it serves exactly as before.
#
# The cap is the one thing pass-through has to bring of its own, since nothing is being
# resized: an animated master is whole-file, and the ones banked for future feats run
# ~3-8 MB each. 12 MB clears those with headroom while still refusing something absurd;
# over the cap the .webp 404s and the client's chain falls back to the still thumb.
_BADGE_ANIM_MAX_BYTES = 12 * 1024 * 1024


def _badge_anim(aid):
    """The animated master's bytes for `aid`, or None when there isn't one (no
    `<id>.webp` in the badges role, unreadable, or over _BADGE_ANIM_MAX_BYTES).
    None is the fallback signal, not an error: the route 404s and the client's
    webp-first chain drops to the still `<id>.png` thumb. Reads through
    _branding_bytes(), so a loose master wins over the container's, same as the
    stills. NO cache entry: there is no derived artefact to cache -- the bytes
    served ARE the master."""
    from moonglade.gallery import _branding_bytes, _branding_exists, _role_rel
    rel = _role_rel("badges", aid + ".webp")
    if not _branding_exists(rel):
        return None
    raw = _branding_bytes(rel)
    if raw is None or len(raw) > _BADGE_ANIM_MAX_BYTES:
        return None
    return raw
