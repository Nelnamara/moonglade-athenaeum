#!/usr/bin/env python3
"""Runs CI's commands on THIS machine, before you push.

    python tools/ci_local.py            # run them
    python tools/ci_local.py --dry-run  # list the jobs and run the file/package presence
                                        # checks; launches no browser and executes no job

WHAT THIS IS, in one statement. It runs CI's commands -- pytest exactly as CI invokes it,
then the loom build, the stale-bundle check and `node --test` -- on THIS machine's Python,
Node, OS and installed packages. It does not reproduce CI's environment. Green here means
those commands passed here and the skip-prone gates really ran; only CI's own run proves CI.

THE JOBS. `.github/workflows/tests.yml` has two, and this runs both:

  1. pytest -- CI's exact command, `pytest -q --ignore=tests/test_similar.py`
     (test_similar needs the optional Pixeltable/CLIP index; CI skips it too). The
     browser-driven render harness is INCLUDED: a harness test that fails here is a bug
     to trace, not a reason to skip the file.
  2. loom-node-tests -- rebuild loom/dist, FAIL if the committed bundle is stale, then run
     the Loom's `node --test` source-structure + logic suite. This is the job a Python-only
     local run misses: a front-end MOVE/rename goes red here while pytest stays green
     (learned twice, 2026-09-08/09).

PREFLIGHT, and why it refuses rather than warns. Three checks in the pytest job are written
to SKIP themselves when their toolchain is absent -- the committed-gallery-bundle and
committed-loom-bundle freshness tests (they need node_modules) and the whole render harness
(it needs a browser that launches). A run missing any of them prints the same "green" while
saying nothing about the bundle it would have rebuilt or the layout it would have measured.
So the run refuses to start until three things hold: gallery/node_modules and
loom/node_modules are present, the harness engine actually launches, and every package on
CI's `pip install` line imports on this interpreter. It names the command that fixes each
gap and installs nothing -- an install is the kind of thing you should watch.

CI's pip line is READ OFF the workflow (`ci_pip_packages`), never copied into this file, so
it follows CI when the line changes; a token on it that is not a plain distribution name
refuses the run rather than being half-read.

AND THEN IT CHECKS THAT THEY REALLY RAN, which is the half a preflight cannot do. A
preflight answers "could this check run", and those are not the same sentence: a browser
binary can be on disk and still refuse to launch, and the harness skips on the LAUNCH, not
on the path; `gallery/dist/app.css` can be missing, or `MOONGLADE_SKIP_GALLERY_BUILD` set,
and the bundle test skips itself with every preflight box ticked. So the pytest job is run
with a junit report and the report is read afterwards: both bundle-freshness tests must
have actually executed, and the render harness must have contributed at least one
non-skipped test. A gate that skipped fails this run. A green that skipped the gate you
needed is worse than a red.

Exit 0 only if every job passes. It is a long run -- start it when you are done editing,
not between edits.
"""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOM = os.path.join(ROOT, "loom")
GALLERY = os.path.join(ROOT, "gallery")
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "tests.yml")

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


# Distribution name -> the module that proves it is importable, where the two differ.
# Everything else is its own name with `-` as `_` (pytest-mock -> pytest_mock).
_IMPORT_NAME = {"pillow": "PIL"}
# A plain distribution name and nothing else: no specifier, no marker, no extra, no quote.
_DIST_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _dist_names(tokens):
    """Distribution names off CI's install line. Returns (names, offending token).

    Every token must be a plain distribution name. Anything else -- a flag (`-r`,
    `--upgrade`), a quoted or version-pinned requirement (`"flask>=3"`, `zeroconf>=0.130`),
    a trailing `\\` continuation -- returns `(None, that token)` so the caller can refuse
    the run and print it verbatim. Dropping it silently is the failure worth designing
    against: preflight would then tick its box against a shorter list than CI installs and
    call that a mirror.
    """
    out = []
    for tok in tokens:
        if not _DIST_NAME.match(tok):
            return None, tok
        out.append(tok.lower())
    return out, ""


