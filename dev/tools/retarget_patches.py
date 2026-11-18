"""Retarget test patches after a symbol moves out of a megamodule (3.21.0 split, item 9).

THE PROBLEM. A patch only works if it targets the module whose code does the lookup. When a
name moves from `moonglade.backup` (or `moonglade.gallery`) into a new module, a test that still
says `monkeypatch.setattr(core, "name", fake)` patches the OLD module: a loud AttributeError if
the old module no longer has the name, a silent no-op if it still does (a re-export), and
always silent for a plain `core.name = fake`. This tool finds those sites and moves them.

ONE SOURCE OF TRUTH. The moves are the `SEAMS` map in dev/tests/test_module_seams.py, read
here with ast.literal_eval (so SEAMS must stay a plain literal) -- this tool never imports the
test, and the test loads this file by path for its scanner. Shape:

    SEAMS = {"moonglade.newmod": {"from": "moonglade.gallery", "names": ["a", "b"]}}

WHAT IT RECOGNISES (per test file, aliases derived from the file's own imports, scope by scope):
    monkeypatch.setattr(<alias>, "name", ...)      (any `.setattr`/`.delattr`, builtin setattr too)
    monkeypatch.setattr("moonglade.backup.name", ...)
    mock.patch("moonglade.gallery.name")           (`patch`, `mock.patch`, `mocker.patch`, decorators)
    patch.object(<alias>, "name")                   (`mock.patch.object`, `mocker.patch.object`)
    <alias>.name = ... / <alias>.name.attr = ... / del <alias>.name / <alias>.name += ...
    and a receiver chain rooted at the module: monkeypatch.setattr(core.Client, "get", ...)
An alias is any name bound to the module by `import moonglade.backup as x`, `from moonglade
import gallery as x`, `import moonglade.gallery` (then `moonglade.gallery.name`),
`x = importlib.import_module("moonglade.backup")`, or `x = <another alias>`.

CONSERVATIVE. Text-level edits of exactly the alias expression (or the dotted string), checked
by re-parsing the result. A site whose receiver it cannot resolve to a module (a fixture
parameter, a name bound two ways, a computed string, `patch.multiple`) is REPORTED, never
guessed -- except a computed name that is the variable of an enclosing `for name in ("a",
"b")` over string literals, which is checked against those literals (reported only if one of
them moved). `--dry-run` (the default) prints `file:line old_target -> new_target`; `--apply`
rewrites and adds `from moonglade import <mod> as <alias>` to each touched file.

    py dev/tools/retarget_patches.py                 # dry run over dev/tests
    py dev/tools/retarget_patches.py --apply
    py dev/tools/retarget_patches.py --seams X.py --tests DIR --alias moonglade.scan=scan_mod
"""
import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_SEAMS = REPO / "dev" / "tests" / "test_module_seams.py"
DEFAULT_TESTS = REPO / "dev" / "tests"
OLD_MODULES = ("moonglade.backup", "moonglade.gallery")

AMBIGUOUS = "<ambiguous>"          # a name bound to a module AND to something else in one scope
_SOURCE_FUNCS = {"getsource", "getsourcelines", "getsourcefile", "getfile"}
_MODULE_PATH_RE = re.compile(r"^(?:.*[/\\])?(backup|gallery)\.py$")


# ---------------------------------------------------------------------------------------------
# The SEAMS map
# ---------------------------------------------------------------------------------------------

def load_seams(path=DEFAULT_SEAMS):
    """The SEAMS literal from the test module, without importing it."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        if any(isinstance(t, ast.Name) and t.id == "SEAMS" for t in targets):
            return ast.literal_eval(node.value)
    raise ValueError("no SEAMS = {...} literal at the top level of %s" % path)


def moved_index(seams):
    """{(old_module, name): new_module} -- every moved name, keyed by where it used to live."""
    out = {}
    for new_mod, entry in seams.items():
        for name in entry["names"]:
            out[(entry["from"], name)] = new_mod
    return out


# ---------------------------------------------------------------------------------------------
# Scope-aware alias resolution
# ---------------------------------------------------------------------------------------------

_SCOPE_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


class _Scope:
    def __init__(self, node, parent):
        self.node = node
        self.parent = parent
        self.is_class = isinstance(node, ast.ClassDef)
        self.bindings = {}        # name -> set of ("mod", "moonglade.x") | ("copy", "alias") | ("other", None)

    def bind(self, name, kind):
        self.bindings.setdefault(name, set()).add(kind)


def _direct_children(node):
    """Child nodes that run in this node's scope (not the bodies of nested defs/lambdas/classes)."""
    for child in ast.iter_child_nodes(node):
        yield child


