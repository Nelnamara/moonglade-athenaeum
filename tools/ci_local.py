#!/usr/bin/env python3
"""Local mirror of the GitHub "Tests" workflow (.github/workflows/tests.yml).

Run this from anywhere BEFORE pushing to master, so master never goes red on
something a local run could have caught:

    python tools/ci_local.py            # the real thing
    python tools/ci_local.py --dry-run  # print the preflight + the jobs, run nothing

The real workflow has two jobs and this runs both, the way CI runs them:

  1. pytest -- CI's exact command, `pytest -q --ignore=tests/test_similar.py`
     (test_similar needs the optional Pixeltable/CLIP index; CI skips it too). The
     browser-driven render harness is INCLUDED. It runs clean on a dev box; the one
     local failure it ever had was a real precondition bug in a test, since fixed, not
     an environment quirk. A harness test that fails here is a bug to trace, not a
     reason to skip the file.
  2. loom-node-tests -- rebuild loom/dist, FAIL if the committed bundle is stale,
     then run the Loom's `node --test` source-structure + logic suite. This is the
     job a Python-only local run misses: a front-end MOVE/rename goes red here while
     pytest stays green (learned twice, 2026-09-08/09).

PREFLIGHT, and why it refuses rather than warns. Three checks in the pytest job are written
to SKIP themselves when their toolchain is absent -- the committed-gallery-bundle and
committed-loom-bundle freshness tests (they need node_modules) and the whole render harness
(it needs a playwright browser). Two of the three really run in CI: its pytest job installs
node, `npm ci`s gallery/ and installs chromium `--with-deps`. The loom bundle test is the
exception and is worth being exact about -- CI's pytest job never touches loom/node_modules,
so that test SKIPS there every time; CI covers the same staleness in its OTHER job, the
`git status --porcelain -- dist` step this script mirrors as [2b]. A local run missing any
of them prints the same "green" while saying nothing about the bundle it would have rebuilt
or the layout it would have measured: precisely how a stale gallery/dist earns a green
pre-merge command and a red CI. So this refuses to start until the environment carries what
CI's `npm ci` / `playwright install` steps provide (plus loom's, which only this run needs),
and names the command that fixes each gap. Nothing is installed for you -- an install is the
kind of thing you should watch.

AND THEN IT CHECKS THAT THEY REALLY RAN, which is the half a preflight cannot do. A
preflight answers "could this check run", and those are not the same sentence: chromium's
binary can be on disk and still refuse to launch (a fresh Linux box after
`playwright install chromium` without the system libraries -- CI installs them with
`--with-deps`), and the harness skips on the LAUNCH, not on the path. `gallery/dist/app.css`
can be missing, or `MOONGLADE_SKIP_GALLERY_BUILD` set, and the bundle test skips itself with
every preflight box ticked. So the pytest job is run with a junit report and the report is
read afterwards: both bundle-freshness tests must have actually executed, and the render
harness must have contributed at least one non-skipped test. A gate that skipped fails this
run. A green that skipped the gate you needed is worse than a red.

Exit 0 only if every job passes. Green here == safe to push. It is a long run --
start it when you are done editing, not between edits.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOM = os.path.join(ROOT, "loom")
GALLERY = os.path.join(ROOT, "gallery")

JOBS = [
    "[1] pytest  (CI's exact command; render harness included)",
    "[1b] the skip-prone checks actually ran  (read off the junit report)",
    "[2a] loom: rebuild the esbuild bundle",
    "[2b] loom/dist is a fresh build  (git status --porcelain, as CI checks it)",
    "[3] loom node suite  (node --test)",
]


def _run(desc, cmd, cwd=None, shell=False):
    print("\n== %s ==" % desc)
    sys.stdout.flush()
    return subprocess.run(cmd, cwd=cwd or ROOT, shell=shell).returncode == 0


_ENGINES = ("chromium", "firefox", "webkit")


def harness_engine():
    """The engine the harness will actually launch, read the way it reads it.

    `render_browser` takes `MG_HARNESS_BROWSER` (default chromium, CI's only engine) and
    launches THAT (tests/test_render_harness.py). A preflight that hard-codes chromium
    answers a question nobody asked under `MG_HARNESS_BROWSER=webkit`: it ticks its box off
    a chromium the run will never touch, and every harness test then skips on the webkit
    binary that was never installed. Returns the raw value when it is not a known engine --
    the caller reports that as its own gap, because the harness pytest.fail()s on it."""
    return (os.environ.get("MG_HARNESS_BROWSER") or "chromium").strip().lower()


def _engine_unusable(engine):
    """'' when `engine` LAUNCHES here, else the reason it does not.

    It launches one and closes it, rather than resolving the path and stating it, because
    the path is not what the harness skips on: `render_browser` calls `browser.launch()`
    and skips on the exception it raises (tests/test_render_harness.py). A binary that is
    present but cannot start -- what `playwright install chromium` leaves on a fresh Linux
    box without the system libraries CI's `--with-deps` adds -- passes a stat and fails a
    launch, so a stat-based preflight would tick its box and let every harness test skip.
    Costs about a second. Downloads nothing and installs nothing: an install is the kind of
    thing you should watch."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:                     # noqa: BLE001 -- any import failure is "absent"
        return "the playwright package is not importable (%s)" % exc
    try:
        pw = sync_playwright().start()
    except Exception as exc:                     # noqa: BLE001
        return "playwright will not start (%s)" % exc
    try:
        exe = getattr(pw, engine).executable_path
        if not os.path.exists(exe):
            return "no %s binary at %s" % (engine, exe)
        browser = getattr(pw, engine).launch()
        browser.close()
    except Exception as exc:                     # noqa: BLE001
        # First line only: playwright's own message trails a multi-line ASCII banner.
        return "%s will not launch (%s)" % (engine, str(exc).splitlines()[0])
    finally:
        pw.stop()
    return ""


def preflight():
    """The environment CI's install steps provide. Returns a list of (gap, fix) pairs.

    Every skip path of BOTH bundle-freshness tests is covered here, not just the gallery
    one: `test_committed_loom_bundle_matches_a_fresh_build` skips on
    MOONGLADE_SKIP_LOOM_BUILD, a missing node, missing loom/scripts/build.mjs or
    loom/dist/master-storyboard.bundle.js, and a missing loom/node_modules/esbuild
    (tests/test_js_syntax.py). [1b] catches a skip after the fact, but a gap named before
    the run costs minutes instead of the whole pytest job, and the loom test has no reason
    to be told about later than its gallery twin."""
    gaps = []
    if shutil.which("node") is None:
        gaps.append(("node is not on PATH -- both bundle-freshness tests and the whole "
                     "loom-node-tests job need it", "install Node 22 (CI's version)"))
    if not os.path.isfile(os.path.join(GALLERY, "node_modules", "vite", "bin", "vite.js")):
        gaps.append(("gallery/node_modules is missing, so "
                     "test_committed_gallery_bundle_matches_a_fresh_build SKIPS and a stale "
                     "committed gallery/dist would sail through this run",
                     "cd gallery && npm ci"))
    for name in ("app.js", "app.css"):
        if not os.path.isfile(os.path.join(GALLERY, "dist", name)):
            # The same test skips on `len(committed) != 2`, so a missing half of the
            # committed bundle silently turns the freshness gate off.
            gaps.append(("gallery/dist/%s is missing, so "
                         "test_committed_gallery_bundle_matches_a_fresh_build SKIPS itself "
                         "and nothing compares the served bundle to its source" % name,
                         "cd gallery && npm run build   then commit gallery/dist/"))
    if not os.path.isdir(os.path.join(LOOM, "node_modules", "esbuild")):
        gaps.append(("loom/node_modules is missing, so the loom bundle cannot be rebuilt "
                     "with the esbuild version pinned in loom/package-lock.json -- and "
                     "test_committed_loom_bundle_matches_a_fresh_build SKIPS on it too",
                     "cd loom && npm ci"))
    for rel in (os.path.join("scripts", "build.mjs"),
                os.path.join("dist", "master-storyboard.bundle.js")):
        if not os.path.isfile(os.path.join(LOOM, rel)):
            # The same "build tooling or dist bundle not present" skip the gallery test has,
            # on the loom side: without either half there is nothing to rebuild or compare.
            gaps.append(("loom/%s is missing, so "
                         "test_committed_loom_bundle_matches_a_fresh_build SKIPS itself and "
                         "nothing compares the served bundle to its source"
                         % rel.replace(os.sep, "/"),
                         "restore it from git -- /loom?bundle=1 serves that committed file"))
    if os.environ.get("MOONGLADE_SKIP_GALLERY_BUILD"):
        gaps.append(("MOONGLADE_SKIP_GALLERY_BUILD is set in this environment -- it turns "
                     "test_committed_gallery_bundle_matches_a_fresh_build off outright",
                     "unset MOONGLADE_SKIP_GALLERY_BUILD"))
    if os.environ.get("MOONGLADE_SKIP_LOOM_BUILD"):
        gaps.append(("MOONGLADE_SKIP_LOOM_BUILD is set in this environment -- it turns "
                     "test_committed_loom_bundle_matches_a_fresh_build off outright",
                     "unset MOONGLADE_SKIP_LOOM_BUILD"))
    engine = harness_engine()
    if engine not in _ENGINES:
        gaps.append(("MG_HARNESS_BROWSER=%r is not one of %s -- the render harness "
                     "pytest.fail()s on it rather than running" % (engine, ", ".join(_ENGINES)),
                     "unset MG_HARNESS_BROWSER (chromium, CI's engine) or set a real one"))
    else:
        unusable = _engine_unusable(engine)
        if unusable:
            gaps.append(("the render harness would skip itself -- %s" % unusable,
                         "python -m playwright install --with-deps %s   (CI's own step for "
                         "chromium; --with-deps is what supplies the browser's system "
                         "libraries on Linux)" % engine))
    return gaps


# The checks inside the pytest job that are written to skip themselves. Preflight argues
# they CAN run; this is how the run proves they DID. (module, test) for a named test;
# (module, None) for "this whole module must have contributed something".
#
# Two of the three are also gates in CI's own pytest job. The loom bundle test is not --
# CI's pytest job never installs loom/node_modules, so it skips there and CI catches a
# stale loom/dist in the loom-node-tests job instead ([2b] below). It is required here
# anyway: it is the one check that compares the committed bundle to a rebuild inside the
# pytest run, and a local gate going quiet is still a local gate going quiet.
REQUIRED_TO_RUN = [
    ("tests.test_js_syntax", "test_committed_gallery_bundle_matches_a_fresh_build"),
    ("tests.test_js_syntax", "test_committed_loom_bundle_matches_a_fresh_build"),
    ("tests.test_render_harness", None),
]


def gates_that_did_not_run(xml_path):
    """Read the junit report; return a list of gates that skipped or never appeared.

    Empty list == every skip-prone check in the pytest job actually executed here. This is
    the difference between "the environment looks right" and "the gate ran": the harness
    skips on a failed browser LAUNCH, and the bundle test skips on an env var or a missing
    dist file, neither of which a preflight can see from outside the run."""
    try:
        root = ET.parse(xml_path).getroot()
    except Exception as exc:                     # noqa: BLE001 -- no report is its own answer
        return ["the pytest run produced no readable junit report (%s), so nothing here can "
                "say whether the skip-prone checks ran" % exc]
    cases = [(c.get("classname") or "", c.get("name") or "",
              c.find("skipped") is not None)
             for c in root.iter("testcase")]
    gaps = []
    for module, name in REQUIRED_TO_RUN:
        if name is None:
            ran = [c for c in cases if c[0] == module and not c[2]]
            if not ran:
                gaps.append("%s contributed no test that actually ran -- the whole module "
                            "skipped (no playwright, or a chromium that will not launch), "
                            "so every guard in it was decoration on this run" % module)
            continue
        matches = [c for c in cases if c[0] == module and c[1] == name]
        if not matches:
            gaps.append("%s::%s was never collected" % (module, name))
        elif all(c[2] for c in matches):
            gaps.append("%s::%s SKIPPED -- the stale-bundle gate did not run" % (module, name))
    return gaps


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    dry = False
    for arg in argv:
        if arg in ("-n", "--dry-run"):
            dry = True
        elif arg in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            print("unknown argument %r (try --help)" % arg)
            return 2

    gaps = preflight()
    if gaps:
        print("\n== preflight: this environment is not what CI gives its jobs ==")
        for gap, fix in gaps:
            print("  MISSING: %s" % gap)
            print("     fix:  %s" % fix)
    else:
        print("\n== preflight: node, gallery/ and loom/ build tooling, a %s that launches "
              "-- all present ==" % harness_engine())

    if dry:
        print("\n-- dry run: nothing below is executed --")
        for job in JOBS:
            print("   would run: %s" % job)
    if gaps:
        print("\nFAIL: preflight -- a run without these would report green on checks that\n"
              "      never ran. Fix the above, then re-run.")
        return 1
    if dry:
        return 0

    fails = []

    # The junit report goes to a temp dir, never into the checkout: `git status --porcelain`
    # is the loom job's own instrument a few lines down, and a stray report file would be
    # noise in it (and in the owner's next `git status`).
    with tempfile.TemporaryDirectory(prefix="mg-ci-local-") as tmp:
        report = os.path.join(tmp, "pytest.xml")
        if not _run(JOBS[0], [sys.executable, "-m", "pytest", "-q",
                              "--ignore=tests/test_similar.py",
                              "--junitxml=%s" % report]):
            fails.append("pytest")
        skipped_gates = gates_that_did_not_run(report)

    print("\n== %s ==" % JOBS[1])
    if skipped_gates:
        for gap in skipped_gates:
            print("  DID NOT RUN: %s" % gap)
        print("  A green pytest that skipped one of these says nothing about the bundle it\n"
              "  never rebuilt or the layout it never measured.\n"
              "  Which of these CI itself runs, exactly: its pytest job installs node,\n"
              "  `npm ci`s gallery/ and installs chromium --with-deps, so the GALLERY bundle\n"
              "  test and the RENDER HARNESS really run there. It never installs\n"
              "  loom/node_modules, so the LOOM bundle test skips in CI every time -- CI\n"
              "  catches a stale loom/dist in its other job instead, the check mirrored\n"
              "  below as [2b]. So a loom-bundle skip here is a local-only gate going\n"
              "  quiet, and the other two are gates CI will run whether you did or not.")
        fails.append("a CI check skipped locally")
    else:
        print("  both bundle-freshness tests ran, and the render harness really rendered.")

    build_ok = _run(JOBS[2], "npm run build", cwd=LOOM, shell=True)
    if not build_ok:
        fails.append("loom build")
    else:
        # `git status --porcelain`, NOT `git diff` -- the same choice CI's own
        # "Fail if the committed bundle is stale" step makes and explains: git diff
        # (no --cached) compares the worktree to the INDEX, so it sees neither a new
        # untracked file in dist/ nor a bundle already `git add`ed and different from
        # the committed blob. The ordinary `npm run build; git add loom/dist; push`
        # flow hits exactly that, and reported "matches a fresh build" on a bundle CI
        # would reject.
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "loom/dist"],
                               cwd=ROOT, capture_output=True, text=True)
        if dirty.returncode != 0:
            print("\n== %s ==" % JOBS[3])
            print("  git status failed:\n" + (dirty.stderr or "").strip())
            fails.append("loom/dist check")
        elif dirty.stdout.strip():
            print("\n== %s ==" % JOBS[3])
            print("  STALE: loom/dist does not match a fresh build.")
            print("  Fix:  cd loom && npm run build   then commit loom/dist/")
            print(dirty.stdout.rstrip())
            subprocess.run(["git", "--no-pager", "diff", "--stat", "--", "loom/dist"],
                           cwd=ROOT)
            fails.append("loom/dist stale")
        else:
            print("\n== %s ==\n  matches a fresh build." % JOBS[3])

    if not _run(JOBS[4], "node --test", cwd=LOOM, shell=True):
        fails.append("loom node tests")

    print()
    if fails:
        print("FAIL: " + ", ".join(fails) + "  -- do NOT push.")
        return 1
    print("PASS: every CI job is green -- safe to push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
