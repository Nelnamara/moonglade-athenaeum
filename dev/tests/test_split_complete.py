"""The module split is complete (split phase 4, DESIGN section 2: checks C1-C7).

gallery.py and backup.py used to hold everything. They are now the two engines' cores, and every
section that left them lives in a module of its own. This file holds that it stays so:

  C1  gallery.py and backup.py stay under their line ceilings.
  C2  create_app's body defines nothing: no def, class or lambda, and a short body.
  C3  no route is declared in gallery.py; on a built app every view is a routes_* function and
      every hook is routes_gate's (Flask's own context processor excepted, named below).
  C4  production reaches moonglade.backup and moonglade.gallery only for their core names.
  C5  no other module passes the size ceiling (migrate.py, the 3.20 move's one-time migration,
      was never part of the split and is the one named exception).
  C6  the seams checks pass over the final SEAMS, and every route and web module imports the
      two old modules only inside functions.
  C7  the server-source collector in conftest returns the two old modules and every module that
      received code from them, and its per-function view finds create_app and every register.

Each check is a function over its inputs, so the synthetic cases at the foot prove it fires.
"""
import ast
import re

import pytest

from tests import test_module_seams as seams
from tests.conftest import REPO_ROOT, server_source_modules, server_sources

PACKAGE = REPO_ROOT / "moonglade"

# --- C1 / C5: the ceilings (physical lines) ---------------------------------------------------
GALLERY_MAX_LINES = 1500
BACKUP_MAX_LINES = 2500
OTHER_MODULE_MAX_LINES = 3500
# migrate.py is the 3.20 move's one-time migration; it was never part of the split.
C5_EXEMPT = ("migrate.py",)

# --- C2 ----------------------------------------------------------------------------------------
CREATE_APP_MAX_LINES = 250

# --- C3 ----------------------------------------------------------------------------------------
# Flask registers its own context processor on every app; its __module__ starts with "flask.".
# The exclusion is named here so it is never loosened by hand.
FLASK_OWN_HOOK_PREFIX = "flask."
HOOK_MODULE = "moonglade.routes_gate"
ROUTE_MODULE_PREFIX = "moonglade.routes_"

# --- C4: what production may reach through the two old modules ---------------------------------
BACKUP_CORE = frozenset({
    "__version__", "main",
    # the error classes and the redirect and error helpers
    "PixAIError", "HistoryPageRefused", "ArtworkListRefused", "LocalRefusal", "PixAIAuthError",
    "graphql_error", "PixAIRestError", "PixAIOutcomeError", "CreateOutcomeUnknown",
    "_rest_error", "_is_redirect_status", "_refuse_redirect", "EmptyOutputsError",
    "WatchStaleError",
    # verbosity
    "set_verbose", "vlog", "_VERBOSE",
    # the module state tests patch
    "API_URL", "REST_API_BASE", "OPERATION_NAME", "READ_ONLY", "USER_ID", "U3T", "MEDIA_BASE",
    "_turbo_refused", "_cfg",
    # config (the accounts lock stays in backup: web_accounts takes it lazily)
    "_config_path", "_load_config", "_save_config", "_accounts_lock",
    "_read_only_now", "_check_read_only", "load_token", "_ssl_help",
    # the progress helpers, the count and the size line they print, and the TLS state they report
    "_progress_line", "_make_progress", "PANEL_PROGRESS_PREFIX", "PANEL_WARN_PREFIX",
    "_format_size", "_quick_count", "_TRUSTSTORE_ACTIVE",
    "_atomic_replace", "_ensure_db",
    # the transport
    "gql_adhoc", "gql_mutate", "resolve_user_id", "_make_session", "_rest_get", "_rest_post",
    "_create", "_rest_patch", "_rest_put",
    "upload_media",
    # what 3.22 kept
    "CONFIG_API_BASE", "_config_get", "_cached_config", "_GEN_MODEL_Q", "_UPSERT_MODEL",
    "make_model_public",
})
GALLERY_CORE = frozenset({
    "create_app", "main",
    # the server lifecycle: route modules reach these lazily
    "_schedule_server_exit", "_supervised", "_note_server_exit", "server_notice",
    "_power_in_progress", "_OUTSIDE_FIXING", "_SERVER_CONTROL", "_clean_for_log", "_outside_scan",
    "_shortcut_icon_bytes", "DEFAULT_LIBRARY_DIR", "DEFAULT_PORT",
    # the Windows no-console flag, for the updater
    "_NO_WINDOW",
})
CORE = {"moonglade.backup": BACKUP_CORE, "moonglade.gallery": GALLERY_CORE}


