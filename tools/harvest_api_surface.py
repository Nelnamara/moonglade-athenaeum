#!/usr/bin/env python3
"""Harvest PixAI's entire GraphQL operation surface from their own JavaScript.

    python tools/harvest_api_surface.py fetch      # crawl every JS chunk (cached per build)
    python tools/harvest_api_surface.py extract    # mine ASTs -> operations + DERIVED hashes
    python tools/harvest_api_surface.py show       # print the catalog
    python tools/harvest_api_surface.py doc <op>   # print one operation's full GraphQL
    python tools/harvest_api_surface.py diff       # what changed since last harvest (chunks + ops)
    python tools/harvest_api_surface.py replay <op>  # ONE read-only op, explicit

WHY THIS EXISTS
Every layer we peeled by hand revealed another. Bookmarks took a browser session, a network
capture and three probes, and the answer was in their bundle the whole time. This gets the whole
surface at once, offline, without a single call to their GraphQL endpoint.

WHAT WAS MEASURED (2026-07-25/26, revised 2026-08-16) -- none of this is assumed
  * pixai.art is a React Router app bundled with Rolldown. NOT Next.js: no `_next`, no buildId,
    no webpackChunk. Two earlier attempts in this very file failed on that assumption.
  * Its JS is not served from pixai.art at all, but from a LABELLED CDN path:
        https://cdn.pixai.art/artifacts/app-1.0.2605/assets/<name>-<HASH>.js
    referenced by <link rel="modulepreload">, 526 of them on the homepage alone (195 on
    2026-08-16 -- the count moves with the build; the crawl follows imports regardless).
  * **The `app-1.0.2605` label is NOT a build fingerprint** (measured 2026-08-16). The label
    stayed `app-1.0.2605` from 2026-07-25 through 2026-08-16 while only 65 of 967 chunk
    filenames overlapped -- new builds ship under the same label. The chunk NAMES are the
    fingerprint: `<name>-<HASH>.js` is content-hashed, so the build IS the sorted set of chunk
    filenames the homepage references. `fetch` hashes that set (sha256, 12 hex) and `diff`
    compares chunk sets, not labels. (Of the 65 shared names, 64 were byte-identical and one
    differed only by an appended `//# sourceMappingURL` comment -- so a same-named chunk from
    an earlier crawl is safe to reuse instead of re-downloading.)
  * Chunks import each other, so the crawl follows imports transitively. That is the point: an
    earlier pass scanned "all 204 chunks on the enhancement page" and concluded a value did not
    exist, when it was simply in a LAZY chunk that page never loaded.
  * The chunk cache is partitioned PER CRAWL: private/harvest/chunks/<fingerprint>/. Before
    that (2026-07) `fetch` never cleared a flat chunks/ and `extract` mined all of it: by
    2026-08 it held 2617 chunks from >=3 builds -- three different `utils-*.js` each carrying
    `listUserBookmarks` -- and the catalog was a multi-build union in which "first chunk wins"
    could pick a stale document over the current one. `extract` now mines only the crawl that
    `fetch` last recorded in build.json.
  * **The sha256 hashes are NOT in the bundle.** Zero 64-hex strings across 868 chunks / 16 MB.
    Apollo computes them at runtime from the query document.
  * **But the documents ARE, as pre-parsed AST literals** -- `{kind:"Document",definitions:[..]}`
    -- 191 in a single chunk. Complete field projections and typed variable definitions.

So the hashes are DERIVED, not captured: print the AST the way graphql-js prints it, sha256 the
result. That is what Apollo itself does, so it produces the same hash -- and it keeps working
after a PixAI redeploy, which capture-by-hand does not.

THE ORACLE. A derived hash is worthless if the derivation is subtly wrong, so three hashes
observed on real requests are baked in below. `extract` tries each print variant, keeps only one
that reproduces all three, and refuses to emit hashes at all if none does. It cannot silently
hand back plausible-looking wrong hashes -- that exact failure mode has already cost this
project real time.

SAFETY, BY CONSTRUCTION
  * `fetch` and `extract` never touch api.pixai.art. Static CDN files only.
  * `replay` takes ONE operation, refuses anything that looks like a mutation, and requires an
    allowlist entry or an explicit --force. There is deliberately no "replay everything" mode:
    blindly calling a harvested catalog could delete tasks, submit generations and spend real
    credits.
  * Output goes to private/ (git-ignored) -- this is reverse-engineering material, and the
    repo's public docs deliberately do not carry it.
  * CDN requests are paced. Being polite to their servers is a standing rule here.
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "private" / "harvest"
CHUNKS = OUT / "chunks"                 # one sub-dir per crawl: chunks/<fingerprint>/
CATALOG = OUT / "operations.json"
PREVIOUS = OUT / "operations.prev.json"
BUILD_JSON = OUT / "build.json"         # the crawl `extract` mines: label, fingerprint, chunk set
LEGACY_BUILD_TXT = OUT / "build.txt"    # pre-2026-08-16 pointer (label only); superseded

SITE = "https://pixai.art"
DELAY = 0.2

# Hashes observed on REAL requests. The derivation must reproduce all three or it is wrong.
ORACLE = {
    "listMyBookmarkedGenerationModels":
        "2281653492ff54ef17707104736fd74e7a8d70dc314e024e595f0e71ff2945b9",
    "listGenerationModels":
        "b7a2d663bc0381dd6eb26f8c68f702cb928bea720982f6f5553ea1629a8e871d",
    "getMyInfo":
        "73ed36dec9299a9062c3ffdb98a86dcbc7d23808394a5dd0cede3e8407a7dd2d",
}

REPLAY_ALLOWLIST = {"listGenerationModels", "listMyBookmarkedGenerationModels",
                    "getMyInfo", "getMyMembership"}
MUTATION_HINTS = ("create", "delete", "update", "submit", "claim", "upload", "purchase", "buy",
                  "cancel", "remove", "add", "set", "toggle", "like", "bookmark", "follow",
                  "publish", "train", "redeem", "transfer", "withdraw", "start", "stop")


def _session():
    import moonglade_backup as core
    return core, core._make_session(None)


# ---------------------------------------------------------------- fetch
RE_ASSET = re.compile(r'assets/([A-Za-z0-9._~-]+\.js)')
RE_BASE = re.compile(r'(https?://[^"\'\s]+?/artifacts/app-[0-9.]+)/assets/')


def _fingerprint(names):
    """The build's identity: sha256 of the sorted, de-duplicated chunk filenames the homepage
    references, first 12 hex. Chunk names are content-hashed, so this changes exactly when
    the build does -- which the CDN label (`app-1.0.2605`) measurably does not."""
    return _sha("\n".join(sorted(set(names))))[:12]


def _safe_name(name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def _read_build_json():
    if not BUILD_JSON.exists():
        return None
    try:
        return json.loads(BUILD_JSON.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _reuse_cached(fname, dest, sibling_dirs):
    """Chunk names are content-hashed, so a same-named file anywhere in the cache is the same
    chunk (measured: 64/65 shared names byte-identical, the 65th differed only by a trailing
    sourceMappingURL comment). Reuse it rather than ask the CDN again. A loose file directly
    under chunks/ is a leftover of the pre-partition flat layout with no crawl of its own, so
    it is MOVED into this crawl; a sibling crawl's file is COPIED, leaving that crawl whole.
    Returns True if `dest` was populated."""
    loose = CHUNKS / fname
    if loose.is_file() and loose.stat().st_size:
        loose.replace(dest)
        return True
    for d in sibling_dirs:
        cand = d / fname
        if cand.is_file() and cand.stat().st_size:
            shutil.copyfile(cand, dest)
            return True
    return False


def cmd_fetch(args):
    """Crawl the whole JS asset graph into a per-build cache. Makes no GraphQL calls."""
    import requests
    OUT.mkdir(parents=True, exist_ok=True)
    CHUNKS.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/126 Safari/537.36")

    print("1. reading {} for the asset base".format(SITE))
    html = s.get(SITE, timeout=60).text
    bases = RE_BASE.findall(html)
    if not bases:
        sys.exit("no /artifacts/app-*/assets/ base found -- their build layout changed. Open the "
                 "site, copy one script URL, and update RE_BASE.")
    base = max(set(bases), key=bases.count)
    label = base.rsplit("/", 1)[-1]
    referenced = sorted(set(RE_ASSET.findall(html)))
    fp = _fingerprint(referenced)
    crawl_dir = CHUNKS / fp
    print("   base        : {}/assets/".format(base))
    print("   label       : {}   (a CDN path segment -- NOT a build fingerprint)".format(label))
    print("   fingerprint : {}   ({} chunks referenced by the page)".format(fp, len(referenced)))
    prev = _read_build_json()
    if prev and prev.get("fingerprint") and prev["fingerprint"] != fp:
        print("   NEW BUILD: previous crawl was {} (label {})".format(
            prev["fingerprint"], prev.get("label")))
    elif prev and prev.get("fingerprint") == fp:
        print("   same fingerprint as the previous crawl -- cache is warm")

    crawl_dir.mkdir(parents=True, exist_ok=True)
    siblings = sorted(d for d in CHUNKS.iterdir() if d.is_dir() and d != crawl_dir)
    queue = list(referenced)
    print("2. following imports from those {} chunks -> {}".format(len(queue), crawl_dir))

    seen, got, cached, reused, failed = set(), 0, 0, 0, 0
    while queue and len(seen) < args.max_chunks:
        name = queue.pop(0)
        if name in seen:
            continue
        seen.add(name)
        fname = _safe_name(name)
        dest = crawl_dir / fname
        text = None
        if dest.exists() and dest.stat().st_size:
            text = dest.read_text(encoding="utf-8", errors="replace")
            cached += 1
        elif _reuse_cached(fname, dest, siblings):
            text = dest.read_text(encoding="utf-8", errors="replace")
            reused += 1
        else:
            try:
                r = s.get("{}/assets/{}".format(base, name), timeout=60)
                if r.status_code == 200:
                    text = r.text
                    dest.write_text(text, encoding="utf-8", errors="replace")
                    got += 1
                else:
                    failed += 1
            except Exception:                                   # noqa: BLE001
                failed += 1
            time.sleep(DELAY)
        if text:
            for n in RE_ASSET.findall(text):                    # reaches the lazy chunks
                if n not in seen:
                    queue.append(n)
        if len(seen) % 100 == 0:
            print("   crawled {}  (queue {})".format(len(seen), len(queue)))

    if queue:
        print("   (!) stopped at --max-chunks={}; {} still queued.".format(
            args.max_chunks, len(queue)))
    print("   crawled {} chunks: fetched {}  already-cached {}  reused-by-name {}  failed {}"
          .format(len(seen), got, cached, reused, failed))
    loose = sum(1 for p in CHUNKS.glob("*.js"))
    if loose:
        print("   note: {} loose chunks directly under {} are left over from the pre-partition "
              "cache and are not part of this build; extract ignores them (safe to delete)."
              .format(loose, CHUNKS))

    on_disk = sorted(p.name for p in crawl_dir.glob("*.js"))
    BUILD_JSON.write_text(json.dumps({
        "label": label, "fingerprint": fp, "base": base,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "referenced": referenced,          # what the fingerprint is computed over
        "crawled": len(on_disk), "failed": failed, "stopped_early": bool(queue),
    }, indent=2), encoding="utf-8")
    if LEGACY_BUILD_TXT.exists():          # this tool's own pre-2026-08-16 pointer; superseded
        LEGACY_BUILD_TXT.unlink()
    print("   -> {}".format(BUILD_JSON))
    print("\nNext: python tools/harvest_api_surface.py extract")


# ------------------------------------------------- JS object-literal parser
# The bundle stores documents as JS object literals with UNQUOTED keys, so json.loads cannot read
# them. This is a small recursive-descent reader for exactly that subset. It also returns the end
# offset, which is how a document's extent is found -- no separate brace matching, and therefore
# no risk of a brace inside a string throwing the scan off.
class JSLiteralError(ValueError):
    pass


_ID = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_NUM = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _skip_ws(s, i):
    while i < len(s) and s[i] in " \t\r\n":
        i += 1
    return i


def _read_string(s, i):
    quote = s[i]
    j, buf = i + 1, []
    while j < len(s):
        c = s[j]
        if c == "\\":
            buf.append(s[j:j + 2])
            j += 2
            continue
        if c == quote:
            raw = "".join(buf)
            if quote == "'":
                raw = raw.replace("\\'", "'").replace('"', '\\"')
            try:
                return json.loads('"' + raw + '"'), j + 1
            except ValueError:
                return raw, j + 1
        buf.append(c)
        j += 1
    raise JSLiteralError("unterminated string")


def _read_value(s, i):
    i = _skip_ws(s, i)
    if i >= len(s):
        raise JSLiteralError("eof")
    c = s[i]
    if c == "{":
        obj = {}
        i = _skip_ws(s, i + 1)
        if s[i] == "}":
            return obj, i + 1
        while True:
            i = _skip_ws(s, i)
            if s[i] in "\"'":
                key, i = _read_string(s, i)
            else:
                m = _ID.match(s, i)
                if not m:
                    raise JSLiteralError("bad key at {}".format(i))
                key, i = m.group(0), m.end()
            i = _skip_ws(s, i)
            if s[i] != ":":
                raise JSLiteralError("expected : at {}".format(i))
            val, i = _read_value(s, i + 1)
            obj[key] = val
            i = _skip_ws(s, i)
            if s[i] == ",":
                i += 1
                continue
            if s[i] == "}":
                return obj, i + 1
            raise JSLiteralError("expected , or close-brace at {}".format(i))
    if c == "[":
        arr = []
        i = _skip_ws(s, i + 1)
        if s[i] == "]":
            return arr, i + 1
        while True:
            val, i = _read_value(s, i)
            arr.append(val)
            i = _skip_ws(s, i)
            if s[i] == ",":
                i += 1
                continue
            if s[i] == "]":
                return arr, i + 1
            raise JSLiteralError("expected , or ] at {}".format(i))
    if c in "\"'":
        return _read_string(s, i)
    if s.startswith("true", i):
        return True, i + 4
    if s.startswith("false", i):
        return False, i + 5
    if s.startswith("null", i):
        return None, i + 4
    m = _NUM.match(s, i)
    if m:
        txt = m.group(0)
        return (float(txt) if ("." in txt or "e" in txt.lower()) else int(txt)), m.end()
    # A bare identifier means the literal references a variable -- a shared fragment, say. None
    # were found in this bundle, but fail loudly rather than silently emit a truncated document.
    m = _ID.match(s, i)
    if m:
        raise JSLiteralError("unresolved reference {!r}".format(m.group(0)))
    raise JSLiteralError("unparseable at {}: {!r}".format(i, s[i:i + 20]))


# ------------------------------------------------- graphql-js compatible printer
# Faithful port of graphql-js printer.js. Whitespace is load-bearing here: it feeds the sha256, so
# one wrong space yields a wrong hash. The ORACLE above is what proves this correct.
MAX_LINE = 80


def _wrap(start, s, end=""):
    return start + s + end if s else ""


def _join(parts, sep=""):
    return sep.join(p for p in parts if p)


def _indent(s):
    return _wrap("  ", s.replace("\n", "\n  "))


def _block(items):
    return "{\n" + _indent(_join(items, "\n")) + "\n}" if items else ""


def _name(n):
    return n["value"] if isinstance(n, dict) else ""


def _p(node):
    """Print one AST node exactly as graphql-js print() would."""
    k = node["kind"]

    if k == "Document":
        return _join([_p(d) for d in node["definitions"]], "\n\n")

    if k == "OperationDefinition":
        op = node.get("operation", "query")
        vds = _wrap("(", _join([_p(v) for v in node.get("variableDefinitions") or []], ", "), ")")
        dirs = _join([_p(d) for d in node.get("directives") or []], " ")
        prefix = _join([op, _join([_name(node.get("name")), vds]), dirs], " ")
        sel = _p(node["selectionSet"])
        return sel if prefix == "query" else prefix + " " + sel

    if k == "VariableDefinition":
        return ("$" + _name(node["variable"]["name"]) + ": " + _p(node["type"])
                + _wrap(" = ", _p(node["defaultValue"]) if node.get("defaultValue") else "")
                + _wrap(" ", _join([_p(d) for d in node.get("directives") or []], " ")))

    if k == "SelectionSet":
        return _block([_p(s) for s in node["selections"]])

    if k == "Field":
        prefix = _wrap("", _name(node.get("alias")), ": ") + _name(node["name"])
        args = [_p(a) for a in node.get("arguments") or []]
        line = prefix + _wrap("(", _join(args, ", "), ")")
        if len(line) > MAX_LINE:
            line = prefix + _wrap("(\n", _indent(_join(args, "\n")), "\n)")
        dirs = _join([_p(d) for d in node.get("directives") or []], " ")
        sel = _p(node["selectionSet"]) if node.get("selectionSet") else ""
        return _join([line, dirs, sel], " ")

    if k == "Argument":
        return _name(node["name"]) + ": " + _p(node["value"])

    if k == "FragmentSpread":
        return ("..." + _name(node["name"])
                + _wrap(" ", _join([_p(d) for d in node.get("directives") or []], " ")))

    if k == "InlineFragment":
        return _join(["...",
                      _wrap("on ", _p(node["typeCondition"]) if node.get("typeCondition") else ""),
                      _join([_p(d) for d in node.get("directives") or []], " "),
                      _p(node["selectionSet"])], " ")

    if k == "FragmentDefinition":
        vds = _wrap("(", _join([_p(v) for v in node.get("variableDefinitions") or []], ", "), ")")
        dirs = _wrap("", _join([_p(d) for d in node.get("directives") or []], " "), " ")
        return ("fragment {}{} on {} {}".format(_name(node["name"]), vds,
                                                _p(node["typeCondition"]), dirs)
                + _p(node["selectionSet"]))

    if k == "Directive":
        return ("@" + _name(node["name"])
                + _wrap("(", _join([_p(a) for a in node.get("arguments") or []], ", "), ")"))

    if k == "NamedType":
        return _name(node["name"])
    if k == "ListType":
        return "[" + _p(node["type"]) + "]"
    if k == "NonNullType":
        return _p(node["type"]) + "!"
    if k == "Variable":
        return "$" + _name(node["name"])

    if k == "BooleanValue":
        return "true" if node["value"] else "false"
    if k in ("IntValue", "FloatValue", "EnumValue"):
        return str(node["value"])
    if k == "NullValue":
        return "null"
    if k == "StringValue":
        if node.get("block"):
            return '"""\n' + node["value"] + '\n"""'
        return json.dumps(node["value"], ensure_ascii=False)
    if k == "ListValue":
        return "[" + _join([_p(v) for v in node["values"]], ", ") + "]"
    if k == "ObjectValue":
        return "{" + _join([_p(f) for f in node["fields"]], ", ") + "}"
    if k == "ObjectField":
        return _name(node["name"]) + ": " + _p(node["value"])

    raise ValueError("unhandled node kind {}".format(k))


TYPENAME = {"kind": "Field", "name": {"kind": "Name", "value": "__typename"}}


def _add_typename(node, parent_kind=None):
    """Apollo's addTypenameToDocument: append __typename to every selection set except an
    operation's root, skipping any set that already selects a `__`-prefixed field."""
    if isinstance(node, list):
        return [_add_typename(n, parent_kind) for n in node]
    if not isinstance(node, dict) or "kind" not in node:
        return node
    out = {k: (v if k == "kind" else _add_typename(v, node["kind"])) for k, v in node.items()}
    if node["kind"] == "SelectionSet" and parent_kind != "OperationDefinition":
        sels = out.get("selections") or []
        already = any(isinstance(s, dict) and s.get("kind") == "Field"
                      and _name(s.get("name")).startswith("__") for s in sels)
        if sels and not already:
            out["selections"] = list(sels) + [TYPENAME]
    return out


