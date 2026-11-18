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
`x = importlib.import_module("moonglade.backup")`, or `x = <another alias>`. Two more ways in:
  - a PARAMETER every in-file call fills with the same module (`def _line_for(r, check, g)`,
    always called as `_line_for(..., g)` with g the gallery): it is that module. Calls that
    disagree, a function used other than by calling it, or a decorated one make it ambiguous.
  - another moonglade module's attribute (`m.g`, with `m` the MCP server, whose top level says
    `from moonglade import gallery as g`): read off that module's own file.

CONSERVATIVE. Text-level edits of exactly the alias expression (or the dotted string), checked
by re-parsing the result. A site whose receiver it cannot resolve to a module (a fixture
parameter, a name bound two ways, a computed string, `patch.multiple`) is REPORTED, never
guessed -- except a computed name that is the variable of an enclosing `for name in ("a",
"b")`, or a parameter filled by `@pytest.mark.parametrize("name", [...])`, over string literals
(directly or through a name bound once to them), which is checked against those literals
(reported only if one of them moved). `getattr(<old module>, name)` / `hasattr(...)` with a
computed name is a site the same way (a moved name read that way fails late or, for hasattr,
silently). `--dry-run` (the default) prints `file:line old_target -> new_target`; `--apply`
rewrites and adds `from moonglade import <mod> as <alias>` to each touched file.

scan_reference_gaps() is the production-side twin: attribute uses on a name the file binds to
an old module somewhere but that does not resolve where it is used (`core, s = _gen_session()`,
a parameter no call pins), so a move cannot strand one silently.

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
        self.bindings = {}        # name -> set of ("mod", "moonglade.x") | ("copy", "alias") |
                                  # ("other", None) | ("param", None)
        self.counts = {}          # name -> how many statements bind it here
        self.assigns = {}         # name -> the value of a plain `name = <value>` here
        self.params = {}          # parameter name -> its bindings other than being a parameter

    def bind(self, name, kind):
        self.bindings.setdefault(name, set()).add(kind)
        self.counts[name] = self.counts.get(name, 0) + 1


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


_MODULE_MODELS = {}


def repo_module_binding(modname, attr, repo=None):
    """What `<modname>.<attr>` is, read off that module's own file under the repo: a dotted
    module name, AMBIGUOUS (bound as a module and as something else, or only through a
    `global` statement), or None (not a module, or no such file). One hop: the file read here
    resolves its own names only."""
    repo = repo or REPO
    key = (str(repo), modname)
    if key not in _MODULE_MODELS:
        path = Path(repo, *modname.split(".")).with_suffix(".py")
        try:
            _MODULE_MODELS[key] = FileModel(path.read_text(encoding="utf-8"),
                                            module_binding=None, infer=False)
        except (OSError, SyntaxError, ValueError):
            _MODULE_MODELS[key] = None
    model = _MODULE_MODELS[key]
    if model is None:
        return None
    top = model.scopes[0]
    if attr in top.bindings:
        return model.resolve_name(attr, top)
    for node in ast.walk(model.tree):
        if isinstance(node, ast.Global) and attr in node.names:
            return AMBIGUOUS
    return None


def source_module_binding(sources):
    """A module_binding over {modname: source text} (the synthetic cases' stand-in)."""
    models = {}

    def binding(modname, attr):
        if modname not in sources:
            return None
        if modname not in models:
            models[modname] = FileModel(sources[modname], module_binding=None, infer=False)
        model = models[modname]
        return model.resolve_name(attr, model.scopes[0]) if attr in model.scopes[0].bindings \
            else None
    return binding


