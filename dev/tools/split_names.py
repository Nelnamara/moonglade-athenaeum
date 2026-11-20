"""Prove a split_move.py cut left every name its moved code reads meaning the same thing (3.22,
split Phase 5: the spend code leaves moonglade/backup.py).

    py dev/tools/split_names.py OLDREL NEWREL

OLDREL/NEWREL are repo-relative (moonglade/backup.py, moonglade/task_reads.py). Run it after
split_move.py's move, lazy and attrs steps and before the commit, so HEAD is the commit before
the move. The moved names come from <WORK>/<new>.names.json, which split_move.py's `move` wrote
(<WORK> is %TEMP%/moonglade_split unless MOONGLADE_SPLIT_WORK names another folder).

split_verify.py proves the TEXT moved verbatim. Verbatim text can still mean something else in
its new home: a global the code reads may be missing there, may be a different object there, or
may be a copy of state the old module rebinds at run time, which a test's patch of the old
module's binding (or the engine's own rebinding) never reaches. This tool proves the names.

  1. For each moved unit (a top-level function or class, and each moved top-level statement),
     the global names its code reads: the `co_names` of the unit's code object and of every
     code object nested in it, kept to the names a global-scope instruction uses (LOAD_GLOBAL,
     LOAD_NAME and their store/delete forms; `co_names` also holds attribute names, which are
     not lookups). Before the move from HEAD's OLDREL, compiled, never run; after it from
     NEWREL as it is now.
  2. Each name is resolved to the object it names. Before, in the old module: a name that
     moved is the new module's object, any other name is the old module's live binding, else a
     builtin. After, in the new module: a name the unit now imports inside itself (split_move's
     lazy `from moonglade.backup import X`) is that module's binding read at call time; else
     the new module's own global; else a builtin.
  3. It FAILS when a name resolves to a different object; when it resolves to a top-level copy
     in the new module of the old module's mutable state (3.22 design 3.2's list, READ_ONLY,
     USER_ID, API_URL, REST_API_BASE and _turbo_refused, plus every name the old module rebinds
     through a `global` statement), which must be read through the old module at call time;
     when it is a top-level copy of a name some test patches on the old module (the patch
     would no longer reach the moved code); when the moved code writes a global that stayed in
     the old module (it would write the new module's instead); when a module dunder other than
     a class body's implicit `__name__` is read (it changes with the module); or when a name
     does not resolve at all.
  4. Two sweeps outside the moved code: no function left in the old module reads a moved name
     as a bare global (it would be a NameError at call time), and no `from <old module> import
     X` anywhere in moonglade/ (an earlier split module's lazy imports included) names a
     moved X.

The last line is the summary that goes into the move commit's message, beside split_verify's.
Exit 1 on any failure.
"""
import ast
import builtins
import dis
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get("MOONGLADE_SPLIT_WORK")
            or Path(tempfile.gettempdir()) / "moonglade_split")

# 3.22 design 3.2: the module state the tests patch through `core`, read through moonglade.backup
# at call time, never copied.
STATE = ("READ_ONLY", "USER_ID", "API_URL", "REST_API_BASE", "_turbo_refused")

GLOBAL_OPS = {"LOAD_GLOBAL", "LOAD_NAME", "LOAD_FROM_DICT_OR_GLOBALS"}
STORE_OPS = {"STORE_GLOBAL", "DELETE_GLOBAL", "STORE_NAME", "DELETE_NAME"}


def _git_show(rel):
    out = subprocess.run(["git", "show", "HEAD:%s" % rel], cwd=REPO, capture_output=True,
                         text=True, encoding="utf-8")
    if out.returncode:
        sys.exit("git show HEAD:%s failed: %s" % (rel, out.stderr.strip()))
    return out.stdout