# Which print variant Apollo hashes is an empirical question, not a guessable one: whether
# __typename is injected before hashing, and whether a trailing newline is appended (that differs
# between graphql-js 15 and 16). Try all four and let the ORACLE decide.
VARIANTS = [
    ("typename,no-newline", True, False),
    ("typename,newline", True, True),
    ("raw,no-newline", False, False),
    ("raw,newline", False, True),
]


def _render(doc, typename, newline):
    text = _p(_add_typename(doc) if typename else doc)
    return text + "\n" if newline else text


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- extract
def _scan_documents(text):
    """Yield every {kind:"Document",...} literal in a chunk, parsed."""
    for m in re.finditer(r'\{kind:"Document"', text):
        try:
            doc, _end = _read_value(text, m.start())
        except (JSLiteralError, IndexError, RecursionError):
            continue
        if isinstance(doc, dict) and doc.get("definitions"):
            yield doc


def cmd_extract(args):
    build = _read_build_json()
    if not build or not build.get("fingerprint"):
        sys.exit("no build.json -- run `fetch` first. (Since 2026-08-16 chunks are cached per "
                 "crawl under chunks/<fingerprint>/ and extract mines only the crawl fetch "
                 "recorded there; a flat chunks/ from before that is not mined.)")
    crawl_dir = CHUNKS / build["fingerprint"]
    files = sorted(crawl_dir.glob("*.js"))          # THIS crawl only -- never the siblings
    if not files:
        sys.exit("crawl {} has no chunks -- run `fetch` first".format(crawl_dir))
    print("mining {} chunks from crawl {} (label {}) for GraphQL document ASTs".format(
        len(files), build["fingerprint"], build.get("label")))

    docs, frags, anon, conflicts = {}, 0, 0, []
    for f in files:
        try:
            t = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if 'kind:"Document"' not in t:
            continue
        for doc in _scan_documents(t):
            ops = [d for d in doc["definitions"] if d.get("kind") == "OperationDefinition"]
            frags += sum(1 for d in doc["definitions"] if d.get("kind") == "FragmentDefinition")
            if not ops:
                continue
            nm = _name(ops[0].get("name"))
            if not nm:
                anon += 1
            elif nm not in docs:
                docs[nm] = (doc, f.name)
            elif docs[nm][0] != doc:
                # Same name, different document, SAME build. First chunk wins, as before -- but
                # inside one crawl that is a curiosity worth a look, not a stale-cache artefact.
                conflicts.append(nm)
    print("  {} named operations, {} fragment definitions, {} anonymous".format(
        len(docs), frags, anon))
    if conflicts:
        print("  (!) {} same-name/different-document conflicts within this crawl (first chunk "
              "kept): {}".format(len(conflicts), ", ".join(sorted(set(conflicts)))))
    if not docs:
        sys.exit("no documents found -- their bundle format changed; re-inspect a chunk.")

    # --- the oracle decides which print variant is real
    print("\nvalidating the hash derivation against {} hashes seen on real requests".format(
        len(ORACLE)))
    winner = None
    for label, typename, newline in VARIANTS:
        marks = []
        for op, expect in ORACLE.items():
            if op not in docs:
                marks.append("{}:MISSING".format(op))
            else:
                got = _sha(_render(docs[op][0], typename, newline))
                marks.append("{}:{}".format(op, "OK" if got == expect else "no"))
        ok = all(m.endswith(":OK") for m in marks)
        print("  {:22} {}   {}".format(label, "PASS" if ok else "fail", "  ".join(marks)))
        if ok and winner is None:
            winner = (label, typename, newline)

    if winner:
        print("\n  derivation PROVEN via '{}' -- every hash below is computed, not captured"
              .format(winner[0]))
    else:
        print("\n  (!) NO variant reproduced all observed hashes. NOT writing derived hashes --")
        print("      plausible-and-wrong is worse than absent. The documents themselves are")
        print("      still valid; only the hashes are unproven.")

    catalog = []
    for nm, (doc, chunk) in sorted(docs.items()):
        op = [d for d in doc["definitions"] if d.get("kind") == "OperationDefinition"][0]
        printed = _render(doc, winner[1], winner[2]) if winner else _p(doc)
        catalog.append({
            "name": nm,
            "kind": op.get("operation", "query"),
            "variables": {_name(v["variable"]["name"]): _p(v["type"])
                          for v in op.get("variableDefinitions") or []},
            "hash": _sha(printed) if winner else None,
            "chunk": chunk,
            "document": printed,
        })

    OUT.mkdir(parents=True, exist_ok=True)
    if CATALOG.exists():
        PREVIOUS.write_text(CATALOG.read_text(encoding="utf-8"), encoding="utf-8")
    # The chunk list rides in the catalog so `diff` (which compares operations.json against
    # operations.prev.json) can say how much of the BUILD changed, not just how many hashes.
    build_block = {"label": build.get("label"), "fingerprint": build["fingerprint"],
                   "fetched_at": build.get("fetched_at"), "chunks": [f.name for f in files]}
    CATALOG.write_text(json.dumps(
        {"site": SITE, "build": build_block, "derivation": winner[0] if winner else None,
         "hashes_proven": bool(winner), "operations": catalog}, indent=2), encoding="utf-8")
    q = sum(1 for c in catalog if c["kind"] == "query")
    print("\n  {} operations ({} queries, {} mutations/subscriptions) from build {}".format(
        len(catalog), q, len(catalog) - q, _build_tag(_build_info({"build": build_block}))))
    print("  -> {}".format(CATALOG))
    print("\nNext: python tools/harvest_api_surface.py show --grep lora")


