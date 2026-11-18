"""The 3.21.0 megamodule split's mover: cut a section out of moonglade/backup.py or gallery.py
VERBATIM into a new module and rewire only what has to change.

A move is several commands, run from the repo root (`py dev/tools/split_move.py <cmd> ...`):

  analyze  OLDFILE START END [EXTRA_LINE ...]
      No writes. The top-level names lines START..END (plus any single EXTRA_LINEs elsewhere,
      e.g. a constant the section reads at import time) define, the names the block uses but
      does not define (what it needs from the old module), how many bare references to the
      moved names the old module keeps, and any CONFLICT (a moved name rebound locally or by a
      `global` statement), which stops a move.
  move     OLDFILE START END NEWFILE HEADERFILE ALIAS [EXTRA_LINE ...]
      Cuts the block into NEWFILE (HEADERFILE's text, typically the docstring and the top-level
      imports, then the block untouched), leaves two blank lines at the seam, rewrites the old
      module's bare references to the moved names as ALIAS.name (scope-aware: a local that
      shadows one is left alone) and adds `from moonglade import <new> as ALIAS` to its
      top-level `from moonglade import` run. Writes the moved names to
      <WORK>/<new>.names.json for the commands below and split_verify.py.
  attrs    OLDMOD NEWMOD ALIAS NAMESFILE FILE...
      In other files (production importers, tests): `<old alias>.name`, getattr/hasattr(<old
      alias>, "name") and `from OLDMOD import name` for the moved names now go to NEWMOD (an
      existing alias of NEWMOD in the file is reused, else `from moonglade import <new> as
      ALIAS` is added). Patches are NOT this command's job: dev/tools/retarget_patches.py moves
      those, from the SEAMS map.
  lazy     NEWFILE MAPFILE
      MAPFILE is {module: [names]}: inserts `from <module> import <names>` as the first
      statement of every top-level function in NEWFILE that uses them (the lazy-import rule:
      a new module never imports backup/gallery at import time). Reports a use outside any
      function, which cannot be made lazy.
  grep     NAMESFILE FILE...
      Every `.name` attribute use of a moved name left in FILEs: a review list.

<WORK> is %TEMP%/moonglade_split unless MOONGLADE_SPLIT_WORK names another folder.
Then: split_verify.py proves the cut is verbatim; add the SEAMS entry; run retarget_patches.py.
"""
import ast
import builtins
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get("MOONGLADE_SPLIT_WORK")
            or Path(tempfile.gettempdir()) / "moonglade_split")
_spec = importlib.util.spec_from_file_location("rp", REPO / "dev" / "tools" / "retarget_patches.py")
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)


def read(p):
    with open(p, encoding="utf-8", newline="") as fh:
        return fh.read()


def write(p, text):
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def top_defines(src):
    names = []
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Name) and sub.id not in names:
                        names.append(sub.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            pass
    return names


def cut(text, start, end, extra):
    lines = text.splitlines(keepends=True)
    idx = set(range(start - 1, end))
    extra_lines = [lines[i - 1] for i in extra]
    block = "".join(lines[start - 1:end])
    keep = [l for i, l in enumerate(lines) if i not in idx and (i + 1) not in extra]
    return block, extra_lines, keep, start - 1 - sum(1 for e in extra if e < start)


def name_edits(text, names):
    """Bare Name nodes referring to the module-global `names` -> (edits, conflicts)."""
    model = rp.FileModel(text)
    names = set(names)
    edits, conflicts = [], []
    for node in ast.walk(model.tree):
        if isinstance(node, ast.Name) and node.id in names:
            scope = model.scope_for(node)
            bound_in = None
            for s in model._chain(scope):
                if node.id in s.bindings:
                    bound_in = s
                    break
            if bound_in is None:
                edits.append(node)
            else:
                where = "module" if bound_in is model.scopes[0] else getattr(bound_in.node, "name", "?")
                conflicts.append((node.lineno, node.id, where, type(node.ctx).__name__))
        elif isinstance(node, ast.Global):
            for n in node.names:
                if n in names:
                    conflicts.append((node.lineno, n, "global-stmt", ""))
    return edits, conflicts


def apply_name_edits(text, nodes, alias):
    lines = text.splitlines(keepends=True)
    by_line = {}
    for n in nodes:
        assert n.lineno == n.end_lineno
        by_line.setdefault(n.lineno, []).append(n)
    for ln, ns in by_line.items():
        raw = lines[ln - 1].encode("utf-8")
        for n in sorted(ns, key=lambda n: n.col_offset, reverse=True):
            seg = raw[n.col_offset:n.end_col_offset].decode("utf-8")
            assert seg == n.id, (ln, seg, n.id)
            raw = raw[:n.col_offset] + ("%s.%s" % (alias, n.id)).encode("utf-8") + raw[n.end_col_offset:]
        lines[ln - 1] = raw.decode("utf-8")
    return "".join(lines)


def free_names(block):
    """Names the block loads that it neither defines, imports, nor gets from builtins."""
    model = rp.FileModel(block)
    out = set()
    for node in ast.walk(model.tree):
        if isinstance(node, ast.Name):
            if node.id in dir(builtins):
                continue
            found = any(node.id in s.bindings for s in model._chain(model.scope_for(node)))
            if not found:
                out.add(node.id)
    return sorted(out)


def insert_import(text, line):
    """Insert `line` into the top-level run of `from moonglade import X as Y` lines, alphabetically."""
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text)
    runs = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "moonglade"
            and n.col_offset == 0]
    assert runs, "no top-level `from moonglade import` lines"
    pos = None
    for n in runs:
        if lines[n.lineno - 1].strip() > line.strip():
            pos = n.lineno - 1
            break
    if pos is None:
        pos = runs[-1].end_lineno
    nl = "\r\n" if lines[0].endswith("\r\n") else "\n"
    lines[pos:pos] = [line.rstrip() + nl]
    return "".join(lines)


