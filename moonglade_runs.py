"""moonglade_runs.py -- Session M (Generate power tools): the prompt template, the Runs store,
the Inspector's secret stripping and Copy as CLI.

WHAT A RUN IS. A send of more than one generation from the Generate dock: a plain batch x2-4
(one task, N images), a Random run (one task per image, each with its own drawn values) or a
Matrix run (one task per combination, hard cap 24). Every one of them opens ONE confirm with
the server's own quote (DECISIONS 2026-09-28, "Every multi-send confirms once"), and the
server re-expands, re-builds and re-quotes everything itself before a single job goes out.
The design, its guard order and its adversarial review:
moonglade-internal/design/notes/generate-power-tools/BUILD-w5-m.md.

This module is the pure half and the store:

  parse / plan_jobs / escape_literal   the template syntax (NOTES 1, as the S1 ruling reads
                                       it): `{a|b|c}` inline, `__name__` a saved list, a
                                       brace group with no `|` literal, a backslash
                                       dropped only where it changes the parse.
                                       The dock's gallery/src/gen/templateCore.js is the same
                                       rule in JS; tests/fixtures/template_vectors.json pins
                                       both to one set of answers, so the preview the dock
                                       draws is the set of jobs the server sends.
  run_digest                           what the acknowledgement is checked against.
  RunsStore                            runs.db beside catalog.db: a run's template, vars,
                                       each job's state and the exact request it sent.
  strip_secrets                        what the Inspector may show (NOTES 7).
  cli_command                          Copy as CLI: the REAL command and flags (Settled 1).

Nothing here talks to PixAI. The sender is moonglade_backup.send_run (the spend choke), and
the routes are moonglade_gallery's /api/generate/plan, /run, /runs/<id> and /request/<id>.
"""
import hashlib
import json
import os
import re
import shlex
import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import moonglade_paths as _paths

# ---------------------------------------------------------------------------------------
# The template (NOTES 1, page M1 + M6)
# ---------------------------------------------------------------------------------------

MAX_VARS = 8                  # variables in one prompt
MAX_OPTIONS = 64              # options in one inline variable
CELL_CAP = 24                 # matrix cells (page M6: the hard cap)
MAX_COUNT = 4                 # Random / plain batch: x1-4
RUN_SEED_MAX = 2147483646     # the run seed's range, 0..RUN_SEED_MAX (prefillFromRun's space)
SEED_MOD = 2147483647         # image seed of Random job k: (run_seed + k) % SEED_MOD
_BIG = 1000000                # above this the over-cap message stops counting

LISTS_KEY = "gen.lists"       # the account store key the Lists sheet writes: {name: [items]}
LIST_NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")
MAX_LISTS = 50
MAX_LIST_ITEMS = 200
LIST_ITEM_MAX = 200

_LIST_TOKEN_RE = re.compile(r"__([a-z0-9_]+)__")

# What an option and a list item are trimmed of (review N5): ONE explicit set, the same in
# templateCore.js, because Python's str.strip() and JS's String.trim() disagree (JS keeps
# U+0085 and U+001C-U+001F, Python keeps U+FEFF). It is the union of the two.
TRIM_CHARS = ("\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f \x85\xa0 "
              "           "
              "    　﻿")


def trim(text):
    return str(text).strip(TRIM_CHARS)


# The refusals, word for word (BUILD-w5-m s1.2). The dock paints the same sentences peach.
ERR_UNCLOSED = "Unclosed or nested brace. Nesting isn’t supported."
ERR_EMPTY = "Empty variable."
ERR_TOO_MANY_VARS = "Up to {} variables in one prompt.".format(MAX_VARS)
ERR_TOO_MANY_OPTS = "Up to {} options in one variable.".format(MAX_OPTIONS)


def err_unknown_list(token):
    return "No list named {}.".format(token)


def err_empty_list(token):
    return "The list {} is empty.".format(token)


def err_long_list(token):
    return ("The list {} is too long — up to {} items of up to {} characters."
            .format(token, MAX_LIST_ITEMS, LIST_ITEM_MAX))


def err_duplicate(token, value):
    return ("{} has ‘{}’ twice — a matrix would pay for the same cell twice."
            .format(token, value))


def err_blank_cell(n):
    return "Cell {}’s prompt is empty.".format(n)


def err_over_cap(product):
    if product > _BIG:
        return ("More than a million combinations is over the {}-cell cap — narrow an "
                "axis.".format(CELL_CAP))
    return "{:,} combinations is over the {}-cell cap — narrow an axis.".format(
        product, CELL_CAP)


def clean_list(items):
    """A saved list's items as the expander uses them: each trimmed, blank lines dropped.
    None when the value is not a list of strings or breaks the bounds (the Lists sheet
    refuses the same when it saves; a list that breaks them anyway is refused, never cut)."""
    if not isinstance(items, list):
        return None
    out = []
    for it in items:
        if not isinstance(it, str):
            return None
        t = trim(it)
        if not t:
            continue
        if len(t) > LIST_ITEM_MAX:
            return None
        out.append(t)
    if len(out) > MAX_LIST_ITEMS:
        return None
    return out