def _looks_mutating(name):
    low = name.lower()
    return any(low.startswith(h) for h in MUTATION_HINTS)


# ---------------------------------------------------------------- show / doc / diff
def _load():
    if not CATALOG.exists():
        sys.exit("no catalog -- run `fetch` then `extract`")
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _build_info(data):
    """Normalize a catalog's build block. Catalogs written before 2026-08-16 carry only the CDN
    label as a bare string (and no chunk list); newer ones carry a dict."""
    b = data.get("build")
    if isinstance(b, dict):
        return {"label": b.get("label"), "fingerprint": b.get("fingerprint"),
                "chunks": b.get("chunks")}
    return {"label": b, "fingerprint": None, "chunks": None}


def _build_tag(info):
    return "{} [{}]".format(info["label"] or "?", info["fingerprint"] or "no fingerprint")


def cmd_show(args):
    data = _load()
    ops = data["operations"]
    if args.grep:
        g = args.grep.lower()
        ops = [o for o in ops if g in o["name"].lower() or g in json.dumps(o["variables"]).lower()]
    print("build {}   hashes {}   showing {}/{} operations".format(
        _build_tag(_build_info(data)), "PROVEN" if data.get("hashes_proven") else "UNPROVEN",
        len(ops), len(data["operations"])))
    for kind in ("query", "mutation", "subscription"):
        group = [o for o in ops if o["kind"] == kind]
        if not group:
            continue
        print("\n" + "=" * 78)
        print("{}S  ({})".format(kind.upper(), len(group)))
        print("=" * 78)
        for o in group:
            print("  {}".format(o["name"]))
            if o["variables"]:
                print("      ({})".format(", ".join("${}: {}".format(k, v)
                                                    for k, v in o["variables"].items())))
            if o["hash"]:
                print("      {}".format(o["hash"]))
    print("\nFull GraphQL for one: python tools/harvest_api_surface.py doc <name>")


