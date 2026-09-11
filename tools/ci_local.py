#!/usr/bin/env python3
"""Local mirror of the GitHub "Tests" workflow (.github/workflows/tests.yml).

Run this from anywhere BEFORE pushing to master, so master never goes red on
something a local run could have caught:

    python tools/ci_local.py

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

Exit 0 only if every job passes. Green here == safe to push. It is a long run --
start it when you are done editing, not between edits.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOM = os.path.join(ROOT, "loom")


def _run(desc, cmd, cwd=None, shell=False):
    print("\n== %s ==" % desc)
    sys.stdout.flush()
    return subprocess.run(cmd, cwd=cwd or ROOT, shell=shell).returncode == 0


def main():
    fails = []

    if not _run("[1] pytest  (CI's exact command; render harness included)",
                [sys.executable, "-m", "pytest", "-q",
                 "--ignore=tests/test_similar.py"]):
        fails.append("pytest")

    build_ok = _run("[2a] loom: rebuild the esbuild bundle", "npm run build",
                    cwd=LOOM, shell=True)
    if not build_ok:
        fails.append("loom build")
    else:
        stale = subprocess.run(["git", "diff", "--quiet", "--", "loom/dist"],
                               cwd=ROOT).returncode != 0
        if stale:
            print("\n== [2b] loom/dist is a fresh build ==")
            print("  STALE: loom/dist differs from a fresh build.")
            print("  Fix:  cd loom && npm run build   then commit loom/dist/")
            subprocess.run(["git", "--no-pager", "diff", "--stat", "--", "loom/dist"],
                           cwd=ROOT)
            fails.append("loom/dist stale")
        else:
            print("\n== [2b] loom/dist is a fresh build ==\n  matches a fresh build.")

    if not _run("[3] loom node suite  (node --test)", "node --test",
                cwd=LOOM, shell=True):
        fails.append("loom node tests")

    print()
    if fails:
        print("FAIL: " + ", ".join(fails) + "  -- do NOT push.")
        return 1
    print("PASS: every CI job is green -- safe to push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
