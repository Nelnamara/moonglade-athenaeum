"""moonglade/narrator.py -- the narrator's poke ladder, as a PURE core.

The gallery's narrator can be poked. What that does is a slow ladder rather than a switch:
the server keeps a count and a set of clocks per signed-in account, decides whether a poke
counts, and chooses the line the client will show. The client only paints what it is told.

THIS MODULE HAS NO I/O AND READS NO CLOCK. `poke()` takes the instant as a parameter (a
float of epoch seconds for the gaps, and the local calendar day as a string), so a test can
walk a whole simulated fortnight without sleeping a second. The store that keeps a state
between calls, the route that carries it, and the earn through the achievement path all live
in moonglade/gallery.py.

WHAT THIS MODULE KNOWS is only the MECHANICS: how many pokes make a stage, how long apart two
counted pokes must be, what a day allows. It knows NO line of copy. Every line the narrator
speaks comes from the sealed pack (the `poke_lines` payload beside the achievement roster);
a pack with no line for something gets NEUTRAL, an ellipsis that names nothing. The pack's
shape is described at `clean_pools`.

The rules, in one place:

  * A poke COUNTS only when it is far enough after the last counted one: TWO seconds through
    the first stages ("spam does not count"), SEVEN minutes from stage five onward.
  * At the walk-off count she leaves until tomorrow: every poke that same local day is
    refused with the "walked off" pool.
  * In the fourth stage a day allows at most THREE counted pokes; the fourth is refused with
    the "daily cap" pool.
  * A poke that does not count STILL gets a line (so the person learns the rule) and never
    moves the count. Nothing ever resets the count.
  * The last counted poke is the FINAL STRAW: this module reports it and the caller supplies
    the words (they are an existing feat's own lines, not the ladder's).
  * A line is drawn at random from its pool, never the same one twice running.
"""
import hashlib
import random

# ---- the mechanics ------------------------------------------------------------------------
FINAL = 100                 # the count whose poke is the final straw
WALK_OFF_AT = 40            # she leaves for the day on this counted poke
SPAM_GAP_S = 2.0            # two counted pokes must be at least this far apart
SLOW_GAP_S = 7 * 60.0       # ... and from SLOW_FROM on, this far
SLOW_FROM = 61              # the first count that needs the slow gap
CAP_FROM, CAP_TO = 41, 60   # the counts a day allows only DAILY_CAP of
DAILY_CAP = 3
EYEROLL_P = 0.25            # the chance a counted poke in the eyeroll stage is an eyeroll
EYEROLL_STAGE = "threats"

# (name, first count, last count). The final straw is not a stage: it is FINAL.
STAGES = (
    ("oblivious", 1, 10),
    ("irritated", 11, 25),
    ("warning", 26, 40),
    ("seething", 41, 60),
    ("threats", 61, 85),
    ("breaking", 86, FINAL - 1),
)

# What a poke that names no line gets: public-safe, names nothing, is nobody's copy.
NEUTRAL = "…"

# Why a poke did not count -> the pool its line comes from.
DECLINES = ("spam", "walked_off", "daily_cap", "too_soon", "done")


def stage_of(count):
    """The stage name a counted poke NUMBER falls in ("" when it is in none: 0, or FINAL and
    beyond)."""
    for name, lo, hi in STAGES:
        if lo <= count <= hi:
            return name
    return ""


def new_state():
    """A fresh account's ladder. `count` is counted pokes so far; `last_at` the epoch second
    of the last counted one; `day`/`day_n` the local day and how many capped-stage pokes it
    has counted; `walked` the day she walked off; `last` the id of the last line spoken;
    `once` the ids of one-shot lines already spoken."""
    return {"v": 1, "count": 0, "last_at": None, "day": "", "day_n": 0,
            "walked": "", "last": "", "once": []}


def clean_state(raw):
    """A state read from disk, made safe: anything missing or the wrong type falls back to a
    fresh value for THAT field (a hand-edited or torn file must never crash a poke)."""
    st = new_state()
    if not isinstance(raw, dict):
        return st
    c = raw.get("count")
    if isinstance(c, int) and not isinstance(c, bool) and c >= 0:
        st["count"] = min(c, FINAL)
    la = raw.get("last_at")
    if isinstance(la, (int, float)) and not isinstance(la, bool):
        st["last_at"] = float(la)
    for k in ("day", "walked", "last"):
        if isinstance(raw.get(k), str):
            st[k] = raw[k][:32]
    dn = raw.get("day_n")
    if isinstance(dn, int) and not isinstance(dn, bool) and dn >= 0:
        st["day_n"] = min(dn, 1000)
    once = raw.get("once")
    if isinstance(once, list):
        st["once"] = [o for o in once if isinstance(o, str)][:256]
    return st