def lists_from_prefs(prefs):
    """The account's saved lists out of its prefs document ({name: raw items}); names that
    break the charset are skipped (they can never be written by a token anyway)."""
    raw = (prefs or {}).get(LISTS_KEY)
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if LIST_NAME_RE.match(str(k))}


def _brace_structure(s):
    """The raw brace structure of `s`, every backslash ignored: ({open: close} for each
    matched pair, {open: the enclosing open or None}, [the opens left unclosed]). Inside a
    matched pair every `{` is matched too (a `}` closes the innermost open), so a pair's
    contents are fully nested pairs."""
    stack, pairs, parent = [], {}, {}
    for i, c in enumerate(s):
        if c == "{":
            parent[i] = stack[-1] if stack else None
            stack.append(i)
        elif c == "}" and stack:
            pairs[stack.pop()] = i
    return pairs, parent, stack


def _pair_shape(s, o, c, pairs):
    """(has a top-level `|`, holds a nested pair) for the pair (o, c)."""
    i, pipe, child = o + 1, False, False
    while i < c:
        ch = s[i]
        if ch == "{":
            child = True
            i = pairs[i] + 1
            continue
        if ch == "|":
            pipe = True
        i += 1
    return pipe, child


def _template_marks(s):
    """Where the template rule acts (the orchestrator's S1 ruling, BUILD-w5-m "Rulings"):
    groups {open: (kind, close)} for every pair holding a top-level `|` -- "live" (a
    variable), "escaped" (its `{` or `}` has a backslash before it: literal, that backslash
    dropped) or "nested" (refused: it sits in another pair or holds one); `consume`, the
    backslash positions dropped; `bad_open`, the unclosed `{` with a `|` after it and no
    backslash (refused -- it looks like an intended variable). Every other brace is literal
    text and every other backslash stays."""
    pairs, parent, unclosed = _brace_structure(s)
    groups, consume, bad_open = {}, set(), set()

    def esc(k):
        return k > 0 and s[k - 1] == "\\"

    for o, c in pairs.items():
        pipe, child = _pair_shape(s, o, c, pairs)
        if not pipe:
            continue
        if esc(o) or esc(c):
            groups[o] = ("escaped", c)
            if esc(o):
                consume.add(o - 1)
            if esc(c):
                consume.add(c - 1)
        elif child or parent.get(o) in pairs:
            groups[o] = ("nested", c)
        else:
            groups[o] = ("live", c)
    for u in unclosed:
        if "|" in s[u + 1:]:
            if esc(u):
                consume.add(u - 1)
            else:
                bad_open.add(u)
    return groups, consume, bad_open


def parse(template, lists=None):
    """Scan `template` left to right, once. Returns
        {"parts": [...], "vars": [...], "error": str|None, "syntax": bool}
    part = {"lit": text}                       literal, escapes already applied
         | {"var": token, "options": [...], "kind": "inline"|"list", "name"?: str}
         | {"bad": token, "error": msg}

    THE RULE (the orchestrator's S1 ruling, recorded in BUILD-w5-m's rulings; it deviates
    from the Handoff page's parser, which read every brace as syntax):
      * a `{...}` group is a VARIABLE only when it holds a top-level `|` -- `{a|b|c}`. A brace
        group with no `|` is literal text, sent exactly as typed, braces and all
        (`{masterpiece}`, `{{best quality}}`, `{}`);
      * `__name__` reads a saved list;
      * a backslash is dropped only where it changes the parse: before the `{` or `}` of a
        `|` group (that group is then literal), before an unclosed `{` that has a `|` after
        it, or before the `__` of a list token. Anywhere else it stays as typed, so
        `a\\_b` and a kaomoji's `\\_` reach PixAI unchanged;
      * an unclosed `{` or a stray `}` with no `|` group involved is literal; an unclosed
        `{` with a `|` after it is refused, and a `|` group nested in (or holding) another
        brace group is refused -- both look like an intended variable the rule can't read.
    So a prompt with no `|` group and no `__name__` token resolves to itself byte for byte:
    it never changes what PixAI receives and never needs a confirm.

    `vars` are the variable parts in order of appearance (the same token twice is two
    variables). `error` is the FIRST refusal by position. `syntax` is True when the rule
    acted at all -- a variable, a list, a dropped backslash or a refusal -- which is what
    /api/generate refuses (review F2)."""
    s = str(template if template is not None else "")
    lists = lists or {}
    parts, error, syntax = [], None, False
    buf = []
    n = len(s)
    nvars = 0
    groups, consume, bad_open = _template_marks(s)

    def flush():
        if buf:
            parts.append({"lit": "".join(buf)})
            del buf[:]

    def bad(token, msg):
        nonlocal error
        flush()
        parts.append({"bad": token, "error": msg})
        if error is None:
            error = msg

    def add_var(part):
        nonlocal nvars, error
        flush()
        nvars += 1
        if nvars > MAX_VARS:
            parts.append({"bad": part["var"], "error": ERR_TOO_MANY_VARS})
            if error is None:
                error = ERR_TOO_MANY_VARS
            return
        parts.append(part)

    i = 0
    while i < n:
        c = s[i]
        if i in consume:                     # a backslash that changes the parse: dropped
            syntax = True
            i += 1
            continue
        if c == "\\":
            m = _LIST_TOKEN_RE.match(s, i + 1)
            if m:                            # \__name__ is the literal text __name__
                buf.append(m.group(0))
                syntax = True
                i = m.end()
                continue
            buf.append(c)
            i += 1
            continue
        if c == "{":
            g = groups.get(i)
            if g is not None and g[0] == "live":
                syntax = True
                j = g[1]
                token = s[i:j + 1]
                opts = [trim(o) for o in s[i + 1:j].split("|")]
                opts = [o for o in opts if o]
                if not opts:
                    bad(token, ERR_EMPTY)
                elif len(opts) > MAX_OPTIONS:
                    bad(token, ERR_TOO_MANY_OPTS)
                else:
                    add_var({"var": token, "options": opts, "kind": "inline"})
                i = j + 1
                continue
            if g is not None and g[0] == "nested":
                syntax = True
                bad(s[i:g[1] + 1], ERR_UNCLOSED)
                i = g[1] + 1
                continue
            if i in bad_open:
                syntax = True
                bad("{", ERR_UNCLOSED)
                i += 1
                continue
            buf.append(c)                    # a literal brace (an escaped group's too)
            i += 1
            continue
        if c == "_":
            m = _LIST_TOKEN_RE.match(s, i)
            if m:
                syntax = True
                token, name = m.group(0), m.group(1)
                if name not in lists:
                    bad(token, err_unknown_list(token))
                else:
                    items = clean_list(lists.get(name))
                    if items is None:
                        bad(token, err_long_list(token))
                    elif not items:
                        bad(token, err_empty_list(token))
                    else:
                        add_var({"var": token, "options": items, "kind": "list",
                                 "name": name})
                i = m.end()
                continue
        buf.append(c)
        i += 1
    flush()
    return {"parts": parts, "vars": [p for p in parts if "var" in p], "error": error,
            "syntax": syntax}