def cmd_analyze(old, start, end, extra):
    text = read(old)
    block, extra_lines, keep, _ = cut(text, start, end, extra)
    moved = top_defines("".join(extra_lines) + block)
    print("MOVED", len(moved), moved)
    print("FREE in block:", free_names("".join(extra_lines) + block))
    rest = "".join(keep)
    edits, conflicts = name_edits(rest, moved)
    print("bare refs to rewrite:", len(edits))
    for c in conflicts:
        print("CONFLICT", c)


def cmd_move(old, start, end, new, header, alias, extra):
    text = read(old)
    block, extra_lines, keep, at = cut(text, start, end, extra)
    moved = top_defines("".join(extra_lines) + block)
    # tidy the seam: exactly two blank lines where the block was
    before, after = keep[:at], keep[at:]
    while before and before[-1].strip() == "":
        before.pop()
    while after and after[0].strip() == "":
        after.pop(0)
    nl = "\n"
    rest = "".join(before) + nl + nl + "".join(after) if after else "".join(before) + nl
    edits, conflicts = name_edits(rest, moved)
    if conflicts:
        print("CONFLICTS -- not written:")
        for c in conflicts:
            print("  ", c)
        return 1
    rest = apply_name_edits(rest, edits, alias)
    base = Path(new).stem
    rest = insert_import(rest, "from moonglade import %s as %s" % (base, alias))
    ast.parse(rest)
    head = read(header).lstrip("﻿").replace("\r\n", "\n")
    new_text = head + "".join(extra_lines) + ("\n\n" if extra_lines else "\n") + block
    if not new_text.endswith("\n"):
        new_text += "\n"
    ast.parse(new_text)
    write(old, rest)
    write(new, new_text)
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / (Path(new).stem + ".names.json")).write_text(json.dumps(moved))
    print("moved %d names, %d bare refs rewritten" % (len(moved), len(edits)))
    print(json.dumps(moved))
    return 0


def cmd_attrs(oldmod, newmod, alias, namesfile, files):
    names = set(json.loads(Path(namesfile).read_text()))
    pkg, base = newmod.rsplit(".", 1)
    total = 0
    for f in files:
        text = read(f)
        model = rp.FileModel(text)
        lines = text.splitlines(keepends=True)
        spans = []          # (line, c0, c1, replacement)
        line_repl = {}      # whole-line ImportFrom rewrites: lineno -> (end_lineno, new text)
        used_alias = False
        existing = rp._existing_alias(model, newmod)
        use = existing or alias
        for node in ast.walk(model.tree):
            scope = model.scope_for(node)
            if isinstance(node, ast.Attribute) and node.attr in names:
                if model.resolve_expr(node.value, scope) == oldmod:
                    v = node.value
                    assert v.lineno == v.end_lineno
                    spans.append((v.lineno, v.col_offset, v.end_col_offset, use))
                    used_alias = True
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id in ("getattr", "hasattr") and len(node.args) >= 2
                  and isinstance(node.args[1], ast.Constant) and node.args[1].value in names
                  and model.resolve_expr(node.args[0], scope) == oldmod):
                v = node.args[0]
                spans.append((v.lineno, v.col_offset, v.end_col_offset, use))
                used_alias = True
            elif isinstance(node, ast.ImportFrom) and node.module == oldmod and not node.level:
                hit = [a for a in node.names if a.name in names]
                if not hit:
                    continue
                stay = [a for a in node.names if a.name not in names]
                indent = lines[node.lineno - 1][:node.col_offset]
                nl = "\r\n" if lines[node.lineno - 1].endswith("\r\n") else "\n"

                def fmt(mod, al):
                    parts = [a.name + (" as " + a.asname if a.asname else "") for a in al]
                    one = "%sfrom %s import %s" % (indent, mod, ", ".join(parts))
                    if len(one) <= 99:
                        return one + nl
                    # wrap in parens, keeping lines under 100
                    out, cur = [], "%sfrom %s import (" % (indent, mod)
                    pad = " " * len(cur)
                    for i, p in enumerate(parts):
                        piece = p + ("," if i < len(parts) - 1 else ")")
                        if len(cur) + len(piece) + 1 > 99 and cur.strip() not in ("",) and not cur.endswith("("):
                            out.append(cur.rstrip() + nl)
                            cur = pad + piece
                        else:
                            cur = cur + ("" if cur.endswith("(") else " ") + piece
                    out.append(cur + nl)
                    return "".join(out)
                new = (fmt(oldmod, stay) if stay else "") + fmt(newmod, hit)
                line_repl[node.lineno] = (node.end_lineno, new)
        if not spans and not line_repl:
            continue
        by_line = {}
        for ln, c0, c1, rep in spans:
            by_line.setdefault(ln, []).append((c0, c1, rep))
        for ln, es in by_line.items():
            raw = lines[ln - 1].encode("utf-8")
            for c0, c1, rep in sorted(es, reverse=True):
                raw = raw[:c0] + rep.encode("utf-8") + raw[c1:]
            lines[ln - 1] = raw.decode("utf-8")
        for ln in sorted(line_repl, reverse=True):
            end, new = line_repl[ln]
            lines[ln - 1:end] = [new]
        out = "".join(lines)
        if used_alias and not existing:
            nl = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
            at = rp._import_insert_line(rp.FileModel(text))
            # recompute against new text: insert after last top-level import
            m2 = rp.FileModel(out)
            at = rp._import_insert_line(m2)
            ol = out.splitlines(keepends=True)
            ol[at:at] = ["from %s import %s as %s%s" % (pkg, base, alias, nl)]
            out = "".join(ol)
        ast.parse(out)
        write(f, out)
        n = len(spans) + len(line_repl)
        total += n
        print("%s: %d attr/getattr, %d from-import" % (f, len(spans), len(line_repl)))
    print("total", total)