# ---- the sealed pack's lines ---------------------------------------------------------------
def line_id(text):
    """A short stable id for a line, so state can say "that one" without keeping its words."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def _entry(raw):
    """One pool entry -> (text, lo, hi, once, id), or None. An entry is a string, or an object
    {"t": text, "from": n, "to": n, "once": bool}: `from`/`to` bound the counted-poke number the
    line may answer (either may be left off), `once` lets it be spoken a single time."""
    if isinstance(raw, str):
        text, lo, hi, once = raw, 1, FINAL, False
    elif isinstance(raw, dict) and isinstance(raw.get("t"), str):
        text = raw["t"]
        lo, hi = raw.get("from"), raw.get("to")
        lo = lo if isinstance(lo, int) and not isinstance(lo, bool) else 1
        hi = hi if isinstance(hi, int) and not isinstance(hi, bool) else FINAL
        once = raw.get("once") is True
    else:
        return None
    text = text.strip()
    if not text:
        return None
    return (text, lo, hi, once, line_id(text))


def clean_pools(raw):
    """The sealed `poke_lines` payload, made safe: {pool name: [entry, ...]}. The pack is
    {"stages": {stage: [...]}, "eyeroll": [...], "walk_off": [...], plus one list per decline
    reason ("spam", "walked_off", "daily_cap", "too_soon", "done")}. Anything that is not a
    list of well-formed entries is dropped rather than trusted."""
    pools = {}
    if not isinstance(raw, dict):
        return pools
    flat = dict(raw)
    flat.pop("choice", None)            # the final straw's words: see clean_choice
    stages = flat.pop("stages", None)
    if isinstance(stages, dict):
        for name, lst in stages.items():
            flat[str(name)] = lst
    for name, lst in flat.items():
        if not isinstance(lst, list):
            continue
        ents = [e for e in (_entry(x) for x in lst) if e is not None]
        if ents:
            pools[str(name)] = ents
    return pools


def _draw(pool, count, st, rng):
    """One line out of `pool` (a list of entries) for a poke answering `count`, or None.
    Honours the bounds and the one-shots, avoids the line spoken last, and records what it
    spoke on `st`."""
    if not pool:
        return None
    fits = [e for e in pool if e[1] <= count <= e[2] and not (e[3] and e[4] in st["once"])]
    if not fits:
        return None
    fresh = [e for e in fits if e[4] != st["last"]]
    text, _lo, _hi, once, lid = rng.choice(fresh or fits)
    st["last"] = lid
    if once and lid not in st["once"]:
        st["once"].append(lid)
    return text


def poke(state, now, today, pools, rng=None):
    """One poke. Returns (new_state, result); `state` is never mutated.

    now    epoch seconds -- the gaps are measured on this.
    today  the local calendar day as a string ("2026-09-29") -- the walk-off and the daily cap
           are measured on this. The caller picks the convention; this only compares.
    pools  clean_pools() of the sealed payload ({} for a pack with no lines).
    rng    a random.Random (a test seeds one); the module's own by default.

    result: {"line": str, "counted": bool, "count": int, "final": bool, "reason": str|None,
             "stage": str}. `count` is the count AFTER this poke. On the final straw `line`
    is "" -- the caller supplies the words. `reason` is why it did not count (one of
    DECLINES), or None when it did."""
    rng = rng or random
    st = clean_state(state)
    if st["day"] != today:
        st["day"], st["day_n"] = today, 0
    if st["walked"] and st["walked"] != today:
        st["walked"] = ""
    n = st["count"]

    def decline(reason):
        line = _draw(pools.get(reason), n, st, rng) or NEUTRAL
        return st, {"line": line, "counted": False, "count": n, "final": False,
                    "reason": reason, "stage": stage_of(n)}

    if n >= FINAL:
        return decline("done")
    nxt = n + 1
    if st["walked"] == today:
        return decline("walked_off")
    if CAP_FROM <= nxt <= CAP_TO and st["day_n"] >= DAILY_CAP:
        return decline("daily_cap")
    slow = nxt >= SLOW_FROM
    if st["last_at"] is not None:
        gap = now - st["last_at"]
        if gap < 0:
            # The clock went backwards (a hand-set clock, a restored machine). The stored
            # instant is from a future that has not happened: re-anchor on now and refuse this
            # one, rather than lock the account out until the wall clock catches up.
            st["last_at"] = now
            return decline("too_soon" if slow else "spam")
        if gap < (SLOW_GAP_S if slow else SPAM_GAP_S):
            return decline("too_soon" if slow else "spam")

    st["count"], st["last_at"] = nxt, now
    if CAP_FROM <= nxt <= CAP_TO:
        st["day_n"] += 1
    if nxt == WALK_OFF_AT:
        st["walked"] = today
    stage = stage_of(nxt)
    if nxt >= FINAL:
        return st, {"line": "", "counted": True, "count": nxt, "final": True,
                    "reason": None, "stage": "final"}
    line = None
    if stage == EYEROLL_STAGE and pools.get("eyeroll") and rng.random() < EYEROLL_P:
        line = _draw(pools["eyeroll"], nxt, st, rng)
    if line is None and nxt == WALK_OFF_AT:
        line = _draw(pools.get("walk_off"), nxt, st, rng)
    if line is None:
        line = _draw(pools.get(stage), nxt, st, rng)
    return st, {"line": line or NEUTRAL, "counted": True, "count": nxt, "final": False,
                "reason": None, "stage": stage}


CHOICE_FIELDS = ("title", "keep", "unleash", "foot")


def clean_choice(raw):
    """The sealed pack's words for the choice the final straw ends on, made safe:
    {title, keep, unleash, foot} with only the fields that are non-empty strings (each cut to
    200 characters). {} when the pack has none -- the page then uses its own plain wording."""
    out = {}
    if isinstance(raw, dict):
        for k in CHOICE_FIELDS:
            v = raw.get(k)
            if isinstance(v, str) and v.strip():
                out[k] = v.strip()[:200]
    return out