def ci_pip_packages():
    """CI's install list, READ OFF the workflow. Returns (packages, problem).

    Read, never copied: a list transcribed into this file is a list that silently stops
    being CI's the first time .github/workflows/tests.yml is edited. Exactly one
    `pip install` line must be findable -- zero means the step moved or was renamed, more
    than one means this script cannot tell which belongs to the pytest job, and both are
    gaps rather than guesses."""
    rel = os.path.relpath(WORKFLOW, ROOT).replace(os.sep, "/")
    try:
        with open(WORKFLOW, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return None, "%s is unreadable (%s)" % (rel, exc)
    lines = [ln for ln in text.splitlines()
             if "pip install" in ln and not ln.lstrip().startswith("#")]
    if len(lines) != 1:
        return None, ("%s has %d `pip install` line(s) -- this script can only read CI's "
                      "install step when there is exactly one" % (rel, len(lines)))
    tokens = lines[0].split("pip install", 1)[1].split()
    pkgs, offender = _dist_names(tokens)
    if pkgs is None:
        return None, ("CI's `pip install` line carries the token %r, which is not a plain "
                      "distribution name -- this script does not interpret it, and will "
                      "not read the rest of the line as though it were not there" % offender)
    if not pkgs:
        return None, "CI's `pip install` line names no packages"
    return pkgs, ""


def _import_name(dist):
    """The module `dist` is proved importable by."""
    return _IMPORT_NAME.get(dist, dist.replace("-", "_"))


def _importable(dist):
    """True when the distribution `dist` can be imported on THIS interpreter."""
    try:
        return importlib.util.find_spec(_import_name(dist)) is not None
    except Exception:                            # noqa: BLE001 -- a half-installed dist is absent
        return False


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
    present but cannot start passes a stat and fails a launch, so a stat-based preflight
    would tick its box and let every harness test skip. Costs about a second. Downloads
    nothing and installs nothing: an install is the kind of thing you should watch."""
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


def preflight(launch_engine=True):
    """The three things a meaningful run needs. Returns a list of (gap, fix) pairs.

    `launch_engine=False` leaves the browser alone and checks only what is on disk and on
    the import path -- what `--dry-run` asks for."""
    gaps = []
    ci_pkgs, problem = ci_pip_packages()
    if ci_pkgs is None:
        gaps.append(("CI's own `pip install` step could not be read, so this run cannot say "
                     "whether this interpreter carries what CI's pytest job installs -- %s"
                     % problem,
                     "fix the workflow line, or teach tools/ci_local.py to read it"))
    else:
        missing = [p for p in ci_pkgs if not _importable(p)]
        if missing:
            gaps.append(("CI's pytest job installs %s, which this interpreter cannot import "
                         "-- a test that touches one runs differently here than on CI"
                         % ", ".join("%s (tried `import %s`)" % (p, _import_name(p))
                                     for p in missing),
                         "pip install %s" % " ".join(missing)))
    if not os.path.isdir(os.path.join(GALLERY, "node_modules")):
        gaps.append(("gallery/node_modules is missing, so "
                     "test_committed_gallery_bundle_matches_a_fresh_build SKIPS and a stale "
                     "committed gallery/dist would sail through this run",
                     "cd gallery && npm ci"))
    if not os.path.isdir(os.path.join(LOOM, "node_modules")):
        gaps.append(("loom/node_modules is missing, so the loom bundle cannot be rebuilt "
                     "with the esbuild version pinned in loom/package-lock.json -- and "
                     "test_committed_loom_bundle_matches_a_fresh_build SKIPS on it too",
                     "cd loom && npm ci"))
    engine = harness_engine()
    if engine not in _ENGINES:
        gaps.append(("MG_HARNESS_BROWSER=%r is not one of %s -- the render harness "
                     "pytest.fail()s on it rather than running" % (engine, ", ".join(_ENGINES)),
                     "unset MG_HARNESS_BROWSER (chromium, CI's engine) or set a real one"))
    elif launch_engine:
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
                            "skipped (no playwright, or a browser that will not launch), "
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

    gaps = preflight(launch_engine=not dry)
    if gaps:
        print("\n== preflight: this machine is missing something the run needs ==")
        for gap, fix in gaps:
            print("  MISSING: %s" % gap)
            print("     fix:  %s" % fix)
    elif dry:
        print("\n== preflight (--dry-run): CI's pip list imports here, gallery/node_modules "
              "and\n   loom/node_modules are present. %s was NOT launched -- a dry run "
              "starts no\n   browser, so it cannot say whether the harness would run =="
              % harness_engine())
    else:
        print("\n== preflight: CI's pip list imports here, gallery/node_modules and "
              "loom/node_modules\n   are present, and %s launches ==" % harness_engine())

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
    print("PASS: CI's commands ran here, the way CI invokes them, on this machine's Python,\n"
          "      Node, OS and installed packages, and the skip-prone gates really ran. This\n"
          "      run does not reproduce CI's environment -- only CI's own run proves CI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