def _lines(path):
    return len(path.read_text(encoding="utf-8").splitlines())


def _package_lines():
    return {p.name: _lines(p) for p in sorted(PACKAGE.glob("*.py"))}


# ---------------------------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------------------------

def check_old_module_sizes(lines):
    """C1. lines: {file name: physical lines}."""
    problems = []
    for name, cap in (("gallery.py", GALLERY_MAX_LINES), ("backup.py", BACKUP_MAX_LINES)):
        if lines[name] > cap:
            problems.append("%s is %d lines; the ceiling is %d" % (name, lines[name], cap))
    return problems


def check_create_app_body(source):
    """C2. create_app has no nested def, class or lambda, and spans at most 250 lines."""
    fn = next((n for n in ast.parse(source).body
               if isinstance(n, ast.FunctionDef) and n.name == "create_app"), None)
    if fn is None:
        return ["create_app is not a top-level function"]
    problems = []
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
    for stmt in fn.body:
        for node in ast.walk(stmt):
            if isinstance(node, kinds):
                problems.append("create_app defines a %s at line %d"
                                % (type(node).__name__, node.lineno))
    span = fn.end_lineno - fn.lineno + 1
    if span > CREATE_APP_MAX_LINES:
        problems.append("create_app spans %d lines; the ceiling is %d" % (span, CREATE_APP_MAX_LINES))
    return problems


def check_no_route_in_source(source):
    """C3, source half: no `.route(` decorator or call and no add_url_rule."""
    problems = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr in ("route", "add_url_rule"):
            problems.append("line %d uses .%s" % (node.lineno, node.attr))
    return problems


def _hook_functions(app):
    """Every before-request, after-request, error-handler and context-processor function."""
    out = []
    for table in (app.before_request_funcs, app.after_request_funcs,
                  app.template_context_processors):
        for funcs in table.values():
            out += list(funcs)
    for by_code in app.error_handler_spec.values():
        for by_class in by_code.values():
            out += list(by_class.values())
    return out


def check_built_app(app):
    """C3, built-app half."""
    problems = []
    for endpoint, view in sorted(app.view_functions.items()):
        if endpoint == "static":
            continue
        mod = getattr(view, "__module__", "") or ""
        if not mod.startswith(ROUTE_MODULE_PREFIX):
            problems.append("endpoint %s is served by %s.%s, not a routes_ module"
                            % (endpoint, mod, getattr(view, "__name__", "?")))
    for fn in _hook_functions(app):
        mod = getattr(fn, "__module__", "") or ""
        if mod.startswith(FLASK_OWN_HOOK_PREFIX):
            continue
        if mod != HOOK_MODULE:
            problems.append("hook %s.%s is not in %s" % (mod, getattr(fn, "__name__", "?"),
                                                         HOOK_MODULE))
    return problems


def check_reach(files, core=CORE, seams_map=None, module_binding=None):
    """C4. files: {path: production source}. Every reach through moonglade.backup or
    moonglade.gallery names a core name, and the scanner has no reach it cannot pin to a core
    name either."""
    rp = seams.rp
    kw = {} if module_binding is None else {"module_binding": module_binding}
    problems = []
    for path, text in sorted(files.items()):
        own = "moonglade." + path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        for old, name in sorted(rp.scan_references(text, **kw)):
            if old in core and old != own and name not in core[old]:
                problems.append("%s reaches %s.%s, which is not in its core: import it from the "
                                "module that defines it" % (path, old, name))
        for line, recv, name, mods in rp.scan_reference_gaps(text, **kw):
            old_mods = [m for m in mods if m in core]
            if old_mods and (name is None or name not in core[old_mods[0]]):
                problems.append("%s:%d %s.%s may be %s's, which is not in its core"
                                % (path, line, recv, name or "<computed>", old_mods[0]))
    problems += seams.check_production_gaps(seams_map if seams_map is not None else seams.SEAMS,
                                            files, **kw)
    return problems


def check_other_module_sizes(lines):
    """C5. lines: {file name: physical lines}."""
    return ["%s is %d lines; the ceiling is %d" % (name, n, OTHER_MODULE_MAX_LINES)
            for name, n in sorted(lines.items())
            if name not in ("gallery.py", "backup.py") and name not in C5_EXEMPT
            and n > OTHER_MODULE_MAX_LINES]