def has_syntax(template):
    """True when the text is not plain literal text under the template rule (see parse)."""
    return parse(template, None)["syntax"]


def _resolve(parts, values):
    """The template with each variable replaced by its value; nothing else changes."""
    out, k = [], 0
    for p in parts:
        if "lit" in p:
            out.append(p["lit"])
        elif "var" in p:
            out.append(values[k])
            k += 1
    return "".join(out)


def _draws(run_seed):
    """The page's LCG (Generate Power Tools Handoff, rng()): s = (seed >>> 0) || 1, then
    s = (s * 1664525 + 1013904223) mod 2^32 per draw; index = floor(s / 2^32 * len). The
    integer form below is exact and equals the JS one (s * len < 2^53)."""
    s = (int(run_seed) & 0xFFFFFFFF) or 1
    while True:
        s = (s * 1664525 + 1013904223) & 0xFFFFFFFF
        yield s


def matrix_product(vars_):
    """The number of cells, stopping the moment it passes a million (never a list)."""
    product = 1
    for v in vars_:
        product *= len(v["options"])
        if product > _BIG:
            return _BIG + 1
    return product


def plan_jobs(template, lists, var_mode, count, run_seed=None):
    """Expand a template into its jobs, before anything is sent (NOTES 1, s1.3-1.5).

    var_mode "random" | "matrix"; count 1-4 (Random / plain batch) or 1 (Matrix) -- the
    caller has already refused anything else; run_seed an int 0..RUN_SEED_MAX, needed only
    for a Random run with variables.

    Returns {"error": msg} or
      {"mode": "single"|"batch"|"random"|"matrix", "images": int, "product": int,
       "axes": [{"token", "values"}] (matrix), "jobs": [
           {"cell": k, "prompt": resolved, "vars": [{"token", "value"}],
            "seed": int|None (None = the dock's own seed field), "batch": 1..4}]}
    """
    P = parse(template, lists)
    if P["error"]:
        return {"error": P["error"]}
    vars_ = P["vars"]
    if not vars_:
        prompt = _resolve(P["parts"], [])
        batch = count if var_mode == "random" else 1
        return {"mode": "batch" if batch > 1 else "single", "images": batch, "product": 1,
                "jobs": [{"cell": 0, "prompt": prompt, "vars": [], "seed": None,
                          "batch": batch}]}
    jobs = []
    if var_mode == "matrix":
        product = matrix_product(vars_)
        if product > CELL_CAP:
            return {"error": err_over_cap(product), "product": product}
        for v in vars_:
            seen = set()
            for o in v["options"]:
                if o in seen:
                    return {"error": err_duplicate(v["var"], o)}
                seen.add(o)
        for i in range(product):
            r, vals = i, []
            for v in reversed(vars_):
                opts = v["options"]
                vals.append(opts[r % len(opts)])
                r //= len(opts)
            vals.reverse()
            jobs.append({"cell": i, "prompt": _resolve(P["parts"], vals),
                         "vars": [{"token": v["var"], "value": x} for v, x in zip(vars_, vals)],
                         "seed": None, "batch": 1})
        mode = "matrix"
        axes = [{"token": v["var"], "values": list(v["options"])} for v in vars_]
    else:
        product = matrix_product(vars_)
        rng = _draws(run_seed)
        for k in range(count):
            vals = []
            for v in vars_:
                opts = v["options"]
                vals.append(opts[(next(rng) * len(opts)) >> 32])
            jobs.append({"cell": k, "prompt": _resolve(P["parts"], vals),
                         "vars": [{"token": v["var"], "value": x} for v, x in zip(vars_, vals)],
                         "seed": (int(run_seed) + k) % SEED_MOD, "batch": 1})
        mode = "random"
        axes = None
    for j in jobs:
        if not trim(j["prompt"]):
            return {"error": err_blank_cell(j["cell"] + 1)}
    out = {"mode": mode, "images": len(jobs), "product": product, "jobs": jobs}
    if axes is not None:
        out["axes"] = axes
    return out