def cmd_lazy(newfile, mapfile):
    """Insert `from <mod> import names` as the first statement (after the docstring) of every
    top-level function in newfile that uses one of the mapped names. mapfile: {mod: [names]}."""
    mapping = json.loads(Path(mapfile).read_text())
    owner = {n: m for m, ns in mapping.items() for n in ns}
    text = read(newfile)
    model = rp.FileModel(text)
    lines = text.splitlines(keepends=True)
    nl = "\r\n" if lines[0].endswith("\r\n") else "\n"
    inserts = []
    problems = []
    for node in model.tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            used = {}
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id in owner:
                    chain = list(model._chain(model.scope_for(sub)))
                    if any(sub.id in s.bindings for s in chain):
                        continue
                    used.setdefault(owner[sub.id], [])
                    if sub.id not in used[owner[sub.id]]:
                        used[owner[sub.id]].append(sub.id)
            if not used:
                continue
            body = node.body
            first = body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                at = first.end_lineno
                ref = body[1] if len(body) > 1 else first
            else:
                at = first.lineno - 1
                ref = first
            indent = lines[ref.lineno - 1][:ref.col_offset]
            new = []
            for mod in sorted(used):
                names = sorted(used[mod], key=lambda n: (n.lower().lstrip("_"), n))
                one = "%sfrom %s import %s" % (indent, mod, ", ".join(names))
                if len(one) <= 99:
                    new.append(one + nl)
                else:
                    head = "%sfrom %s import (" % (indent, mod)
                    pad = " " * len(head)
                    cur = head
                    for i, n in enumerate(names):
                        piece = n + ("," if i < len(names) - 1 else ")")
                        if len(cur) + len(piece) + 1 > 99 and not cur.endswith("("):
                            new.append(cur.rstrip() + nl)
                            cur = pad + piece
                        else:
                            cur += ("" if cur.endswith("(") else " ") + piece
                    new.append(cur + nl)
            inserts.append((at, new, node.name, used))
        else:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id in owner:
                    problems.append((sub.lineno, sub.id))
    for at, new, name, used in sorted(inserts, reverse=True):
        lines[at:at] = new
        print("%s: %s" % (name, used))
    for p in problems:
        print("MODULE-LEVEL USE (cannot be lazy):", p)
    out = "".join(lines)
    ast.parse(out)
    write(newfile, out)
    return 1 if problems else 0


def cmd_grep(namesfile, files):
    names = json.loads(Path(namesfile).read_text())
    pat = re.compile(r"\.(%s)\b" % "|".join(map(re.escape, names)))
    for f in files:
        for i, line in enumerate(read(f).splitlines(), 1):
            if pat.search(line) and not line.lstrip().startswith("#"):
                print("%s:%d: %s" % (f, i, line.strip()[:160]))


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0]
    if cmd == "analyze":
        sys.exit(cmd_analyze(a[1], int(a[2]), int(a[3]), [int(x) for x in a[4:]]))
    if cmd == "move":
        sys.exit(cmd_move(a[1], int(a[2]), int(a[3]), a[4], a[5], a[6], [int(x) for x in a[7:]]))
    if cmd == "attrs":
        sys.exit(cmd_attrs(a[1], a[2], a[3], a[4], a[5:]))
    if cmd == "lazy":
        sys.exit(cmd_lazy(a[1], a[2]))
    if cmd == "grep":
        sys.exit(cmd_grep(a[1], a[2:]))
