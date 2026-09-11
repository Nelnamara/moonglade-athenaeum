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

PREFLIGHT, and why it refuses rather than warns. Three checks in CI's pytest job are
written to SKIP themselves when their toolchain is absent -- the committed-gallery-bundle
and committed-loom-bundle freshness tests (they need node_modules) and the whole render
harness (it needs a playwright browser). CI installs all of it, so those checks really run
there. A local run without them prints the same "green" while saying nothing about the
bundle it would have rebuilt or the layout it would have measured: precisely how a stale
gallery/dist earns a green pre-merge command and a red CI. So this refuses to start until
the environment carries what CI's `npm ci` / `playwright install` steps provide, and names
the command that fixes each gap. Nothing is installed for you -- an install is the kind of
thing you should watch.

Exit 0 only if every job passes. Green here == safe to push. It is a long run --
start it when you are done editing, not between edits.
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOM = os.path.join(ROOT, "loom")
GALLERY = os.path.join(ROOT, "gallery")

JOBS = [
    "[1] pytest  (CI's exact command; render harness included)",
    "[2a] loom: rebuild the esbuild bundle",
    "[2b] loom/dist is a fresh build  (git status --porcelain, as CI checks it)",
    "[3] loom node suite  (node --test)",
]


def _run(desc, cmd, cwd=None, shell=False):
    print("\n== %s ==" % desc)
    sys.stdout.flush()
    return subprocess.run(cmd, cwd=cwd or ROOT, shell=shell).returncode == 0


def _chromium_missing():
    """'' when a usable chromium is installed, else the reason it is not.

    Resolves the binary through playwright's own path logic and stats it -- no launch, no
    download, no network. `playwright install chromium` is idempotent, but running it for
    the user would turn a pre-merge check into an installer."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:                     # noqa: BLE001 -- any import failure is "absent"
        return "the playwright package is not importable (%s)" % exc
    try:
        pw = sync_playwright().start()
    except Exception as exc:                     # noqa: BLE001
        return "playwright will not start (%s)" % exc
    try:
        exe = pw.chromium.executable_path
    except Exception as exc:                     # noqa: BLE001
        return "playwright cannot resolve a chromium path (%s)" % exc
    finally:
        pw.stop()
    return "" if os.path.exists(exe) else "no chromium binary at %s" % exe


def preflight():
    """The environment CI's install steps provide. Returns a list of (gap, fix) pairs."""
    gaps = []
    if shutil.which("node") is None:
        gaps.append(("node is not on PATH -- both bundle-freshness tests and the whole "
                     "loom-node-tests job need it", "install Node 22 (CI's version)"))
    if not os.path.isfile(os.path.join(GALLERY, "node_modules", "vite", "bin", "vite.js")):
        gaps.append(("gallery/node_modules is missing, so "
                     "test_committed_gallery_bundle_matches_a_fresh_build SKIPS and a stale "
                     "committed gallery/dist would sail through this run",
                     "cd gallery && npm ci"))
    if not os.path.isdir(os.path.join(LOOM, "node_modules", "esbuild")):
        gaps.append(("loom/node_modules is missing, so the loom bundle cannot be rebuilt "
                     "with the esbuild version pinned in loom/package-lock.json",
                     "cd loom && npm ci"))
    chromium = _chromium_missing()
    if chromium:
        gaps.append(("the render harness would skip itself -- %s" % chromium,
                     "python -m playwright install chromium"))
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
        print("\n== preflight: node, gallery/ and loom/ build tooling, chromium -- all present ==")

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

    if not _run(JOBS[0], [sys.executable, "-m", "pytest", "-q",
                          "--ignore=tests/test_similar.py"]):
        fails.append("pytest")

    build_ok = _run(JOBS[1], "npm run build", cwd=LOOM, shell=True)
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
            print("\n== %s ==" % JOBS[2])
            print("  git status failed:\n" + (dirty.stderr or "").strip())
            fails.append("loom/dist check")
        elif dirty.stdout.strip():
            print("\n== %s ==" % JOBS[2])
            print("  STALE: loom/dist does not match a fresh build.")
            print("  Fix:  cd loom && npm run build   then commit loom/dist/")
            print(dirty.stdout.rstrip())
            subprocess.run(["git", "--no-pager", "diff", "--stat", "--", "loom/dist"],
                           cwd=ROOT)
            fails.append("loom/dist stale")
        else:
            print("\n== %s ==\n  matches a fresh build." % JOBS[2])

    if not _run(JOBS[3], "node --test", cwd=LOOM, shell=True):
        fails.append("loom node tests")

    print()
    if fails:
        print("FAIL: " + ", ".join(fails) + "  -- do NOT push.")
        return 1
    print("PASS: every CI job is green -- safe to push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