def forces_no_card(plan):
    """True when a send of `plan` goes out with no free card, whatever the payload says:
    a Matrix of 2 or more cells (Settled 2 -- free cards never cover queued matrix cells).
    A one-cell matrix is an ordinary single send and its card applies as for any single send
    (review B1). The dock's cost badge prices with no_card on exactly when this is True."""
    return bool(plan) and not plan.get("error") and plan.get("mode") == "matrix" \
        and len(plan.get("jobs") or []) >= 2


def same_prompt_cells(plan):
    """(a, b), the first two cell numbers (1-based) of a Matrix plan whose resolved prompts
    are the same, or None (review N4: with a fixed seed they would pay twice for one image)."""
    if not plan or plan.get("mode") != "matrix":
        return None
    seen = {}
    for j in plan.get("jobs") or []:
        if j["prompt"] in seen:
            return seen[j["prompt"]] + 1, j["cell"] + 1
        seen[j["prompt"]] = j["cell"]
    return None


def escape_literal(text):
    """A plain prompt made safe to put back in the composer (History reuse of a run with no
    stored template, open call 3): parse(escape_literal(t)) resolves to exactly t, with no
    variable and no refusal. Under the S1 rule only what the rule would act on gets a
    backslash: the `{` of every `|` group (and its `}` when a backslash already sits before
    it, so that one survives), an unclosed `{` with a `|` after it, and the first `_` of
    every list token. Everything else -- ordinary braces, `long_hair`, a kaomoji's `\\_` --
    stays exactly as it is."""
    s = str(text or "")
    n = len(s)
    pairs, _parent, unclosed = _brace_structure(s)
    ins = set()
    for o, c in pairs.items():
        pipe, _child = _pair_shape(s, o, c, pairs)
        if pipe:
            ins.add(o)
            if s[c - 1] == "\\":
                ins.add(c)
    for u in unclosed:
        if "|" in s[u + 1:]:
            ins.add(u)
    i = 0
    while i < n:                    # list tokens, found the way parse's scan finds them
        if s[i] == "_":
            m = _LIST_TOKEN_RE.match(s, i)
            if m:
                ins.add(i)
                i = m.end()
                continue
        i += 1
    return "".join(("\\" + ch) if k in ins else ch for k, ch in enumerate(s))


def strict_int(v, lo, hi):
    """An int in [lo, hi] from a JSON value -- never a bool, never a float with a fraction,
    never clamped (review F13f: one strict reading for the route and the job builder).
    None when it does not qualify."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        n = v
    elif isinstance(v, float) and v.is_integer():
        n = int(v)
    elif isinstance(v, str) and re.fullmatch(r"\s*\d{1,12}\s*", v):
        n = int(v)
    else:
        return None
    return n if lo <= n <= hi else None


# ---------------------------------------------------------------------------------------
# The acknowledgement (review F1 + F3)
# ---------------------------------------------------------------------------------------

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      default=str)


def run_digest(job_params, price_identity):
    """SHA-256 of every job's full built, gated parameters (pre-card) with its no_card flag,
    plus the price-query identity. Not a secret: the server recomputes it from a fresh
    expansion and build, so it proves the jobs about to go out are the ones the confirm
    listed -- any changed setting, list, seed or price input changes it."""
    blob = canonical({"jobs": [[p, bool(nc)] for p, nc in job_params],
                      "price": price_identity})
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


ACK_FIELDS = ("count", "jobs", "each", "covered", "total", "digest")


def ack_problem(ack, plan, fields=ACK_FIELDS):
    """The first acknowledgement field (of `fields`) that differs from the fresh plan, or
    None."""
    if not isinstance(ack, dict):
        return "missing"
    for k in fields:
        a, b = ack.get(k), plan.get(k)
        if isinstance(a, bool) or isinstance(b, bool) or a != b:
            return k
    return None


def ack_count_problem(ack, plan):
    """Review N6: the acknowledgement's count (images) and jobs (tasks) against the LOCAL
    expansion, before any entitlement read, build or quote -- the design's cheap early
    refusal. None when they agree."""
    return ack_problem(ack, {"count": plan["images"], "jobs": len(plan["jobs"])},
                       ("count", "jobs"))


# ---------------------------------------------------------------------------------------
# Secrets (NOTES 7)
# ---------------------------------------------------------------------------------------

_SECRET_KEY_RE = re.compile(
    r"token|secret|password|passwd|api[_-]?key|authorization|cookie|jwt|u3t|session|csrf",
    re.I)


def strip_secrets(obj, redact=None):
    """A copy of `obj` with every key that names a credential removed at any depth, and
    every string passed through `redact` (host paths). Removed from the data, never hidden
    in CSS. kaisuukenId stays: it is a card's id, and part of what was sent."""
    if isinstance(obj, dict):
        return {k: strip_secrets(v, redact) for k, v in obj.items()
                if not _SECRET_KEY_RE.search(str(k))}
    if isinstance(obj, list):
        return [strip_secrets(v, redact) for v in obj]
    if isinstance(obj, str) and redact is not None:
        try:
            return redact(obj)
        except Exception:                                    # noqa: BLE001
            return obj
    return obj


