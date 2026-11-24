"""
moonglade/web_tiers.py
======================
The gallery's auth tiers, declared at the route: PUBLIC, LOGIN and LOCALHOST, the `tier`
decorator that hangs a declaration on a view, the readers the front door uses
(`route_tier`, `route_tier_message`), `declare_endpoint_tier` for rules registered without a
decorator, and `assert_every_route_declares_a_tier`, which create_app runs before it returns an
app. Moved verbatim out of moonglade/gallery.py in the 3.22 split (phase 4).

It needs nothing from the gallery or the engine.
"""


# ---------------------------------------------------------------------------
# Auth tiers -- DECLARED AT THE ROUTE, enforced in one place
# ---------------------------------------------------------------------------
# A route's auth tier is a property OF THE ROUTE, so it is written on the route.
# It used to live in dev/tests/test_route_tiers.py's ROUTE_TIERS table instead, which
# meant every route addition edited two files in two repositories' worth of
# context -- and the table had already drifted past every credit-spending route
# once (see that file's own header). The decorator below hangs the declaration on
# the view function; _enforce_front_door() reads it back off app.view_functions at
# request time; create_app() refuses to return an app in which any registered rule
# has no declaration. The test still enumerates the url_map and still proves each
# tier against a live request -- it just no longer DECLARES anything.
PUBLIC = "PUBLIC"        # reachable with no session at all (the login surface itself)
LOGIN = "LOGIN"          # any logged-in session, local or LAN
LOCALHOST = "LOCALHOST"  # a logged-in session AND a loopback remote_addr
TIERS = (PUBLIC, LOGIN, LOCALHOST)

# The 403 body a LOCALHOST route refuses with. Three routes say something more
# specific instead (see their `message=`); the wording of all four is a contract
# the front end reads, so it is carried here verbatim rather than regenerated.
LOCALHOST_REFUSAL = "localhost-only"

_TIER_ATTR = "_mg_route_tier"


def tier(default, message=LOCALHOST_REFUSAL, **by_method):
    """Declare this view's auth tier. `@tier(LOGIN)`, `@tier(LOCALHOST)`, `@tier(PUBLIC)`.

    A per-method override keeps a split route declarative instead of pushing half
    of it back into the handler body: `/api/library-path` and `/api/panel/schedule`
    are `@tier(LOGIN, POST=LOCALHOST)` -- readable at the route, and enforced by
    the same gate as everything else.

    `message` overrides the `error` string in the 403 a LOCALHOST route refuses
    with, for the three routes whose hand-written guard said something more
    specific than "localhost-only" (deleting from PixAI; importing onto the
    server's machine). It is the message only -- the status and JSON shape are
    the same for every tier refusal.

    Pick the tier by what the handler can DO, not by what feels convenient:
      LOGIN     -- browse the library, spend the owner's credits, manage your OWN
                   account. A signed-in LAN device is NOT read-only; that is the
                   whole point of the tier (see moonglade-internal/DECISIONS.md).
      LOCALHOST -- irreversible cloud deletion, writes to config.json (which holds
                   PIXAI_API_KEY / AUTH_SECRET_KEY / AUTH_USERS), file-moving
                   maintenance, or shelling out on the SERVER machine.
      PUBLIC    -- the login surface and the static art it renders. Nothing else.

    A route whose LOCALHOST requirement depends on its ARGUMENTS rather than on
    its URL is not expressible as a tier and must not be forced into one:
    /api/panel/run demands loopback only for a destructive action, and
    /api/users/remove only for someone else's account. Those declare the floor
    the gate can actually enforce (LOGIN) and keep their own conditional check,
    which their own test files cover."""
    if default not in TIERS:
        raise ValueError("unknown auth tier {!r}; expected one of {}".format(default, TIERS))
    bad = {m: t for m, t in by_method.items() if t not in TIERS}
    if bad:
        raise ValueError("unknown auth tier(s) in per-method override: {!r}".format(bad))

    declaration = (default, {m.upper(): t for m, t in by_method.items()}, message)

    def _declare(view):
        setattr(view, _TIER_ATTR, declaration)
        return view
    return _declare


def route_tier(view, method):
    """The tier that governs `view` for `method`, or None if it declares none.

    HEAD is governed by the GET tier (review R1, 2026-11-23). Flask adds HEAD to every GET rule
    and runs the same view for it; reading HEAD as its own method fell back to the DEFAULT tier,
    so a route declared `@tier(LOGIN, POST=LOCALHOST)` answered HEAD at LOGIN -- and a handler
    whose write branch was "anything not GET" wrote from a LAN session. Handlers now write only
    on POST, and HEAD is the GET it stands for."""
    declaration = getattr(view, _TIER_ATTR, None)
    if declaration is None:
        return None
    default, by_method, _message = declaration
    if method == "HEAD":
        method = "GET"
    return by_method.get(method, default)


def route_tier_message(view):
    """The `error` string this view's LOCALHOST refusal carries."""
    declaration = getattr(view, _TIER_ATTR, None)
    return LOCALHOST_REFUSAL if declaration is None else declaration[2]


def declare_endpoint_tier(app, endpoint, default, message=LOCALHOST_REFUSAL, **by_method):
    """Declare a tier for an endpoint whose view function this module does not define.

    Exactly one exists: Flask's built-in `static`. It is NOT special-cased away --
    `if rule.endpoint == "static": continue` is the single most common way a
    catch-all route rule grows a hole, and /static/ is gated like everything else."""
    view = app.view_functions[endpoint]
    try:
        tier(default, message=message, **by_method)(view)
    except (AttributeError, TypeError):
        # A bound method or C function can't carry an attribute; wrap it once.
        import functools

        @functools.wraps(view)
        def _shim(*a, **k):
            return view(*a, **k)
        app.view_functions[endpoint] = tier(default, message=message, **by_method)(_shim)


def assert_every_route_declares_a_tier(app):
    """Refuse to hand back an app in which any registered rule has no tier.

    This is the half of the old test table that could never be a test: a
    declaration that lives at the route can only be MISSING at the route, and the
    cheapest possible moment to say so is app creation, not CI. Adding a route
    without a tier now fails the very first request anyone makes -- including the
    developer's own."""
    missing = sorted(
        {(rule.endpoint, str(rule)) for rule in app.url_map.iter_rules()
         if route_tier(app.view_functions.get(rule.endpoint), "GET") is None})
    if missing:
        raise AssertionError(
            "{} registered route(s) declare NO auth tier:\n{}\n\n"
            "FIX: put @tier(...) on the view, under its @app.route(...):\n"
            "    @app.route(\"/api/thing\", methods=[\"POST\"])\n"
            "    @tier(LOGIN)\n"
            "    def api_thing():\n"
            "Choose by what the handler can DO -- see tier()'s own docstring. The\n"
            "tier is not paperwork: every credit-spending route was missing from\n"
            "the hand-maintained lists that preceded this mechanism, and nothing\n"
            "noticed until a route-gating audit found it."
            .format(len(missing),
                    "\n".join("    {} ({})".format(r, e) for e, r in missing)))