class FileModel:
    """One parsed file: its scope tree and a resolver from expressions to module names.

    module_binding(modname, attr) answers what another moonglade module's attribute is (default:
    read off its file under the repo; None: never look). infer=False skips the parameter
    inference (enough when only top-level names are wanted)."""

    def __init__(self, text, package_hint="moonglade", module_binding=repo_module_binding,
                 infer=True):
        self.text = text
        self.tree = ast.parse(text)
        self.package_hint = package_hint
        self.module_binding = module_binding
        self.scope_of = {}            # id(node) -> _Scope the node's code runs in
        self.scope_by_node = {}       # id(scope node) -> its _Scope
        self.scopes = []
        self.parents = {}
        for node in ast.walk(self.tree):
            for child in ast.iter_child_nodes(node):
                self.parents[id(child)] = node
        self._build(self.tree, None)
        if infer:
            self._infer_params()

    # -- building ------------------------------------------------------------------------
    def _build(self, scope_node, parent):
        scope = _Scope(scope_node, parent)
        self.scopes.append(scope)
        self.scope_by_node[id(scope_node)] = scope
        if isinstance(scope_node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = scope_node.args
            for arg in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg]:
                if arg is not None:
                    scope.bind(arg.arg, ("param", None))
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
                    scope.assigns[t.id] = node.value
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
                if self.module_binding is not None and base.startswith(self.package_hint + "."):
                    return self.module_binding(base, expr.attr)
        return None

    def scope_for(self, node):
        return self.scope_of.get(id(node), self.scopes[0])

    def alias_modules(self, old_modules=OLD_MODULES):
        """{name: old modules it is bound to in SOME scope of this file}: the names a reader
        would take for a module alias even where this file's scoping says otherwise."""
        out = {}
        for s in self.scopes:
            for name, kinds in s.bindings.items():
                for kind, val in kinds:
                    if kind == "mod" and val in old_modules:
                        out.setdefault(name, set()).add(val)
        return out

    # -- parameters that carry a module ----------------------------------------------------
    def _callee(self, name, scope, by_def):
        for s in self._chain(scope):
            if name in s.bindings:
                return by_def.get((id(s), name))
        return None

    def _infer_params(self):
        """Bind a parameter to a module when every call in this file fills it with that one
        module. A function referenced other than as a call's callee (handed out as a callback,
        decorated) can be called from elsewhere, so its parameters also see an unknown value.
        A parameter that sees a module AND something else resolves as AMBIGUOUS."""
        by_def = {}
        for s in self.scopes:
            node = s.node
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and s.parent is not None:
                if s.parent.counts.get(node.name) == 1:
                    by_def[(id(s.parent), node.name)] = s
        if not by_def:
            return
        calls, escaped = [], set()
        for s in by_def.values():
            if s.node.decorator_list:
                escaped.add(id(s))
            for name, kinds in s.bindings.items():
                if ("param", None) in kinds:
                    s.params[name] = set(kinds) - {("param", None)}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name):
                scope = self.scope_for(node)
                callee = self._callee(node.id, scope, by_def)
                if callee is None:
                    continue
                parent = self.parents.get(id(node))
                if isinstance(parent, ast.Call) and parent.func is node:
                    calls.append((parent, scope, callee))
                else:
                    escaped.add(id(callee))
        for _ in range(10):
            obs = {}
            for call, scope, callee in calls:
                a = callee.node.args
                positional = [p.arg for p in a.posonlyargs + a.args]
                every = positional + [p.arg for p in a.kwonlyargs]
                seen = set()
                unknown = False
                for i, arg in enumerate(call.args):
                    if isinstance(arg, ast.Starred):
                        unknown = True
                        break
                    if i < len(positional):
                        obs.setdefault((id(callee), positional[i]), set()).add(
                            self.resolve_expr(arg, scope))
                        seen.add(positional[i])
                for k in call.keywords:
                    if k.arg is None:
                        unknown = True
                    elif k.arg in every:
                        obs.setdefault((id(callee), k.arg), set()).add(
                            self.resolve_expr(k.value, scope))
                        seen.add(k.arg)
                if unknown:
                    for p in every:
                        obs.setdefault((id(callee), p), set()).add(None)
                defaults = dict(zip(positional[len(positional) - len(a.defaults):], a.defaults))
                defaults.update({p.arg: d for p, d in zip(a.kwonlyargs, a.kw_defaults)
                                 if d is not None})
                for p, d in defaults.items():
                    if p not in seen:
                        obs.setdefault((id(callee), p), set()).add(
                            self.resolve_expr(d, self.scope_for(callee.node)))
            changed = False
            for s in by_def.values():
                for p, base in s.params.items():
                    seen_vals = set(obs.get((id(s), p), set()))
                    if id(s) in escaped:
                        seen_vals.add(None)
                    mods = {v for v in seen_vals if v not in (None, AMBIGUOUS)}
                    if len(mods) == 1 and not seen_vals - mods:
                        inferred = {("mod", next(iter(mods)))}
                    elif mods & set(OLD_MODULES):        # maybe an old module: ambiguous
                        inferred = {("mod", m) for m in mods} | {("param", None)}
                    else:                                # never an old module: a plain value
                        inferred = {("param", None)}
                    new = base | inferred
                    if new != s.bindings[p]:
                        s.bindings[p] = new
                        changed = True
            if not changed:
                break

    # -- literal names -----------------------------------------------------------------------
    def literal_strings(self, expr, scope, _depth=0):
        """The strings a tuple/list/set of string literals holds -- directly, through a name
        bound once to one, or a `+` of two of them -- else None."""
        if _depth > 5:
            return None
        if isinstance(expr, (ast.Tuple, ast.List, ast.Set)):
            if expr.elts and all(_str_const(e) is not None for e in expr.elts):
                return tuple(e.value for e in expr.elts)
            return None
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
            left = self.literal_strings(expr.left, scope, _depth + 1)
            right = self.literal_strings(expr.right, scope, _depth + 1)
            return left + right if left is not None and right is not None else None
        if isinstance(expr, ast.Name):
            for s in self._chain(scope):
                if expr.id in s.bindings:
                    if s.counts.get(expr.id) == 1 and expr.id in s.assigns:
                        return self.literal_strings(s.assigns[expr.id], s, _depth + 1)
                    return None
        return None

    def literal_names(self, name_node, node):
        """The literals a computed name takes: the variable of the nearest enclosing `for` over
        literal strings, or a parameter filled by `@pytest.mark.parametrize("<it>", <literal
        strings>)`. None when neither pins it."""
        if not isinstance(name_node, ast.Name):
            return None
        cur = self.parents.get(id(node))
        while cur is not None and not isinstance(cur, _SCOPE_TYPES):
            if (isinstance(cur, (ast.For, ast.AsyncFor)) and isinstance(cur.target, ast.Name)
                    and cur.target.id == name_node.id):
                return self.literal_strings(cur.iter, self.scope_for(cur))
            cur = self.parents.get(id(cur))
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = cur.args
            if name_node.id in [p.arg for p in a.posonlyargs + a.args + a.kwonlyargs]:
                for d in cur.decorator_list:
                    if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                            and d.func.attr == "parametrize" and len(d.args) >= 2
                            and _str_const(d.args[0]) is not None
                            and [n.strip() for n in d.args[0].value.split(",")] == [name_node.id]):
                        return self.literal_strings(d.args[1], self.scope_for(d))
        return None

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