# ---------------------------------------------------------------------------------------
# The Runs store (NOTES 3): runs.db in the library folder, beside catalog.db
# ---------------------------------------------------------------------------------------

RUNS_DB = "runs.db"
TERMINAL_RUN = ("sent", "stopped", "refused")
_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY, account TEXT, created_at REAL, updated_at REAL,
        mode TEXT, template TEXT, var_mode TEXT, run_seed INTEGER, dock_seed TEXT,
        count INTEGER, jobs_n INTEGER, axes TEXT, payload TEXT,
        each_cost INTEGER, covered INTEGER, ack_total INTEGER,
        status TEXT, reason TEXT)""",
    """CREATE TABLE IF NOT EXISTS run_jobs (
        run_id TEXT, cell INTEGER, task_id TEXT, prompt TEXT, vars TEXT, seed INTEGER,
        batch INTEGER, no_card INTEGER, card INTEGER, expected INTEGER, paid INTEGER,
        state TEXT, error TEXT, request TEXT,
        PRIMARY KEY (run_id, cell))""",
    "CREATE INDEX IF NOT EXISTS run_jobs_task ON run_jobs(task_id)",
)
_RUN_COLS = ("run_id", "account", "created_at", "updated_at", "mode", "template",
             "var_mode", "run_seed", "dock_seed", "count", "jobs_n", "axes", "payload",
             "each_cost", "covered", "ack_total", "status", "reason")
_JOB_COLS = ("run_id", "cell", "task_id", "prompt", "vars", "seed", "batch", "no_card",
             "card", "expected", "paid", "state", "error", "request")
_JSON_COLS = ("axes", "payload", "vars", "request")


class RunsUnreadable(Exception):
    """runs.db exists but could not be read (locked past the busy timeout, corrupt, a
    missing table). Distinct from "no such run" (review N7): a route answers "couldn't read
    the run" for this, never "not found", and never falls back to anything else."""


RUN_UNREADABLE_WORDS = "Couldn't read the run."