def cmd_doc(args):
    for o in _load()["operations"]:
        if o["name"].lower() == args.operation.lower():
            print("# {}  ({})".format(o["name"], o["kind"]))
            print("# chunk: {}".format(o["chunk"]))
            print("# hash : {}".format(o["hash"] or "(unproven)"))
            print()
            print(o["document"])
            return
    sys.exit("{} not in the catalog".format(args.operation))


def cmd_diff(args):
    if not PREVIOUS.exists():
        sys.exit("no previous harvest to compare against (run extract twice)")
    new, old = _load(), json.loads(PREVIOUS.read_text(encoding="utf-8"))
    now = {o["name"]: o for o in new["operations"]}
    then = {o["name"]: o for o in old["operations"]}

    # --- build identity is the chunk set, never the CDN label (measured 2026-08-16: label
    #     unchanged across a build in which 902 of 967 chunks were new).
    nb, ob = _build_info(new), _build_info(old)
    if nb["fingerprint"] and ob["fingerprint"]:
        if nb["fingerprint"] != ob["fingerprint"]:
            print("BUILD CHANGED: {} -> {}{}".format(
                _build_tag(ob), _build_tag(nb),
                "   (same label -- the label is not a fingerprint)"
                if nb["label"] == ob["label"] else ""))
        else:
            print("build unchanged: {}".format(_build_tag(nb)))
    else:
        print("build      : {} -> {}   (a catalog from before 2026-08-16 carries no "
              "fingerprint; label alone cannot say whether the build changed)".format(
                  _build_tag(ob), _build_tag(nb)))
    if nb["chunks"] is not None and ob["chunks"] is not None:
        a, b = set(ob["chunks"]), set(nb["chunks"])
        print("chunks     ({} changed): {} kept, {} new, {} gone   [{} now, {} before]".format(
            len(a ^ b), len(a & b), len(b - a), len(a - b), len(b), len(a)))
    else:
        print("chunks     : n/a -- previous catalog carries no chunk list")

    added, gone = sorted(set(now) - set(then)), sorted(set(then) - set(now))
    moved = [n for n in sorted(set(now) & set(then)) if now[n]["hash"] != then[n]["hash"]]
    print("added      ({}): {}".format(len(added), ", ".join(added) or "-"))
    print("removed    ({}): {}".format(len(gone), ", ".join(gone) or "-"))
    print("hash moved ({}): {}".format(len(moved), ", ".join(moved) or "-"))
    if moved:
        print("\nA moved hash is why PersistedQueryNotFound shows up after a PixAI update.")
        print("Because hashes here are DERIVED, re-running fetch+extract re-pins them.")