_READ_RANK = {"all": 0, "names": 1, "indirect": 2, "whole": 3}


def _mark(reads, mod, kind):
    """Record how a file reads a module's source, keeping the widest: "whole" (the module's
    text: getsource(module), a path read, __file__), "indirect" (getsource of something this
    scanner cannot trace), "names" (getsource of named functions only), "all" (every module of
    the package, by a glob: no move takes code out of its sight)."""
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


def _root_and_first_attr(expr):
    """For `a.b.c` / `a.b[k]`: ("a", "b"); (name, None) for a bare name; (None, None) else."""
    first = None
    while isinstance(expr, (ast.Attribute, ast.Subscript)):
        if isinstance(expr, ast.Attribute):
            first = expr.attr
        expr = expr.value
    return (expr.id if isinstance(expr, ast.Name) else None), first


def _root_name(expr):
    while isinstance(expr, (ast.Attribute, ast.Subscript, ast.Call)):
        expr = expr.value if not isinstance(expr, ast.Call) else expr.func
    return expr.id if isinstance(expr, ast.Name) else None


def scan_text(path, text, old_modules=OLD_MODULES, module_binding=repo_module_binding):
    """Scan one file's text. Never raises on a syntax error (recorded in .error)."""
    out = FileScan(path=str(path))
    try:
        model = FileModel(text, module_binding=module_binding)
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
                            model.literal_names(name_node, node))
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
                return
            # `core.name = ...` on a `core` that is not a module HERE (a fixture parameter, a
            # tuple-bound name) although the file binds that name to one elsewhere
            root, first = _root_and_first_attr(target)
            if (root in likely and first
                    and model.resolve_name(root, scope) in (None, AMBIGUOUS)):
                add(node, form, None, first, "dynamic", None)

    likely = model.alias_modules(old_modules)
    parents = model.parents

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
            elif (isinstance(node.func, ast.Name) and node.func.id in ("getattr", "hasattr")
                  and len(args) >= 2 and _str_const(args[1]) is None):
                # getattr(core, name): a moved name read this way fails late (hasattr: never)
                mod = model.resolve_expr(args[0], scope)
                if mod in old_modules:
                    add(node, node.func.id, mod, "", "dynamic", None,
                        model.literal_names(args[1], node))
                elif mod == AMBIGUOUS:
                    add(node, node.func.id, AMBIGUOUS, "", "dynamic", None)
            # Source readers: (ROOT / "moonglade").glob("*.py") reads every module of the package
            if (isinstance(node.func, ast.Attribute) and node.func.attr in ("glob", "rglob")
                    and args and (_str_const(args[0]) or "").endswith(".py")
                    and any(_str_const(c) == "moonglade" for c in ast.walk(node.func.value))):
                for mod in old_modules:
                    _mark(out.reads_source, mod, "all")
            # Source readers: inspect.getsource(core.x), getsource(g), getsource(fn) ...
            fname = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if fname in _SOURCE_FUNCS and args:
                found_old, found_new, unknown = set(), False, False
                for sub in ast.walk(args[0]):
                    if isinstance(sub, (ast.Name, ast.Attribute)):
                        mod = model.resolve_expr(sub, scope)
                        if mod in old_modules:
                            found_old.add(mod)
                        elif mod not in (None, AMBIGUOUS):
                            found_new = True                    # getsource(newmod.x)
                        elif isinstance(sub, ast.Name) and mod is None:
                            unknown = True
                whole = model.resolve_expr(args[0], scope)
                if whole in old_modules:
                    _mark(out.reads_source, whole, "whole")     # getsource(g): the whole module
                for mod in found_old:
                    _mark(out.reads_source, mod, "names")       # getsource(g.create_app)
                if not found_old and not found_new and unknown:
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