def _import_module_target(value):
    """'moonglade.backup' for `importlib.import_module("moonglade.backup")`, else None."""
    if (isinstance(value, ast.Call) and value.args
            and isinstance(value.args[0], ast.Constant) and isinstance(value.args[0].value, str)):
        f = value.func
        fname = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
        if fname == "import_module":
            return value.args[0].value
    return None


def _bind_target(scope, target):
    if isinstance(target, ast.Name):
        scope.bind(target.id, ("other", None))
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            _bind_target(scope, elt)
    elif isinstance(target, ast.Starred):
        _bind_target(scope, target.value)


class FileModel:
    """One parsed file: its scope tree and a resolver from expressions to module names."""

    def __init__(self, text, package_hint="moonglade"):
        self.text = text
        self.tree = ast.parse(text)
        self.package_hint = package_hint
        self.scope_of = {}            # id(node) -> _Scope the node's code runs in
        self.scopes = []
        self._build(self.tree, None)

    # -- building ------------------------------------------------------------------------
    def _build(self, scope_node, parent):
        scope = _Scope(scope_node, parent)
        self.scopes.append(scope)
        if isinstance(scope_node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = scope_node.args
            for arg in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg]:
                if arg is not None:
                    scope.bind(arg.arg, ("other", None))
        stack = [scope_node.body] if isinstance(scope_node, ast.Lambda) else list(scope_node.body)
        while stack:
            node = stack.pop()
            self.scope_of[id(node)] = scope
            if isinstance(node, _SCOPE_TYPES) and node is not scope_node:
                if not isinstance(node, ast.Lambda):
                    scope.bind(node.name, ("other", None))
                    for d in node.decorator_list:
                        stack.append(d)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    a = node.args
                    for dflt in a.defaults + [d for d in a.kw_defaults if d is not None]:
                        stack.append(dflt)
                if isinstance(node, ast.ClassDef):
                    stack.extend(node.bases)
                    stack.extend(k.value for k in node.keywords)
                self._build(node, scope)
                continue
            self._collect_binding(scope, node)
            stack.extend(_direct_children(node))

    def _collect_binding(self, scope, node):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    scope.bind(a.asname, ("mod", a.name))
                else:
                    top = a.name.split(".")[0]
                    scope.bind(top, ("mod", top))
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = (self.package_hint + ("." + base if base else "")) if node.level == 1 else None
            for a in node.names:
                name = a.asname or a.name
                if base is None or a.name == "*":
                    scope.bind(name, ("other", None))
                    continue
                # `from moonglade import backup` binds a MODULE; `from moonglade.backup import x`
                # binds an attribute (recorded as a from-import elsewhere, an "other" binding here).
                full = base + "." + a.name
                if full in OLD_MODULES or (base == self.package_hint):
                    scope.bind(name, ("mod", full))
                else:
                    scope.bind(name, ("other", None))
        elif isinstance(node, ast.Assign):
            target_mod = _import_module_target(node.value)
            for t in node.targets:
                if isinstance(t, ast.Name):
                    if target_mod:
                        scope.bind(t.id, ("mod", target_mod))
                    elif isinstance(node.value, ast.Name):
                        scope.bind(t.id, ("copy", node.value.id))
                    else:
                        scope.bind(t.id, ("other", None))
                else:
                    _bind_target(scope, t)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            _bind_target(scope, node.target)
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            _bind_target(scope, node.target)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    _bind_target(scope, item.optional_vars)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            scope.bind(node.name, ("other", None))
        elif isinstance(node, ast.NamedExpr):
            _bind_target(scope, node.target)

    # -- resolving -----------------------------------------------------------------------
    def _chain(self, scope):
        first = True
        while scope is not None:
            if first or not scope.is_class:
                yield scope
            first = False
            scope = scope.parent

    def resolve_name(self, name, scope, _seen=None):
        """The module a bare name refers to in `scope`: a dotted module name, AMBIGUOUS, or None
        (bound to something that is not a module, or not bound in this file at all)."""
        _seen = _seen or set()
        if (name, id(scope)) in _seen:
            return AMBIGUOUS
        _seen.add((name, id(scope)))
        for s in self._chain(scope):
            kinds = s.bindings.get(name)
            if not kinds:
                continue
            results = set()
            for kind, val in kinds:
                if kind == "mod":
                    results.add(val)
                elif kind == "copy":
                    results.add(self.resolve_name(val, s, _seen))
                else:
                    results.add(None)
            if len(results) == 1:
                return results.pop()
            return AMBIGUOUS
        return None

    def resolve_expr(self, expr, scope):
        """Module name for a Name / dotted Attribute chain that denotes a module, else None."""
        if isinstance(expr, ast.Name):
            return self.resolve_name(expr.id, scope)
        if isinstance(expr, ast.Attribute):
            base = self.resolve_expr(expr.value, scope)
            if base and base != AMBIGUOUS:
                full = base + "." + expr.attr
                if full in OLD_MODULES or base == self.package_hint:
                    return full
        return None

    def scope_for(self, node):
        return self.scope_of.get(id(node), self.scopes[0])

    def segment(self, node):
        return ast.get_source_segment(self.text, node)