class RunsStore(object):
    """One SQLite file. Written ONLY by the run route (its reservation, its rows, each
    job's state) and by /api/generate after a single send has a task id -- never on open,
    by /plan, by the Inspector or by History. A read never creates the file. A read answers
    None only when there is no such row (or no file yet); a store that exists but cannot be
    read raises RunsUnreadable. Every connection is closed in a finally. There is no pruning
    yet: the file grows with every run (reported as still to do)."""

    def __init__(self, out_dir):
        self.path = _paths.state_path(out_dir, RUNS_DB)
        self._lock = threading.Lock()

    def _connect(self, create):
        if not create and not self.path.exists():
            return None
        c = sqlite3.connect(str(self.path), timeout=5.0)
        try:
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA busy_timeout=5000")
            if create:
                for stmt in _SCHEMA:
                    c.execute(stmt)
        except BaseException:
            c.close()
            raise
        return c

    def _reader(self):
        """A read connection, or None when there is no file yet; RunsUnreadable when the
        file is there and cannot be opened."""
        try:
            return self._connect(False)
        except sqlite3.Error as e:
            raise RunsUnreadable(str(e))

    @staticmethod
    def _enc(col, v):
        if col in _JSON_COLS and v is not None and not isinstance(v, str):
            return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        return v

    @staticmethod
    def _row(r):
        d = dict(r)
        for k in _JSON_COLS:
            if isinstance(d.get(k), str):
                try:
                    d[k] = json.loads(d[k])
                except ValueError:
                    pass
        return d

    def reserve(self, run_id, account, **fields):
        """Insert the run's first row (status 'planning'). False when run_id is taken."""
        now = time.time()
        rec = dict(fields, run_id=run_id, account=account, created_at=now, updated_at=now)
        rec.setdefault("status", "planning")
        cols = [c for c in _RUN_COLS if c in rec]
        with self._lock:
            c = self._connect(True)
            try:
                c.execute("INSERT INTO runs ({}) VALUES ({})".format(
                    ",".join(cols), ",".join("?" * len(cols))),
                    [self._enc(k, rec[k]) for k in cols])
                c.commit()
                return True
            except sqlite3.IntegrityError:
                return False
            finally:
                c.close()

    def update_run(self, run_id, **fields):
        fields["updated_at"] = time.time()
        cols = [k for k in fields if k in _RUN_COLS and k != "run_id"]
        with self._lock:
            c = self._connect(True)
            try:
                c.execute("UPDATE runs SET {} WHERE run_id=?".format(
                    ",".join(k + "=?" for k in cols)),
                    [self._enc(k, fields[k]) for k in cols] + [run_id])
                c.commit()
            finally:
                c.close()

    def put_jobs(self, run_id, jobs):
        """Every job's row, as 'pending', in one transaction."""
        with self._lock:
            c = self._connect(True)
            try:
                for j in jobs:
                    rec = dict(j, run_id=run_id)
                    rec.setdefault("state", "pending")
                    cols = [k for k in _JOB_COLS if k in rec]
                    c.execute("INSERT OR REPLACE INTO run_jobs ({}) VALUES ({})".format(
                        ",".join(cols), ",".join("?" * len(cols))),
                        [self._enc(k, rec[k]) for k in cols])
                c.commit()
            finally:
                c.close()

    def set_job(self, run_id, cell, **fields):
        cols = [k for k in fields if k in _JOB_COLS and k not in ("run_id", "cell")]
        with self._lock:
            c = self._connect(True)
            try:
                cur = c.execute("UPDATE run_jobs SET {} WHERE run_id=? AND cell=?".format(
                    ",".join(k + "=?" for k in cols)),
                    [self._enc(k, fields[k]) for k in cols] + [run_id, int(cell)])
                if cur.rowcount != 1:
                    raise sqlite3.OperationalError("no such job row")
                c.commit()
            finally:
                c.close()

    def get(self, run_id):
        """{run..., "jobs": [...]}, or None when there is no such run. Raises
        RunsUnreadable when the store cannot be read."""
        c = self._reader()
        if c is None:
            return None
        try:
            r = c.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if r is None:
                return None
            run = self._row(r)
            run["jobs"] = [self._row(x) for x in c.execute(
                "SELECT * FROM run_jobs WHERE run_id=? ORDER BY cell", (run_id,))]
            return run
        except sqlite3.Error as e:
            raise RunsUnreadable(str(e))
        finally:
            c.close()

    def find_task(self, task_id):
        """(run, job) for the job that holds `task_id`, or None when no row holds it. The
        run carries `account`, which is what the routes check before serving anything.
        Raises RunsUnreadable when the store cannot be read."""
        tid = str(task_id or "").strip()
        if not tid:
            return None
        c = self._reader()
        if c is None:
            return None
        try:
            j = c.execute("SELECT * FROM run_jobs WHERE task_id=? LIMIT 1", (tid,)).fetchone()
            if j is None:
                return None
            r = c.execute("SELECT * FROM runs WHERE run_id=?", (j["run_id"],)).fetchone()
            if r is None:
                return None
            return self._row(r), self._row(j)
        except sqlite3.Error as e:
            raise RunsUnreadable(str(e))
        finally:
            c.close()


def job_view(job, run_status=None):
    """A job row as the dock reads it. A row left at 'sending' by a run that is no longer
    being sent (the process died, or the task id could not be written) is never read as
    'not sent': it reads may_have_started (review F5). 'pending' after the run ended was
    never reached: not_sent."""
    state = job.get("state") or "pending"
    if state == "sending" and run_status != "sending":
        state = "may_have_started"
    elif state == "pending" and run_status in TERMINAL_RUN:
        state = "not_sent"
    out = {"cell": job.get("cell"), "state": state, "card": bool(job.get("card")),
           "prompt": job.get("prompt") or "", "vars": job.get("vars") or [],
           "seed": job.get("seed"), "batch": job.get("batch")}
    if job.get("task_id"):
        out["task_id"] = str(job["task_id"])
    if job.get("error"):
        out["error"] = job["error"]
    if job.get("expected") is not None:
        out["expected"] = job["expected"]
    if job.get("paid") is not None:
        out["paid"] = job["paid"]
    return out


def run_view(run, live=True):
    """A stored run as GET /api/generate/runs/<id> answers it. `live` is False when this
    process is not sending it: a row still at planning/sending then belongs to a server that
    stopped mid-run, and reads as stopped."""
    status = run.get("status") or "planning"
    if not live and status in ("planning", "sending"):
        run = dict(run, status="stopped",
                   reason=run.get("reason") or "The server stopped while this run was "
                                                "being sent.")
        status = "stopped"
    jobs = [job_view(j, status) for j in run.get("jobs") or []]
    out = {"run_id": run.get("run_id"), "status": status, "mode": run.get("mode"),
           "count": run.get("count"), "jobs": jobs,
           "sent": sum(1 for j in jobs if j["state"] == "sent"),
           "not_sent": sum(1 for j in jobs if j["state"] == "not_sent")}
    if run.get("reason"):
        out["reason"] = run["reason"]
    if run.get("axes"):
        out["axes"] = run["axes"]
    return out