# ---------------------------------------------------------------------------------------------
# JavaScript tests that read the Python source (loom/test/import-batches.test.js read
# IMPORT_REQUEST_CAP out of moonglade/gallery.py until phase 1 moved it to moonglade/scan.py)
# ---------------------------------------------------------------------------------------------

JS_SUFFIXES = (".js", ".mjs", ".cjs", ".jsx")
JS_TEST_ROOTS = ("loom/test", "loom/test-support", "gallery")
_JS_SKIP_DIRS = {"node_modules", "dist"}
_JS_PY_PATH_RE = re.compile(r"^(?:.*[/\\])?moonglade[/\\](\w+)\.py$")
_JS_REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^") | {""}
_JS_REGEX_KEYWORDS = {"return", "typeof", "case", "do", "else", "in", "of", "void", "yield",
                      "await", "delete", "throw", "new", "instanceof"}


def iter_js_test_files(repo=REPO):
    """The JS files under loom/test, loom/test-support and gallery/ (minus node_modules and
    the built dist/), the places a node test lives."""
    out = []
    for root in JS_TEST_ROOTS:
        base = Path(repo, root)
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if (p.suffix in JS_SUFFIXES and p.is_file()
                    and not _JS_SKIP_DIRS & set(p.relative_to(repo).parts)):
                out.append(p)
    return sorted(set(out))


def js_string_literals(text):
    """[(line, value)] for every quoted or template string in JS source, comments skipped. A
    small scanner, not a parser: it knows strings, template literals (a `${...}` inside one is
    kept as text), line and block comments and regex literals, which is all a path needs."""
    out = []
    i, n, line = 0, len(text), 1
    prev = ""            # the last significant character (or word) before here
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c.isspace():
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            line += text.count("\n", i, j)
            i = j
            continue
        if c in "\"'`":
            start_line, j, buf = line, i + 1, []
            while j < n and text[j] != c:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j:j + 2])
                    j += 2
                    continue
                if text[j] == "\n":
                    line += 1
                buf.append(text[j])
                j += 1
            out.append((start_line, "".join(buf)))
            i = j + 1
            prev = c
            continue
        if c == "/" and (prev in _JS_REGEX_AFTER or prev in _JS_REGEX_KEYWORDS):
            j, in_class = i + 1, False
            while j < n and text[j] != "\n":
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "[":
                    in_class = True
                elif text[j] == "]":
                    in_class = False
                elif text[j] == "/" and not in_class:
                    break
                j += 1
            i = j + 1
            prev = "/"
            continue
        if c.isalnum() or c in "_$":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_$"):
                j += 1
            prev = text[i:j]
            i = j
            continue
        prev = c
        i += 1
    return out