# ---------------------------------------------------------------------------------------------
# The scanner
# ---------------------------------------------------------------------------------------------

@dataclass
class Site:
    """One patch that names `name` on `module`. `span` is the exact text to replace: the
    expression that denotes the module (kind "expr") or the whole string literal (kind "string").
    module is a dotted name, AMBIGUOUS, or None (receiver not resolvable to a module)."""
    path: str
    line: int
    form: str                 # setattr / delattr / patch / patch.object / assign / ...
    module: object
    name: str
    kind: str                 # "expr" | "string" | "dynamic"
    span: tuple = None        # (lineno, col, end_lineno, end_col) of the node to rewrite
    text: str = ""            # the source text of that node
    candidates: tuple = None  # a "dynamic" name that is the variable of an enclosing
                              # `for name in ("a", "b")`: the literals it takes


@dataclass
class FileScan:
    path: str
    aliases: list = field(default_factory=list)       # (name, module) bound to an old module
    sites: list = field(default_factory=list)         # Site
    from_imports: list = field(default_factory=list)  # (line, module, name)
    reads_source: dict = field(default_factory=dict)  # old module -> "whole" | "indirect" | "names"
    error: str = ""


def _span(node):
    return (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)


def _func_kind(func):
    """'setattr' | 'delattr' | 'patch' | 'patch.object' | 'patch.multiple' | None."""
    if isinstance(func, ast.Name):
        if func.id in ("setattr", "delattr", "patch"):
            return func.id
        return None
    if isinstance(func, ast.Attribute):
        if func.attr in ("setattr", "delattr"):
            return func.attr
        if func.attr == "patch":
            return "patch"
        inner = func.value
        inner_is_patch = ((isinstance(inner, ast.Name) and inner.id == "patch")
                          or (isinstance(inner, ast.Attribute) and inner.attr == "patch"))
        if inner_is_patch and func.attr in ("object", "multiple"):
            return "patch." + func.attr
    return None


