"""moonglade/contest_qualify.py -- "have you used what this contest requires?"

A contest can require a model, a LoRA or a recipe (its `rules`, moonglade.backup._contest_rule;
gallery/src/lib/contestRules.js names them). The contest cards say, in one small line, whether
the required ones are ones you have generated with (owner's list, 2026-11-18).

WHAT "USED" CAN MEAN HERE, exactly:
  * The catalog records the model VERSION each picture was made with (`model_id`) and the LoRA
    versions (`lora_parameters`, [{versionId, weight}]). A contest names MODELS (its links go
    to pixai.art/model/<id>). So a rule id counts as used when it is itself one of those
    version ids, or when one of the model's versions is (PixAI's
    /generation-model/<id>/versions, read once per model and kept for a day).
  * Recipes are not recorded per picture, so a recipe rule is UNKNOWN -- never "not used".
  * A model whose versions could not be read is unknown too. An unknown never reads as "no".

Read-only. The version reads are paced and capped per answer (MAX_LOOKUPS) so a board with
many LoRA contests never turns one open of the Contests screen into a burst against PixAI.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time

VERSIONS_TTL_S = 24 * 3600.0
MAX_LOOKUPS = 24
LOOKUP_PAUSE_S = 0.25

KINDS = {"required_model_ids": ("model", "model_ids"),
         "required_lora_ids": ("LoRA", "lora_ids"),
         "required_recipe_ids": ("recipe", "recipe_ids")}

_cache = {}                     # model id -> (at, frozenset(version ids))
_lock = threading.Lock()

# The map also lives in local/cache/contest_model_versions.json (through moonglade.paths, written
# the way the contest board's cache is: atomic), so a restart does not repeat up to 24 paced reads.
# Loaded at first use of a given folder; every entry keeps its own saved time and the same TTL.
STORE_NAME = "contest_model_versions.json"
_STORE_VERSION = 1
_loaded_from = None             # the file the memory map was last loaded from


def _store_path():
    from moonglade import paths as _paths
    return _paths.cache_dir() / STORE_NAME


def _load_store():
    """Merge the saved map into memory once per file. Anything unreadable is just an empty map
    (the reads come back, the file is rebuilt)."""
    global _loaded_from
    path = str(_store_path())
    with _lock:
        if _loaded_from == path:
            return
        _loaded_from = path
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            models = data.get("models") if (isinstance(data, dict)
                                            and data.get("v") == _STORE_VERSION) else None
            for mid, ent in (models if isinstance(models, dict) else {}).items():
                if (isinstance(ent, dict) and isinstance(ent.get("versions"), list)
                        and isinstance(ent.get("at"), (int, float))):
                    _cache.setdefault(str(mid), (float(ent["at"]),
                                                 frozenset(str(v) for v in ent["versions"])))
        except (OSError, ValueError):
            pass


def _save_store(now=None):
    """Write the in-date entries (an old one is dropped here) atomically; a failed write is
    logged by the writer and never fails the answer."""
    from moonglade import contests as _contests
    now = time.time() if now is None else now
    with _lock:
        models = {mid: {"at": at, "versions": sorted(vs)} for mid, (at, vs) in _cache.items()
                  if now - at < VERSIONS_TTL_S}
    _contests._save_contest_cache(str(_store_path()), {"v": _STORE_VERSION, "models": models})


def used_version_ids(db_path):
    """Every model and LoRA version id the catalog's pictures were made with."""
    out = set()
    try:
        con = sqlite3.connect("file:%s?mode=ro" % str(db_path).replace("\\", "/"), uri=True)
    except sqlite3.Error:
        return out
    try:
        for (mid,) in con.execute(
                "SELECT DISTINCT model_id FROM catalog WHERE COALESCE(model_id,'') != ''"):
            out.add(str(mid).strip())
        for (raw,) in con.execute(
                "SELECT DISTINCT lora_parameters FROM catalog "
                "WHERE COALESCE(lora_parameters,'') NOT IN ('', '[]')"):
            try:
                items = json.loads(raw)
            except (TypeError, ValueError):
                continue
            for it in items if isinstance(items, list) else []:
                vid = it.get("versionId") if isinstance(it, dict) else None
                if vid not in (None, ""):
                    out.add(str(vid).strip())
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return out


def cached_versions(model_id, now=None):
    now = time.time() if now is None else now
    _load_store()
    with _lock:
        hit = _cache.get(str(model_id))
    if hit and now - hit[0] < VERSIONS_TTL_S:
        return hit[1]
    return None


def remember_versions(model_id, versions, now=None, save=True):
    _load_store()
    with _lock:
        _cache[str(model_id)] = (time.time() if now is None else now, frozenset(versions))
    if save:
        _save_store(now)


def rule_status(rule, used, versions_of):
    """{kind, need, used, unknown} for one rule. `versions_of(id)` returns the model's version
    ids, or None when they are not known (not read, or the read failed)."""
    rule = rule if isinstance(rule, dict) else {}
    kind, key = KINDS.get(str(rule.get("type") or ""), (None, None))
    if kind is None:
        key = next((k for k in rule if isinstance(k, str) and k.endswith("_ids")
                    and isinstance(rule[k], list)), None)
        kind = "item"
    ids = [str(i) for i in (rule.get(key) or []) if i not in (None, "")] if key else []
    st = {"kind": kind, "need": len(ids), "used": 0, "unknown": 0}
    if kind in ("recipe", "item"):
        st["unknown"] = len(ids)
        return st
    for i in ids:
        if i in used:
            st["used"] += 1
            continue
        vs = versions_of(i)
        if vs is None:
            st["unknown"] += 1
        elif used.intersection(vs):
            st["used"] += 1
    return st


def qualify(contests, used, versions_of):
    """{contest id: [rule_status, ...]} for every contest with rules."""
    out = {}
    for c in contests or []:
        rules = [r for r in (c.get("rules") or []) if isinstance(r, dict)]
        if rules and c.get("id"):
            out[str(c["id"])] = [rule_status(r, used, versions_of) for r in rules]
    return out


def model_version_ids(core, session, model_id):
    """The version ids PixAI lists for one model. Raises on a failed read (list_model_versions
    answers [] for that, which would read as "a model with no versions")."""
    data = core._rest_get(session, "/generation-model/" + str(model_id) + "/versions")
    rows = data if isinstance(data, list) else (data or {}).get("data") or []
    return {str(r.get("id")) for r in rows if isinstance(r, dict) and r.get("id")}


def board_qualify(core, session, contests, db_path, sleep=time.sleep, now=None):
    """The answer /api/contests/qualify serves: reads what it must (capped, paced), then
    `qualify` with whatever is known."""
    used = used_version_ids(db_path)
    lookups = 0
    learned = []

    def versions_of(model_id):
        nonlocal lookups
        hit = cached_versions(model_id, now)
        if hit is not None:
            return hit
        if lookups >= MAX_LOOKUPS:
            return None
        if lookups:
            sleep(LOOKUP_PAUSE_S)
        lookups += 1
        try:
            vs = model_version_ids(core, session, model_id)
        except Exception:                    # noqa: BLE001 -- unknown, never "not used"
            return None
        remember_versions(model_id, vs, now, save=False)
        learned.append(model_id)
        return frozenset(vs)

    out = qualify(contests, used, versions_of)
    if learned:
        _save_store(now)                     # once per answer, not once per read
    return out