def scan_js_text(path, text):
    """A JS file's reads of the Python source: every string naming a `moonglade/<x>.py` path
    (or a bare "backup.py"/"gallery.py") outside comments counts as reading that module WHOLE
    -- a node test reads the file's text, never a function by name."""
    out = FileScan(path=str(path))
    for _, value in js_string_literals(text):
        m = _JS_PY_PATH_RE.match(value)
        if m:
            _mark(out.reads_source, "moonglade." + m.group(1), "whole")
            continue
        m = _MODULE_PATH_RE.match(value)
        if m and "/" not in value and "\\" not in value:
            _mark(out.reads_source, "moonglade." + m.group(1), "whole")
    return out


def scan_any(path, text):
    """scan_js_text for a JS file, scan_text for Python."""
    if str(path).endswith(JS_SUFFIXES):
        return scan_js_text(path, text)
    return scan_text(path, text)


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


def scan_reference_gaps(text, old_modules=OLD_MODULES, module_binding=repo_module_binding):
    """What scan_references cannot pin, so a move cannot pass it silently. -> sorted list of
    (line, receiver, name, modules):
      - `<x>.name` / getattr(<x>, "name") where the file binds <x> to an old module in SOME
        scope but <x> does not resolve to one where it is used (`core, s = _gen_session()`, a
        parameter its calls do not pin, a name bound two ways). modules: what <x> is bound to
        elsewhere in the file.
      - getattr/hasattr(<old module>, <computed>): name is "" and modules the one module."""
    model = FileModel(text, module_binding=module_binding)
    likely = model.alias_modules(old_modules)
    gaps = set()
    for node in ast.walk(model.tree):
        scope = model.scope_for(node)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            recv = node.value.id
            if recv in likely and model.resolve_name(recv, scope) in (None, AMBIGUOUS):
                gaps.add((node.lineno, recv, node.attr, tuple(sorted(likely[recv]))))
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in ("getattr", "hasattr") and len(node.args) >= 2):
            recv, name = node.args[0], _str_const(node.args[1])
            mod = model.resolve_expr(recv, scope)
            if mod in old_modules and name is None:
                gaps.add((node.lineno, model.segment(recv), "", (mod,)))
            elif (isinstance(recv, ast.Name) and recv.id in likely and name is not None
                  and mod in (None, AMBIGUOUS)):
                gaps.add((node.lineno, recv.id, name, tuple(sorted(likely[recv.id]))))
    return sorted(gaps)


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


def plan_file(path, text, seams, aliases=None, module_binding=repo_module_binding):
    """(edits, unresolved, alias_for) for one file. unresolved: [(line, message)]."""
    aliases = aliases or {}
    moved = moved_index(seams)
    moved_names = {}
    for (old, name), new in moved.items():
        moved_names.setdefault(name, []).append((old, new))
    scan = scan_text(path, text, module_binding=module_binding)
    edits, unresolved, alias_for = [], [], {}
    if scan.error:
        return edits, [(0, scan.error)], alias_for
    model = FileModel(text, module_binding=module_binding)
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


def source_lines(text):
    """`text` split into lines the way ast numbers them: at "\n" only (a "\r\n" stays one
    line end). str.splitlines also splits at U+2028, a form feed and the other Unicode line
    breaks, which Python source may carry inside a string or a comment; that puts every later
    ast line number one off, and an edit lands on the line above its node."""
    lines = text.split("\n")
    out = [l + "\n" for l in lines[:-1]]
    if lines[-1]:
        out.append(lines[-1])
    return out


def apply_edits(text, edits, alias_for):
    """The rewritten text. Byte-exact edits (ast offsets are UTF-8), right to left."""
    lines = source_lines(text)
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