def check_route_modules_lazy(sources):
    """C6, the lazy rule over every routes_* and web_* module: moonglade.backup and
    moonglade.gallery are imported inside functions only. sources: {module: text}."""
    problems = []
    for mod, text in sorted(sources.items()):
        for node in seams._import_time_imports(ast.parse(text)):
            hit = sorted(set(seams._imported_modules(node)) & set(seams.OLD_MODULES))
            if hit:
                problems.append("%s line %d imports %s at import time" % (mod, node.lineno, hit[0]))
    return problems


# ---------------------------------------------------------------------------------------------
# The split, as it stands
# ---------------------------------------------------------------------------------------------

def test_c1_old_modules_stay_under_their_ceilings():
    assert check_old_module_sizes(_package_lines()) == []


def test_c2_create_app_defines_nothing():
    source = (PACKAGE / "gallery.py").read_text(encoding="utf-8")
    assert check_create_app_body(source) == []


def test_c3_no_route_is_declared_in_gallery(tmp_path):
    source = (PACKAGE / "gallery.py").read_text(encoding="utf-8")
    assert check_no_route_in_source(source) == []


def test_c3_every_view_and_hook_of_a_built_app_is_where_it_belongs(tmp_path):
    from moonglade.gallery import create_app
    app = create_app(tmp_path)
    assert len(app.view_functions) > 1, "the app built no routes"
    assert check_built_app(app) == []


def test_c4_production_reaches_the_old_modules_only_for_their_core():
    files = {p.relative_to(REPO_ROOT).as_posix(): p.read_text(encoding="utf-8")
             for p in seams.production_files()}
    assert check_reach(files) == []


def test_c4_every_core_name_is_real():
    """A core name that no longer exists would let a stale reach pass as 'allowed'."""
    import importlib
    for modname, names in CORE.items():
        mod = importlib.import_module(modname)
        gone = sorted(n for n in names if not hasattr(mod, n))
        assert gone == [], "%s no longer defines %s" % (modname, gone)


def test_c5_no_other_module_passes_the_ceiling():
    assert check_other_module_sizes(_package_lines()) == []


def test_c6_the_seams_checks_pass_over_the_final_map():
    import importlib
    S = seams.SEAMS
    files = {p.relative_to(REPO_ROOT).as_posix(): p.read_text(encoding="utf-8")
             for p in seams.production_files()}
    assert seams.check_defined_in(S, importlib.import_module, seams._source_of) == []
    assert seams.check_reexports(S, importlib.import_module, seams._production_refs()) == []
    assert seams.check_lazy_imports(S, seams._source_of) == []
    assert seams.check_production_gaps(S, files) == []
    stale, unresolved = seams.lint_patches(S, seams._test_files())
    assert (stale, unresolved) == ([], [])


def test_c6_every_route_and_web_module_imports_the_old_modules_lazily():
    sources = {p.stem: p.read_text(encoding="utf-8")
               for pattern in ("routes_*.py", "web_*.py") for p in PACKAGE.glob(pattern)}
    assert len(sources) >= 20, "found no route or web modules to check"
    assert check_route_modules_lazy(sources) == []


def test_c6_every_route_module_is_in_the_seams_map():
    routes = {"moonglade." + p.stem for p in PACKAGE.glob("routes_*.py")}
    assert routes <= set(seams.SEAMS), sorted(routes - set(seams.SEAMS))


def test_c7_the_collector_returns_the_old_modules_and_every_receiver():
    mods = set(server_source_modules())
    assert {"moonglade.gallery", "moonglade.backup"} <= mods
    assert set(seams.SEAMS) <= mods
    assert mods == {"moonglade.gallery", "moonglade.backup"} | set(seams.SEAMS)
    parts = server_sources(parts=True)
    assert set(parts) == mods
    empty = sorted(m for m, text in parts.items() if not text.strip())
    assert empty == [], "empty collected modules: %s" % empty


def test_c7_the_per_function_view_finds_create_app_and_every_register():
    parts = server_sources(function="create_app", parts=True)
    assert "moonglade.gallery" in parts and "def create_app(" in parts["moonglade.gallery"]
    registers = {m for m, text in parts.items() if "def register(" in text}
    routes = {"moonglade." + p.stem for pattern in ("routes_*.py", "web_*.py")
              for p in PACKAGE.glob(pattern) if "def register(" in p.read_text(encoding="utf-8")}
    assert registers == routes and routes, sorted(routes ^ registers)
    assert all(text.strip() for text in parts.values())
    # a named function is found wherever SEAMS says it went
    assert "def load_catalog(" in server_sources(function="load_catalog")
    with pytest.raises(AssertionError):
        server_sources(function="no_such_function_anywhere")