# ---------------------------------------------------------------------------------------
# Copy as CLI (NOTES 7, Settled 1): the real command and flags
# ---------------------------------------------------------------------------------------

CLI_PREFIX = ["python", "moonglade_backup.py", "--generate"]
# PowerShell reads all four of these as a single quote inside a '...' string (review F8b).
_PS_SINGLE_QUOTES = "'‘’‚‛"
_MODES = ("lite", "standard", "pro", "ultra")
# What the CLI's argparse sets when a flag is absent, for the dests _gen_parameters reads.
# tests/test_generate_runs.py checks each against the real parser.
_CLI_DEFAULTS = dict(params_json="", prompt="", negative="", model="", width=512,
                     height=512, steps=25, cfg=7.0, count=1, seed=None, priority=None,
                     mode="auto", prompt_helper=True, lora=None, enlarge=None,
                     enlarge_model="", upscale=None, upscale_denoising_strength=None,
                     upscale_denoising_steps=None, face_fix=False, quality_tag="",
                     kaisuuken_id="", no_card=False)


def _ps_native(arg):
    """`arg` as Windows PowerShell 5.1 must hand it to a native program so the C runtime's
    argv parser (what python.exe reads) rebuilds it byte for byte (review F8a).

    5.1 passes an embedded double quote on unescaped, and it wraps an argument in quotes only
    when some whitespace in it follows an EVEN number of double-quote characters (it counts
    every one, backslash or not) -- so `{\\"k\\":\\"v w\\"}` reached python as two words. The
    form here never depends on that guess: an argument with whitespace or a quote is wrapped
    in quotes HERE, each quote inside written as the pair `""` (the runtime's in-quotes escape),
    which keeps every whitespace after an odd count so 5.1 never wraps it a second time. The
    backslashes before a quote -- the closing one included -- are doubled, the runtime's rule;
    others stay single. Checked against real powershell.exe in tests/test_generate_runs.py."""
    if not any(c.isspace() or c == '"' for c in arg):
        return arg
    out, bs = ['"'], 0
    for ch in arg:
        if ch == "\\":
            bs += 1
            continue
        if ch == '"':
            out.append("\\" * (2 * bs) + '""')
        else:
            out.append("\\" * bs + ch)
        bs = 0
    out.append("\\" * (2 * bs) + '"')
    return "".join(out)


def _ps_quote(arg):
    """One PowerShell single-quoted literal: every single-quote character doubled."""
    body = _ps_native(arg)
    for q in _PS_SINGLE_QUOTES:
        body = body.replace(q, q + q)
    return "'" + body + "'"


def _quote(arg, shell):
    if shell == "powershell":
        # A word PowerShell passes on as it is: letters, digits and . _ : / + - (no leading
        # dash unless it is a flag name, never $ @ ` ' " ( ) { } ; , or whitespace).
        if re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:/+-]*", arg):
            return arg
        if re.fullmatch(r"--?[a-z][a-z0-9-]*", arg):
            return arg
        return _ps_quote(arg)
    return shlex.quote(arg)


# The name the Inspector shows beside Copy as CLI (review S3): the command is quoted for the
# shell of the machine the server runs on, and only that one -- PowerShell's quoting is not
# cmd.exe's (in cmd.exe `&` `|` `^` `%` stay live inside a PowerShell single-quoted word).
SHELL_NAMES = {"powershell": "PowerShell", "posix": "bash"}


def default_shell():
    return "powershell" if os.name == "nt" else "posix"


def _num_text(v):
    """A number as the CLI's argparse reads it back to the same value (repr round-trips)."""
    if isinstance(v, bool):
        raise ValueError("bool")
    return repr(v) if isinstance(v, float) else str(int(v))