def _rp():
    spec = importlib.util.spec_from_file_location("rp", REPO / "dev" / "tools" / "retarget_patches.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _code_objects(code):
    """`code` and every code object nested in it."""
    yield code
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            yield from _code_objects(c)


def _global_reads(unit_code, is_class_body=False):
    """{name: {"load", "store"}} for the global-scope names the unit's code objects use. For a
    class body (LOAD_NAME), a name the body itself binds is the class's own, not a global."""
    found = {}
    for code in _code_objects(unit_code):
        own = set()
        if code is unit_code and is_class_body:
            own = {i.argval for i in dis.get_instructions(code) if i.opname == "STORE_NAME"}
        names = set(code.co_names)
        for ins in dis.get_instructions(code):
            if not isinstance(ins.argval, str) or ins.argval not in names:
                continue
            if ins.opname in GLOBAL_OPS:
                if ins.opname == "LOAD_NAME" and ins.argval in own:
                    continue
                if is_class_body and code is unit_code and ins.argval == "__name__":
                    continue            # the implicit `__module__ = __name__`
                found.setdefault(ins.argval, set()).add("load")
            elif ins.opname in STORE_OPS:
                if ins.opname in ("STORE_NAME", "DELETE_NAME") and code is not unit_code:
                    continue
                if ins.opname in ("STORE_NAME", "DELETE_NAME") and is_class_body:
                    continue            # class attributes
                found.setdefault(ins.argval, set()).add("store")
    return found


def _units(source, filename, wanted):
    """{name: (kind, code, ast node)} for the top-level statements of `source` that bind a name
    in `wanted`. A def/class maps to its own code object; any other statement to that one
    statement compiled as a module (it runs at import time)."""
    tree = ast.parse(source)
    module_code = compile(tree, filename, "exec")
    consts = [c for c in module_code.co_consts if isinstance(c, types.CodeType)]
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name not in wanted:
                continue
            lines = {node.lineno} | {d.lineno for d in node.decorator_list}
            hit = [c for c in consts if c.co_name == node.name and c.co_firstlineno in lines]
            if len(hit) != 1:
                raise SystemExit("cannot find the code object of %s in %s" % (node.name, filename))
            # What runs at import time, outside the unit's own code: decorators, default
            # arguments, a class's bases and keywords.
            exprs = list(node.decorator_list)
            if isinstance(node, ast.ClassDef):
                exprs += node.bases + [k.value for k in node.keywords]
            else:
                exprs += node.args.defaults + [d for d in node.args.kw_defaults if d is not None]
            head = None
            if exprs:
                head = compile(ast.fix_missing_locations(ast.Module(
                    body=[ast.Expr(ast.Tuple(elts=exprs, ctx=ast.Load()))], type_ignores=[])),
                    filename, "exec")
            out[node.name] = ("class" if isinstance(node, ast.ClassDef) else "def", hit[0], node,
                              head)
        else:
            bound = [s.id for s in ast.walk(node) if isinstance(s, ast.Name)
                     and isinstance(s.ctx, ast.Store)]
            mine = [b for b in bound if b in wanted]
            if not mine:
                continue
            code = compile(ast.Module(body=[node], type_ignores=[]), filename, "exec")
            for b in mine:
                out[b] = ("stmt", code, node, None)
    return out


def _in_function_imports(node):
    """{local name: (module, attribute)} for every `from M import a [as b]` inside the unit's
    functions (a method's, for a class): the names read at call time."""
    out = {}
    for sub in ast.walk(node):
        if isinstance(sub, ast.ImportFrom) and sub.col_offset > 0 and sub.module and not sub.level:
            for a in sub.names:
                out[a.asname or a.name] = (sub.module, a.name)
    return out


def _rebound_names(source):
    """Names a module rebinds at run time: every name in a `global` statement."""
    return {n for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Global)
            for n in node.names}


_MISSING = object()


def _describe(obj):
    if obj is _MISSING:
        return "(nothing)"
    if isinstance(obj, types.ModuleType):
        return "module %s" % obj.__name__
    mod = getattr(obj, "__module__", None)
    qual = getattr(obj, "__qualname__", None)
    if mod and qual and (callable(obj) or isinstance(obj, type)):
        return "%s.%s" % (mod, qual)
    return "%s at 0x%x" % (type(obj).__name__, id(obj))