def _str_const(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _module_prefix(model, expr, scope):
    """For `core.A.B`: (span_node=core, module, 'A'); for a bare module expr: (expr, module, None).
    Returns None when no prefix of the chain denotes a module."""
    mod = model.resolve_expr(expr, scope)
    if mod is not None:
        return expr, mod, None
    if isinstance(expr, ast.Attribute):
        node = expr
        while isinstance(node, ast.Attribute):
            inner = node.value
            mod = model.resolve_expr(inner, scope)
            if mod is not None:
                return inner, mod, node.attr
            node = inner
    return None


_READ_RANK = {"names": 0, "indirect": 1, "whole": 2}


def _mark(reads, mod, kind):
    """Record how a file reads a module's source, keeping the widest: "whole" (the module's
    text: getsource(module), a path read, __file__), "indirect" (getsource of something this
    scanner cannot trace), "names" (getsource of named functions only)."""
    if _READ_RANK[kind] > _READ_RANK.get(reads.get(mod), -1):
        reads[mod] = kind


def _is_path_read(const, parents):
    """A "backup.py"/"gallery.py" string used as a path to open: a `/` operand
    (ROOT / "moonglade" / "gallery.py"), an argument of a call that is not a patch
    (Path("moonglade/gallery.py"), _read(...)), or a "moonglade/..." element of a tuple/list a
    loop iterates. Not an argv list, a dict key, or a list of names to compare."""
    parent = parents.get(id(const))
    if isinstance(parent, ast.BinOp) and isinstance(parent.op, ast.Div):
        return True
    if isinstance(parent, ast.Call) and const in parent.args:
        return _func_kind(parent.func) is None
    if isinstance(parent, (ast.Tuple, ast.List)) and const.value.startswith("moonglade/"):
        loop = parents.get(id(parent))
        return isinstance(loop, (ast.For, ast.comprehension)) and loop.iter is parent
    return False


def _loop_literals(name_node, node, parents):
    """The string literals a computed patch name takes when it is the variable of the nearest
    enclosing `for <name> in ("a", "b", ...)` (a tuple or list of string literals only), else
    None. Stops at the enclosing def/lambda/class."""
    if not isinstance(name_node, ast.Name):
        return None
    cur = parents.get(id(node))
    while cur is not None and not isinstance(cur, _SCOPE_TYPES):
        if (isinstance(cur, (ast.For, ast.AsyncFor)) and isinstance(cur.target, ast.Name)
                and cur.target.id == name_node.id):
            elts = cur.iter.elts if isinstance(cur.iter, (ast.Tuple, ast.List)) else []
            if elts and all(_str_const(e) is not None for e in elts):
                return tuple(e.value for e in elts)
            return None
        cur = parents.get(id(cur))
    return None


def _root_name(expr):
    while isinstance(expr, (ast.Attribute, ast.Subscript, ast.Call)):
        expr = expr.value if not isinstance(expr, ast.Call) else expr.func
    return expr.id if isinstance(expr, ast.Name) else None


def scan_text(path, text, old_modules=OLD_MODULES):
    """Scan one file's text. Never raises on a syntax error (recorded in .error)."""
    out = FileScan(path=str(path))
    try:
        model = FileModel(text)
    except SyntaxError as exc:
        out.error = "syntax error: %s" % exc
        return out
    for scope in model.scopes:
        for name, kinds in scope.bindings.items():
            for kind, val in kinds:
                if kind == "mod" and val in old_modules:
                    out.aliases.append((name, val))

    def add(node, form, module, name, kind, span_node, candidates=None):
        out.sites.append(Site(path=str(path), line=node.lineno, form=form, module=module,
                              name=name, kind=kind,
                              span=_span(span_node) if span_node is not None else None,
                              text=model.segment(span_node) if span_node is not None else "",
                              candidates=candidates))

    def receiver_site(node, form, receiver, name_node, scope):
        hit = _module_prefix(model, receiver, scope)
        if hit is not None:
            span_node, mod, attr = hit
            if mod in old_modules:
                if attr is not None:                     # core.Client, "get": the moved name is Client
                    add(node, form, mod, attr, "expr", span_node)
                else:
                    name = _str_const(name_node) if name_node is not None else None
                    if name is not None:
                        add(node, form, mod, name, "expr", span_node)
                    elif name_node is not None:
                        add(node, form, mod, "", "dynamic", None,
                            _loop_literals(name_node, node, parents))
            elif mod == AMBIGUOUS:
                name = _str_const(name_node) if name_node is not None else None
                add(node, form, AMBIGUOUS, attr or name or "", "dynamic", None)
            return
        # Receiver is not a module expression: only interesting if its name could be a moved one.
        name = _str_const(name_node) if name_node is not None else None
        root = _root_name(receiver)
        if name and isinstance(receiver, ast.Name) and model.resolve_name(root, scope) is None:
            add(node, form, None, name, "dynamic", None)

    def string_site(node, form, target_node):
        target = _str_const(target_node)
        if target is None:
            if isinstance(target_node, ast.JoinedStr):
                seg = model.segment(target_node) or ""
                if any(m in seg for m in old_modules):
                    add(node, form, None, "", "dynamic", None)
            return
        for mod in old_modules:
            if target.startswith(mod + "."):
                name = target[len(mod) + 1:].split(".")[0]
                add(node, form, mod, name, "string", target_node)

    def target_site(node, form, target, scope):
        if isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                target_site(node, form, elt, scope)
            return
        if isinstance(target, ast.Starred):
            target_site(node, form, target.value, scope)
            return
        if isinstance(target, (ast.Attribute, ast.Subscript)):
            hit = _module_prefix(model, target, scope)
            if hit is not None:
                span_node, mod, attr = hit
                if mod in old_modules and attr is not None:
                    add(node, form, mod, attr, "expr", span_node)

    parents = {}
    for node in ast.walk(model.tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node

    for node in ast.walk(model.tree):
        scope = model.scope_for(node)
        if isinstance(node, ast.Call):
            kind = _func_kind(node.func)
            args = node.args
            if kind in ("setattr", "delattr") and args:
                if _str_const(args[0]) is not None and (
                        kind == "setattr" and len(args) == 2 or kind == "delattr" and len(args) == 1):
                    string_site(node, kind, args[0])           # monkeypatch.setattr("a.b.c", v)
                else:
                    receiver_site(node, kind, args[0], args[1] if len(args) > 1 else None, scope)
            elif kind == "patch":
                tgt = args[0] if args else next((k.value for k in node.keywords if k.arg == "target"), None)
                if tgt is not None:
                    string_site(node, "patch", tgt)
            elif kind == "patch.object" and args:
                receiver_site(node, kind, args[0], args[1] if len(args) > 1 else None, scope)
            elif kind == "patch.multiple" and args:
                hit = _module_prefix(model, args[0], scope)
                if hit is not None and hit[1] in old_modules:
                    for k in node.keywords:
                        if k.arg:
                            add(node, kind, None, k.arg, "dynamic", None)
            # Source readers: inspect.getsource(core.x), getsource(g), getsource(fn) ...
            fname = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if fname in _SOURCE_FUNCS and args:
                found_old, unknown = set(), False
                for sub in ast.walk(args[0]):
                    if isinstance(sub, (ast.Name, ast.Attribute)):
                        mod = model.resolve_expr(sub, scope)
                        if mod in old_modules:
                            found_old.add(mod)
                        elif isinstance(sub, ast.Name) and mod is None:
                            unknown = True
                whole = model.resolve_expr(args[0], scope)
                if whole in old_modules:
                    _mark(out.reads_source, whole, "whole")     # getsource(g): the whole module
                for mod in found_old:
                    _mark(out.reads_source, mod, "names")       # getsource(g.create_app)
                if not found_old and unknown:
                    _mark(out.reads_source, "?", "indirect")    # getsource(fn)
        elif isinstance(node, (ast.Assign, ast.Delete)):
            for t in node.targets:
                target_site(node, "assign" if isinstance(node, ast.Assign) else "del", t, scope)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            target_site(node, "assign", node.target, scope)
        elif isinstance(node, ast.ImportFrom) and node.module in old_modules:
            for a in node.names:
                out.from_imports.append((node.lineno, node.module, a.name))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            m = _MODULE_PATH_RE.match(node.value)
            if m and _is_path_read(node, parents):
                _mark(out.reads_source, "moonglade." + m.group(1), "whole")
        elif isinstance(node, ast.Attribute) and node.attr == "__file__":
            mod = model.resolve_expr(node.value, scope)
            if mod in old_modules:
                _mark(out.reads_source, mod, "whole")

    # An indirect reader (getsource of something local) reads an old module only if the file
    # names one at all.
    if "?" in out.reads_source:
        del out.reads_source["?"]
        named = {m for _, m in out.aliases if m in old_modules} | {m for _, m, _ in out.from_imports}
        for mod in named:
            _mark(out.reads_source, mod, "indirect")
    out.sites.sort(key=lambda s: (s.line, s.span or (0,)))
    return out


def iter_test_files(tests_dir=DEFAULT_TESTS):
    return sorted(p for p in Path(tests_dir).rglob("*.py") if "__pycache__" not in p.parts)


def scan_tree(tests_dir=DEFAULT_TESTS):
    scans = []
    for p in iter_test_files(tests_dir):
        scans.append(scan_text(p, p.read_text(encoding="utf-8")))
    return scans


def scan_references(text, old_modules=OLD_MODULES):
    """Names a PRODUCTION file reaches through an old module: `from old import x`,
    `<alias>.x` and `getattr(<alias>, "x")`. -> set of (module, name)."""
    model = FileModel(text)
    refs = set()
    for node in ast.walk(model.tree):
        if isinstance(node, ast.ImportFrom) and node.module in old_modules:
            refs.update((node.module, a.name) for a in node.names)
        elif isinstance(node, ast.Attribute):
            mod = model.resolve_expr(node.value, model.scope_for(node))
            if mod in old_modules:
                refs.add((mod, node.attr))
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in ("getattr", "hasattr") and len(node.args) >= 2):
            mod = model.resolve_expr(node.args[0], model.scope_for(node))
            name = _str_const(node.args[1])
            if mod in old_modules and name:
                refs.add((mod, name))
    return refs


# ---------------------------------------------------------------------------------------------
# Planning and applying the retarget
# ---------------------------------------------------------------------------------------------

@dataclass
class Edit:
    site: Site
    new_module: str
    old_target: str
    new_target: str
    replacement: str          # the text that replaces site.span
    needs_alias: bool


def default_alias(new_module):
    return new_module.rsplit(".", 1)[-1] + "_mod"


def _existing_alias(model, module):
    """A module-scope name already bound to `module` only, or None."""
    top = model.scopes[0]
    for name, kinds in top.bindings.items():
        if kinds == {("mod", module)}:
            return name
    return None


def _identifiers(model):
    names = set()
    for node in ast.walk(model.tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.split(".")[0])
    return names


def plan_file(path, text, seams, aliases=None):
    """(edits, unresolved, alias_for) for one file. unresolved: [(line, message)]."""
    aliases = aliases or {}
    moved = moved_index(seams)
    moved_names = {}
    for (old, name), new in moved.items():
        moved_names.setdefault(name, []).append((old, new))
    scan = scan_text(path, text)
    edits, unresolved, alias_for = [], [], {}
    if scan.error:
        return edits, [(0, scan.error)], alias_for
    model = FileModel(text)
    idents = _identifiers(model)
    for s in scan.sites:
        if s.module in OLD_MODULES and (s.module, s.name) in moved and s.kind in ("expr", "string"):
            new = moved[(s.module, s.name)]
            if s.kind == "string":
                old_dotted = "%s.%s" % (s.module, s.name)
                if s.span[0] != s.span[2] or s.text.count(old_dotted) != 1:
                    unresolved.append((s.line, "string target %s is not one plain literal" % s.text))
                    continue
                new_text = s.text.replace(old_dotted, "%s.%s" % (new, s.name))
                edits.append(Edit(s, new, s.text, new_text, new_text, False))
                continue
            if new not in alias_for:
                name = _existing_alias(model, new) or aliases.get(new) or default_alias(new)
                if _existing_alias(model, new) is None and name in idents:
                    unresolved.append((s.line, "alias %r for %s is already a name in this file"
                                       % (name, new)))
                    continue
                alias_for[new] = name
            edits.append(Edit(s, new, "%s.%s" % (s.text, s.name),
                              "%s.%s" % (alias_for[new], s.name), alias_for[new],
                              _existing_alias(model, new) is None))
        elif s.module in OLD_MODULES and s.kind == "dynamic":
            # setattr(core, name, ...): only a question when something moved out of that module
            if s.candidates is not None:
                # `for name in ("a", "b"): setattr(core, name, ...)`: the names are known
                hit = [n for n in s.candidates if (s.module, n) in moved]
                if hit:
                    unresolved.append((s.line, "%s on %s with a loop name that includes moved %s: "
                                               "retarget by hand" % (s.form, s.module,
                                                                     ", ".join(hit))))
            elif any(old == s.module for old, _ in moved):
                unresolved.append((s.line, "%s on %s with a computed name: check by hand"
                                   % (s.form, s.module)))
        elif s.module in (None, AMBIGUOUS) and s.name and s.name in moved_names:
            unresolved.append((s.line, "%s of %r on a receiver that does not resolve to a module "
                                       "(%s): check by hand" % (s.form, s.name,
                                                               s.module or "unknown")))
        elif s.module in (None, AMBIGUOUS) and not s.name and s.kind == "dynamic" and moved:
            unresolved.append((s.line, "%s with a computed target naming an old module: check by "
                                       "hand" % s.form))
    return edits, unresolved, alias_for


def _import_insert_line(model):
    """1-based line after which to insert a new top-level import."""
    last = 0
    body = model.tree.body
    for node in body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last = node.end_lineno
    if last:
        return last
    if body and isinstance(body[0], ast.Expr) and isinstance(_str_const(body[0].value), str):
        last = body[0].end_lineno
    for node in body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            last = node.end_lineno
    return last


def apply_edits(text, edits, alias_for):
    """The rewritten text. Byte-exact edits (ast offsets are UTF-8), right to left."""
    lines = text.splitlines(keepends=True)
    newline = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    by_line = {}
    for e in edits:
        by_line.setdefault(e.site.span[0], []).append(e)
    for lineno, es in by_line.items():
        raw = lines[lineno - 1].encode("utf-8")
        for e in sorted(es, key=lambda e: e.site.span[1], reverse=True):
            _, c0, _, c1 = e.site.span
            raw = raw[:c0] + e.replacement.encode("utf-8") + raw[c1:]
        lines[lineno - 1] = raw.decode("utf-8")
    needed = sorted({(e.new_module, alias_for.get(e.new_module)) for e in edits if e.needs_alias})
    if needed:
        at = _import_insert_line(FileModel(text))
        new_lines = []
        for mod, alias in needed:
            pkg, base = mod.rsplit(".", 1)
            new_lines.append("from %s import %s as %s%s" % (pkg, base, alias, newline))
        lines[at:at] = new_lines
    return "".join(lines)


def run(seams, tests_dir, apply=False, aliases=None, out=None):
    """Plan (and with apply=True, write) every file. Returns (n_edits, n_unresolved)."""
    out = out or sys.stdout
    tests_dir = Path(tests_dir)
    n_edits = n_unres = 0
    for p in iter_test_files(tests_dir):
        with open(p, encoding="utf-8", newline="") as fh:     # keep CRLF files CRLF
            text = fh.read()
        edits, unresolved, alias_for = plan_file(p, text, seams, aliases)
        try:
            rel = p.resolve().relative_to(REPO)
        except ValueError:
            rel = p.relative_to(tests_dir)
        for e in edits:
            print("%s:%d %s -> %s" % (rel.as_posix(), e.site.line, e.old_target, e.new_target),
                  file=out)
        for line, msg in unresolved:
            print("%s:%d UNRESOLVED %s" % (rel.as_posix(), line, msg), file=out)
        n_edits += len(edits)
        n_unres += len(unresolved)
        if apply and edits:
            new_text = apply_edits(text, edits, alias_for)
            try:
                ast.parse(new_text)
            except SyntaxError as exc:
                print("%s: NOT WRITTEN, the rewrite does not parse: %s" % (rel.as_posix(), exc),
                      file=out)
                n_unres += 1
                continue
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(new_text)
    print("%d site(s) %s, %d unresolved" % (n_edits, "rewritten" if apply else "to change",
                                            n_unres), file=out)
    return n_edits, n_unres


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="print the sites to change (the default)")
    mode.add_argument("--apply", action="store_true", help="rewrite the test files")
    ap.add_argument("--seams", type=Path, default=DEFAULT_SEAMS,
                    help="the file holding the SEAMS literal (default: dev/tests/test_module_seams.py)")
    ap.add_argument("--tests", type=Path, default=DEFAULT_TESTS, help="the folder to scan")
    ap.add_argument("--alias", action="append", default=[], metavar="MODULE=NAME",
                    help="the import alias for a new module (default: <base>_mod)")
    args = ap.parse_args(argv)
    aliases = dict(a.split("=", 1) for a in args.alias)
    _, unresolved = run(load_seams(args.seams), args.tests, apply=args.apply, aliases=aliases)
    return 1 if unresolved else 0


if __name__ == "__main__":
    sys.exit(main())