def _flag_args(core, params):
    """(argv tail, namespace) for `params` in the CLI's own flags, or None when a key has no
    flag. The namespace is what argparse would build from that argv."""
    p = dict(params)
    ns = dict(_CLI_DEFAULTS)
    argv = []

    def add(flag, value, dest, parsed):
        text = value if isinstance(value, str) else _num_text(value)
        if text.startswith("-"):
            argv.append(("=", flag, text))
        else:
            argv.append((" ", flag, text))
        ns[dest] = parsed

    known = {"prompts", "naturalPrompts", "modelId", "width", "height", "samplingSteps",
             "cfgScale", "batchSize", "seed", "priority", "inferenceProfile",
             "negativePrompts", "lora", "loraParameters", "promptHelper", "enlarge",
             "enlargeModel", "upscale", "upscaleDenoisingStrength", "upscaleDenoisingSteps",
             "upscaleSampler", "enableADetailer", "qualityTag"}
    if set(p) - known:
        return None
    prompt = p.get("prompts")
    if not isinstance(prompt, str) or not prompt or p.get("naturalPrompts") != prompt:
        return None
    try:
        add("--model", str(p["modelId"]), "model", str(p["modelId"]))
        add("--prompt", prompt, "prompt", prompt)
        neg = p.get("negativePrompts")
        if neg is not None:
            if not isinstance(neg, str) or not neg:
                return None
            add("--negative", neg, "negative", neg)
        for key, flag, dest, cast in (("width", "--width", "width", int),
                                      ("height", "--height", "height", int),
                                      ("samplingSteps", "--steps", "steps", int),
                                      ("cfgScale", "--cfg", "cfg", float),
                                      ("batchSize", "--batch-size", "count", int)):
            if key in p:
                v = p[key]
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    return None
                add(flag, v, dest, cast(v))
        if "seed" in p:
            if isinstance(p["seed"], bool) or not isinstance(p["seed"], int):
                return None
            add("--seed", p["seed"], "seed", p["seed"])
        if "priority" in p:
            if p["priority"] not in core.PRIORITY_CHOICES:
                return None
            add("--priority", p["priority"], "priority", p["priority"])
        if "inferenceProfile" in p:
            if p["inferenceProfile"] not in _MODES:
                return None
            add("--mode", p["inferenceProfile"], "mode", p["inferenceProfile"])
        ph = p.get("promptHelper")
        if ph == {"withStage": False, "userWantToEnable": False,
                  "forcePromptHelperDetectionSide": "server"}:
            argv.append(("", "--no-prompt-helper", None))
            ns["prompt_helper"] = False
        loras = p.get("loraParameters")
        if loras is not None:
            specs = []
            for lp in loras:
                vid, w = str(lp.get("versionId") or ""), lp.get("weight")
                if not vid or ":" in vid or isinstance(w, bool) \
                        or not isinstance(w, (int, float)):
                    return None
                spec = "{}:{}".format(vid, _num_text(w))
                argv.append((" ", "--lora", spec))
                specs.append(spec)
            ns["lora"] = specs
        if "enlarge" in p:
            add("--enlarge", p["enlarge"], "enlarge", float(p["enlarge"]))
            if p.get("enlargeModel") not in core.ENLARGE_MODELS:
                return None
            add("--enlarge-model", p["enlargeModel"], "enlarge_model", p["enlargeModel"])
        if "upscale" in p:
            add("--upscale", p["upscale"], "upscale", float(p["upscale"]))
            if "upscaleDenoisingStrength" in p:
                add("--upscale-denoise", p["upscaleDenoisingStrength"],
                    "upscale_denoising_strength", float(p["upscaleDenoisingStrength"]))
            if "upscaleDenoisingSteps" in p:
                add("--upscale-denoise-steps", p["upscaleDenoisingSteps"],
                    "upscale_denoising_steps", int(p["upscaleDenoisingSteps"]))
        if p.get("enableADetailer") is True:
            argv.append(("", "--face-fix", None))
            ns["face_fix"] = True
        qt = p.get("qualityTag")
        if qt is not None:
            if not (isinstance(qt, dict) and set(qt) == {"prefix"}
                    and isinstance(qt["prefix"], str) and qt["prefix"].strip()):
                return None
            add("--quality-tag", qt["prefix"], "quality_tag", qt["prefix"])
    except (TypeError, ValueError, KeyError):
        return None
    if ns["priority"] is None:
        ns["priority"] = core.PRIORITY_TURBO
    return argv, ns


def cli_command(core, params, *, no_card=False, shell=None):
    """The command-line form of one job's parameters: {"command", "form", "shell"}.

    One command per job (the CLI has no template or matrix; open call 7), on one line,
    never --confirm (the CLI previews until the user adds it) and never --kaisuuken-id (the
    card is matched when the CLI sends). The flag form is used only when the CLI's own
    builder, _gen_parameters, rebuilds exactly these parameters from those flags; anything
    the flags cannot say (context images, recipes, a palette, creativity, an image
    reference, a quality-tag suffix, a gate's changes) goes as --params-json instead, which
    the CLI still sends through its own gate."""
    shell = shell or default_shell()
    body = {k: v for k, v in (params or {}).items() if k != "kaisuukenId"}
    tail = None
    got = _flag_args(core, body)
    if got is not None:
        argv, ns = got
        try:
            rebuilt = core._gen_parameters(SimpleNamespace(**ns))
        except Exception:                                    # noqa: BLE001
            rebuilt = None
        if rebuilt == body:
            tail = argv
    words = [_quote(w, shell) for w in CLI_PREFIX]
    if tail is not None:
        form = "flags"
        for sep, flag, value in tail:
            if value is None:
                words.append(flag)
            elif sep == "=":
                words.append(_quote(flag + "=" + value, shell))
            else:
                words.append(flag)
                words.append(_quote(value, shell))
    else:
        form = "json"
        words.append("--params-json")
        words.append(_quote(json.dumps(body, ensure_ascii=True, separators=(",", ":")),
                            shell))
    if no_card:
        words.append("--no-card")
    return {"command": " ".join(words), "form": form, "shell": shell,
            "shell_name": SHELL_NAMES.get(shell, shell)}