# ---------------------------------------------------------------- replay
def cmd_replay(args):
    ops = {o["name"]: o for o in _load()["operations"]}
    o = ops.get(args.operation)
    if not o:
        sys.exit("{} is not in the catalog".format(args.operation))
    if o["kind"] != "query" or _looks_mutating(o["name"]):
        sys.exit("{} is a {}. Refusing -- mutations change the owner's account and are never "
                 "replayed by this tool.".format(o["name"], o["kind"]))
    if o["name"] not in REPLAY_ALLOWLIST and not args.force:
        sys.exit("{} is a query but not on the allowlist. Read its document first "
                 "(`doc {}`), then re-run with --force --reason '...'.".format(
                     o["name"], o["name"]))
    if not o["hash"]:
        sys.exit("hash unproven for {} -- refusing to send a guess.".format(o["name"]))

    core, session = _session()
    variables = json.loads(args.variables) if args.variables else {}
    r = session.get(core.API_URL, params={
        "operation": o["name"], "u3t": getattr(core, "U3T", "") or "",
        "operationName": o["name"],
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps({"clientLibrary": core.CLIENT_LIBRARY,
                                  "persistedQuery": {"version": 1, "sha256Hash": o["hash"]}},
                                 separators=(",", ":")),
    }, timeout=60)
    print("HTTP {}".format(r.status_code))
    try:
        body = r.json()
    except ValueError:
        print(r.text[:600])
        return
    print(json.dumps(body.get("errors") or body.get("data"), indent=2)[:4000])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    fe = sub.add_parser("fetch", help="crawl every JS chunk (cached; no GraphQL calls)")
    fe.add_argument("--max-chunks", type=int, default=1500)
    sub.add_parser("extract", help="mine ASTs into a catalog with derived hashes")
    sh = sub.add_parser("show", help="print the catalog")
    sh.add_argument("--grep", default="")
    dc = sub.add_parser("doc", help="print one operation's full GraphQL")
    dc.add_argument("operation")
    sub.add_parser("diff", help="what changed since the previous extract")
    rp = sub.add_parser("replay", help="call ONE read-only operation with your API key")
    rp.add_argument("operation")
    rp.add_argument("--variables", default="")
    rp.add_argument("--force", action="store_true")
    rp.add_argument("--reason", default="")
    args = ap.parse_args()
    {"fetch": cmd_fetch, "extract": cmd_extract, "show": cmd_show, "doc": cmd_doc,
     "diff": cmd_diff, "replay": cmd_replay}[args.cmd](args)


if __name__ == "__main__":
    main()