def main(argv):
    if len(argv) != 2:
        sys.exit(__doc__)
    old_rel, new_rel = argv
    old_mod_name = "moonglade." + Path(old_rel).stem
    new_mod_name = "moonglade." + Path(new_rel).stem
    moved = json.loads((WORK / (Path(new_rel).stem + ".names.json")).read_text())
    moved_set = set(moved)

    sys.path.insert(0, str(REPO))
    old = importlib.import_module(old_mod_name)
    new = importlib.import_module(new_mod_name)

    head_src = _git_show(old_rel)
    new_src = (REPO / new_rel).read_text(encoding="utf-8")
    before_units = _units(head_src, old_rel, moved_set)
    after_units = _units(new_src, new_rel, moved_set)
    mutable = set(STATE) | _rebound_names(head_src)
    rp = _rp()
    patched = {(s.module, s.name) for scan in rp.scan_tree(REPO / "dev" / "tests")
               for s in scan.sites if s.name}

    failures, notes = [], []
    counts = {"names": 0, "same": 0, "call_time": 0, "copies": 0}
    missing_units = sorted(moved_set - set(after_units))
    for n in missing_units:
        failures.append("%s: moved, but %s does not define it" % (n, new_rel))
    for n in sorted(moved_set - set(before_units)):
        failures.append("%s: in the names list, but HEAD's %s does not define it" % (n, old_rel))

    pairs = []                          # (label, before code, after code, kind, lazy imports)
    done_codes = set()
    for name in moved:
        if name not in before_units or name not in after_units:
            continue
        b_kind, b_code, _, b_head = before_units[name]
        a_kind, a_code, a_node, a_head = after_units[name]
        if id(a_code) in done_codes:    # one statement binding several moved names
            continue
        done_codes.add(id(a_code))
        lazy = _in_function_imports(a_node) if a_kind != "stmt" else {}
        pairs.append((name, b_code, a_code, a_kind, lazy))
        if b_head or a_head:
            if not (b_head and a_head):
                failures.append("%s: its decorators/defaults/bases differ across the move" % name)
                continue
            pairs.append((name + " (at import time)", b_head, a_head, "stmt", {}))

    for name, b_code, a_code, kind, lazy in pairs:
        before = _global_reads(b_code, is_class_body=(kind == "class"))
        after = _global_reads(a_code, is_class_body=(kind == "class"))
        for n in sorted(set(after) - set(before) - set(lazy)):
            failures.append("%s: reads %s after the move but not before it (the text changed?)"
                            % (name, n))
        for n, ops in sorted(before.items()):
            counts["names"] += 1
            where = "%s reads %s" % (name, n)
            if n.startswith("__") and n.endswith("__"):
                failures.append("%s: a module dunder, which changes with the module" % where)
                continue
            if "store" in ops and n not in moved_set:
                failures.append("%s: it WRITES %s, which stays in %s; after the move it would "
                                "write %s's instead" % (where, n, old_mod_name, new_mod_name))
            # before: in the old module
            if n in moved_set:
                b_obj, b_from = new.__dict__.get(n, _MISSING), "moved"
            elif n in old.__dict__:
                b_obj, b_from = old.__dict__[n], "old"
            elif hasattr(builtins, n):
                b_obj, b_from = getattr(builtins, n), "builtin"
            else:
                failures.append("%s: did not resolve even before the move" % where)
                continue
            # after: in the new module
            if n in lazy:
                mod, attr = lazy[n]
                a_obj = getattr(importlib.import_module(mod), attr, _MISSING)
                a_from = "call-time %s.%s" % (mod, attr)
                if a_obj is _MISSING:
                    failures.append("%s: imported at call time from %s, which has no %s"
                                    % (where, mod, attr))
                    continue
            elif n in new.__dict__:
                a_obj, a_from = new.__dict__[n], "new"
            elif hasattr(builtins, n):
                a_obj, a_from = getattr(builtins, n), "builtin"
            else:
                failures.append("%s: does not resolve in %s" % (where, new_rel))
                continue
            if a_obj is not b_obj:
                failures.append("%s: was %s, is now %s (%s)" % (where, _describe(b_obj),
                                                                _describe(a_obj), a_from))
                continue
            counts["same"] += 1
            if a_from.startswith("call-time"):
                counts["call_time"] += 1
                continue
            if b_from == "old" and a_from == "new":
                if isinstance(a_obj, types.ModuleType):
                    continue
                counts["copies"] += 1
                if n in mutable:
                    failures.append("%s: a top-level copy of %s.%s, state the engine or a test "
                                    "rebinds; read it through %s at call time"
                                    % (where, old_mod_name, n, old_mod_name))
                elif (old_mod_name, n) in patched:
                    failures.append("%s: a top-level copy of %s.%s, which a test patches there; "
                                    "the patch would no longer reach the moved code"
                                    % (where, old_mod_name, n))
                else:
                    notes.append("%s: top-level copy of %s.%s (%s)" % (where, old_mod_name, n,
                                                                     _describe(a_obj)))

    # Sweep 1: what stayed in the old module still reaches every moved name.
    cur_old = (REPO / old_rel).read_text(encoding="utf-8")
    stay_reads = set()
    for code in _code_objects(compile(cur_old, old_rel, "exec")):
        stay_reads |= {i.argval for i in dis.get_instructions(code)
                       if i.opname in GLOBAL_OPS and isinstance(i.argval, str)}
    for n in sorted(stay_reads & moved_set):
        if n not in old.__dict__:
            failures.append("%s still reads %s as a bare global; it moved to %s"
                            % (old_rel, n, new_rel))

    # Sweep 2: no from-import in the package names a moved name at its old home.
    stale = 0
    for p in sorted((REPO / "moonglade").glob("*.py")):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module == old_mod_name and not node.level:
                for a in node.names:
                    if a.name in moved_set:
                        stale += 1
                        failures.append("moonglade/%s:%d imports %s from %s; it moved to %s"
                                        % (p.name, node.lineno, a.name, old_mod_name,
                                           new_mod_name))

    for line in notes:
        print("   note:", line)
    for line in failures:
        print("FAIL:", line)
    units = len({id(u[1]) for u in after_units.values()})
    print("split_names: %s -> %s: %d units, %d global reads: %d the same object (%d at call "
          "time through their old home, %d top-level copies), %d failure(s); old-module and "
          "package import sweeps %s -- %s"
          % (old_rel, new_rel, units, counts["names"], counts["same"], counts["call_time"],
             counts["copies"], len(failures), "clean" if not stale else "NOT clean",
             "PASS" if not failures else "FAIL"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
