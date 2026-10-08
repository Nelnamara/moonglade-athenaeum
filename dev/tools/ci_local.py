#!/usr/bin/env python3
"""Runs CI's commands on THIS machine, before you push.

    python dev/tools/ci_local.py            # run them (from the repo root, or anywhere)
    python dev/tools/ci_local.py --dry-run  # list the jobs and run the file/package
                                            # presence checks; launches no browser and
                                            # executes no job

WHAT THIS IS, in one statement. It runs CI's commands -- the two pytest halves as CI invokes
them, then the loom build, the stale-bundle check and `node --test` -- on THIS machine's
Python, Node, OS and installed packages. It does not reproduce CI's environment. Green here
means those commands passed here and the skip-prone gates really ran; only CI's own run
proves CI.

THE JOBS. `.github/workflows/tests.yml` has three, and this runs all of them:

  1. pytest, in two halves -- CI's command, `pytest -q dev/tests
     --ignore=dev/tests/test_similar.py` (test_similar needs the optional Pixeltable/CLIP
     index; CI skips it too), split by the `render` marker the way CI's `render-harness`
     and `pytest` jobs split it, each half spread over pytest-xdist workers and each with
     its own `--junitxml` (which only feeds job [1c]), from the repo root:
       [1a] `-m render -n 3` -- the browser-driven render harness. INCLUDED: a harness test
            that fails here is a bug to trace, not a reason to skip the file. Its browser and
            its app server are module-scoped, so every worker launches its own browser and
            serves its own app on its own ephemeral port.
       [1b] `-m "not render" -n <the rest of the cores>` -- everything else.
     They are separate RUNS, not one run with a deselect: the harness's playwright keeps an
     asyncio loop running in its worker's thread, and a test of its own that calls
     `asyncio.run()` (dev/tests/test_watch.py) must never share a process with it. On a
     machine with the cores for it (RENDER_WORKERS plus two) the halves run side by side,
     each line of output prefixed with its half's name; on a smaller one they run one after
     the other, the rest on `-n auto`. Worker counts are this machine's, not CI's: each CI
     job has a runner of its own and uses `-n auto`.
  2. loom-node-tests -- AFTER both halves: rebuild loom/dist, FAIL if the committed bundle is
     stale, then run the Loom's `node --test` source-structure + logic suite. This is the job
     a Python-only local run misses: a front-end MOVE/rename goes red here while pytest stays
     green (learned twice, 2026-09-08/09). It waits for pytest because the rebuild writes
     loom/dist in place, under a run whose loom-bundle test reads it.

PREFLIGHT, and why it refuses rather than warns. Some checks in the pytest jobs are written
to SKIP themselves when what they need is absent -- the committed-gallery-bundle and
committed-loom-bundle freshness tests (they need node_modules), the whole render harness
(it needs a browser that launches) and the pack-art tests in test_branding_roles.py (they
read the pack's role art from the folder MOONGLADE_PACK_ART names; the art is not in the
repo). A run missing any of them prints the same "green" while saying nothing about the
bundle it would have rebuilt, the layout it would have measured or the art it would have
checked. So the run refuses to start until these hold: gallery/node_modules and
loom/node_modules are present, the harness engine actually launches, MOONGLADE_PACK_ART
names a folder, and every package on CI's `pip install` line imports on this interpreter.
It names the command that fixes each gap and installs nothing -- an install is the kind of
thing you should watch.

CI's pip lines are READ OFF the workflow (`ci_pip_packages`), never copied into this file, so
they follow CI when a line changes; a token on one that is not a plain distribution name
refuses the run rather than being half-read. pytest-xdist is on them, so preflight requires
it: both halves are `-n` runs.

AND THEN IT CHECKS THAT THEY REALLY RAN, which is the half a preflight cannot do. A
preflight answers "could this check run", and those are not the same sentence: a browser
binary can be on disk and still refuse to launch, and the harness skips on the LAUNCH, not
on the path; `gallery/dist/app.css` can be missing, or `MOONGLADE_SKIP_GALLERY_BUILD` set,
and the bundle test skips itself with every preflight box ticked. So each pytest half is run
with a junit report and both reports are read afterwards: both bundle-freshness tests and
the pack-art tests must have actually executed, and the render harness must have contributed
at least one non-skipped test. A gate that skipped fails this run. A green that skipped the
gate you needed is worse than a red.

Exit 0 only if every job passes. It prints each pytest half's wall-clock and the whole run's.
Start it when you are done editing, not between edits.
"""
import importlib.util
import locale
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET

# This file is dev/tools/ci_local.py: the repo root is two folders up.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOOM = os.path.join(ROOT, "loom")
GALLERY = os.path.join(ROOT, "gallery")
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "tests.yml")

JOBS = [
    "[1a] pytest, render half  (CI's command, -m render, xdist; the browser harness)",
    "[1b] pytest, the rest  (CI's command, -m \"not render\", xdist)",
    "[1c] the skip-prone checks actually ran  (read off both halves' junit reports)",
    "[2a] loom: rebuild the esbuild bundle",
    "[2b] loom/dist is a fresh build  (git status --porcelain, as CI checks it)",
    "[3] loom node suite  (node --test)",
]

# CI's pytest command; each half adds its marker, its worker count and its own junit report.
PYTEST = [sys.executable, "-m", "pytest", "-q", "dev/tests", "--ignore=dev/tests/test_similar.py"]

# Workers for the render half. Each one launches a browser of its own and serves an app of its
# own (dev/tests/test_render_harness.py's module-scoped render_browser and render_server), so
# a worker costs a browser's processes, not one core; three keep the harness moving while
# leaving the rest of the machine to the other half.
RENDER_WORKERS = 3


def pytest_halves(cpus=None):
    """(side_by_side, [(name, job, marker args), ...]) for this machine.

    Side by side when there are cores for both: the render half's workers plus at least two
    for the rest, which then takes every core the harness does not. Otherwise one after the
    other, the rest on `-n auto` (every core, once the harness is done with them)."""
    cpus = cpus or os.cpu_count() or 1
    side_by_side = cpus >= RENDER_WORKERS + 2
    rest = str(cpus - RENDER_WORKERS) if side_by_side else "auto"
    return side_by_side, [
        ("render", JOBS[0], ["-m", "render", "-n", str(RENDER_WORKERS)]),
        ("rest", JOBS[1], ["-m", "not render", "-n", rest]),
    ]


def _clock(seconds):
    m, s = divmod(int(round(seconds)), 60)
    return "%dm %02ds" % (m, s)


def _run(desc, cmd, cwd=None, shell=False):
    print("\n== %s ==" % desc)
    sys.stdout.flush()
    return subprocess.run(cmd, cwd=cwd or ROOT, shell=shell).returncode == 0


_PRINT = threading.Lock()


def _pump(proc, prefix, ended):
    """Copy a child's output to ours a line at a time, each line under its half's name, so two
    runs sharing one console stay readable; then wait for the child and note when it exited,
    so a half that finishes first is timed to ITS exit, not to the other's. The child writes
    its pipe in this machine's locale encoding (pytest escapes what that cannot carry), so
    that is what is decoded."""
    enc = locale.getpreferredencoding(False)
    for raw in iter(proc.stdout.readline, b""):
        line = raw.decode(enc, errors="replace").rstrip("\r\n")
        with _PRINT:
            print(prefix + line)
            sys.stdout.flush()
    proc.stdout.close()
    proc.wait()
    ended.append(time.monotonic())


def run_pytest_halves(tmp):
    """Run both pytest halves. Returns [(name, passed, seconds, junit path), ...] and the
    phase's own wall-clock."""
    side_by_side, halves = pytest_halves()
    out = []
    t_phase = time.monotonic()
    if not side_by_side:
        for name, job, args in halves:
            report = os.path.join(tmp, name + ".xml")
            t0 = time.monotonic()
            ok = _run(job, PYTEST + args + ["--junitxml=%s" % report])
            out.append((name, ok, time.monotonic() - t0, report))
        return out, time.monotonic() - t_phase

    width = max(len(name) for name, _, _ in halves)
    running = []
    try:
        for name, job, args in halves:
            report = os.path.join(tmp, name + ".xml")
            cmd = PYTEST + args + ["--junitxml=%s" % report]
            with _PRINT:
                print("\n== %s ==\n   side by side; its lines carry [%s]: %s"
                      % (job, name, subprocess.list2cmdline(cmd[1:])))
                sys.stdout.flush()
            t0 = time.monotonic()
            proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT)
            ended = []
            pump = threading.Thread(target=_pump, daemon=True,
                                    args=(proc, "[%s] " % name.ljust(width), ended))
            pump.start()
            running.append((name, proc, pump, t0, ended, report))
        for name, proc, pump, t0, ended, report in running:
            pump.join()
            out.append((name, proc.returncode == 0, ended[0] - t0, report))
    finally:
        for _, proc, _, _, _, _ in running:
            if proc.poll() is None:                 # interrupted: leave no run behind
                proc.kill()
    return out, time.monotonic() - t_phase


# Distribution name -> the module that proves it is importable, where the two differ.
# Everything else is its own name with `-` as `_` (pytest-mock -> pytest_mock).
_IMPORT_NAME = {"pillow": "PIL", "pytest-xdist": "xdist"}
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
    being CI's the first time .github/workflows/tests.yml is edited. Each pytest job has its
    own `pip install` line (the render half and the rest run as separate jobs), and this run
    executes both halves, so the list is every package on any of them, in first-seen order.
    At least one line must be findable -- none means the step moved or was renamed -- and
    every line must read cleanly; both are gaps rather than guesses."""
    rel = os.path.relpath(WORKFLOW, ROOT).replace(os.sep, "/")
    try:
        with open(WORKFLOW, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return None, "%s is unreadable (%s)" % (rel, exc)
    lines = [ln for ln in text.splitlines()
             if "pip install" in ln and not ln.lstrip().startswith("#")]
    if not lines:
        return None, "%s has no `pip install` line -- CI's install step moved" % rel
    out = []
    for line in lines:
        pkgs, offender = _dist_names(line.split("pip install", 1)[1].split())
        if pkgs is None:
            return None, ("a CI `pip install` line carries the token %r, which is not a plain "
                          "distribution name -- this script does not interpret it, and will "
                          "not read the rest of the line as though it were not there"
                          % offender)
        if not pkgs:
            return None, "a CI `pip install` line names no packages"
        out.extend(p for p in pkgs if p not in out)
    return out, ""


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
    launches THAT (dev/tests/test_render_harness.py). A preflight that hard-codes chromium
    answers a question nobody asked under `MG_HARNESS_BROWSER=webkit`: it ticks its box off
    a chromium the run will never touch, and every harness test then skips on the webkit
    binary that was never installed. Returns the raw value when it is not a known engine --
    the caller reports that as its own gap, because the harness pytest.fail()s on it."""
    return (os.environ.get("MG_HARNESS_BROWSER") or "chromium").strip().lower()


def _engine_unusable(engine):
    """'' when `engine` LAUNCHES here, else the reason it does not.

    It launches one and closes it, rather than resolving the path and stating it, because
    the path is not what the harness skips on: `render_browser` calls `browser.launch()`
    and skips on the exception it raises (dev/tests/test_render_harness.py). A binary that is
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


def default_pack_art():
    """The pack's role art in its public layout, when MOONGLADE_PACK_ART is unset: the private
    repo's design mirror beside this checkout (`../moonglade-internal/design/handoff-*/assets/
    branding`, the newest handoff), which tools/mirror_pack_to_design.py refreshes from every
    new pack. A worktree under `_wt/<name>/` reaches it the same way, through the
    `moonglade-internal` junction beside the checkout. "" when there is none."""
    for base in (os.path.join(ROOT, "..", "moonglade-internal"),):
        design = os.path.join(base, "design")
        try:
            handoffs = sorted(d for d in os.listdir(design) if d.startswith("handoff-"))
        except OSError:
            continue
        for h in reversed(handoffs):
            art = os.path.join(design, h, "assets", "branding")
            if os.path.isdir(art):
                return os.path.normpath(art)
    return ""


def preflight(launch_engine=True):
    """The three things a meaningful run needs. Returns a list of (gap, fix) pairs.

    `launch_engine=False` leaves the browser alone and checks only what is on disk and on
    the import path -- what `--dry-run` asks for."""
    gaps = []
    ci_pkgs, problem = ci_pip_packages()
    if ci_pkgs is None:
        gaps.append(("CI's own `pip install` step could not be read, so this run cannot say "
                     "whether this interpreter carries what CI's pytest jobs install -- %s"
                     % problem,
                     "fix the workflow line, or teach dev/tools/ci_local.py to read it"))
    else:
        missing = [p for p in ci_pkgs if not _importable(p)]
        if missing:
            gaps.append(("CI's pytest jobs install %s, which this interpreter cannot import "
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
    # The pytest child inherits this environment, so the variable reaches conftest's pack_art
    # fixture as it is. There is no default folder: the art is not in the repo, and a test may
    # not read the checkout's own pack (conftest's hermeticity rule).
    art = os.environ.get("MOONGLADE_PACK_ART", "").strip() or default_pack_art()
    if art:
        os.environ["MOONGLADE_PACK_ART"] = art
    if not art:
        gaps.append(("MOONGLADE_PACK_ART is unset and no private design mirror sits beside this "
                     "checkout, so the pack-art tests in "
                     "dev/tests/test_branding_roles.py SKIP (conftest's pack_art fixture) and "
                     "nothing in this run checks the pack's own role art against its roles",
                     "set MOONGLADE_PACK_ART to the folder holding the pack's role art in its "
                     "public layout (login_nel.webp, nel_spinner.png, mascots/trk_done.png, "
                     "rewards/claim.png ...)"))
    elif not os.path.isdir(art):
        gaps.append(("MOONGLADE_PACK_ART names %r, which is not a folder, so the pack-art "
                     "tests in dev/tests/test_branding_roles.py SKIP" % art,
                     "point MOONGLADE_PACK_ART at the folder holding the pack's role art"))
    return gaps


# The checks inside the pytest jobs that are written to skip themselves. Preflight argues
# they CAN run; this is how the run proves they DID. (module, test, gate) for a named test;
# (module, None, None) for "this whole module must have contributed something".
#
# The gallery bundle test and the harness are also gates in CI's own pytest jobs (`pytest`
# and `render-harness`). The loom bundle test is not -- neither job installs
# loom/node_modules, so it skips there and CI catches a stale loom/dist in the
# loom-node-tests job instead ([2b] below). It is
# required here anyway: it is the one check that compares the committed bundle to a rebuild
# inside the pytest run, and a local gate going quiet is still a local gate going quiet.
# The pack-art tests are the same kind: the art is not in the repo, so they skip in CI every
# time, and this run is the only place they can bite. Preflight refuses a run without
# MOONGLADE_PACK_ART; a skip here means the folder it names lacks one of the role images.
REQUIRED_TO_RUN = [
    ("tests.test_js_syntax", "test_committed_gallery_bundle_matches_a_fresh_build",
     "the stale-bundle gate"),
    ("tests.test_js_syntax", "test_committed_loom_bundle_matches_a_fresh_build",
     "the stale-bundle gate"),
    ("tests.test_render_harness", None, None),
    ("tests.test_branding_roles", "test_every_pack_default_passes_its_own_roles_check",
     "the pack-art gate"),
    ("tests.test_branding_roles", "test_every_pack_default_can_be_uploaded_as_the_override_of_itself",
     "the pack-art gate"),
    ("tests.test_branding_roles", "test_the_shape_rule_is_not_vacuous_on_the_packs_own_art",
     "the pack-art gate"),
]


def gates_that_did_not_run(xml_paths):
    """Read the pytest halves' junit reports; return a list of gates that skipped or never
    appeared in any of them.

    Empty list == every skip-prone check in the pytest halves actually executed here. This is
    the difference between "the environment looks right" and "the gate ran": the harness
    skips on a failed browser LAUNCH, the bundle test skips on an env var or a missing
    dist file, and the pack-art tests skip on a folder that lacks one of the role images,
    none of which a preflight can see from outside the run. A half with no readable report
    is a gap of its own: whatever it held cannot be said to have run."""
    if isinstance(xml_paths, str):
        xml_paths = [xml_paths]
    cases, gaps = [], []
    for xml_path in xml_paths:
        try:
            root = ET.parse(xml_path).getroot()
        except Exception as exc:                 # noqa: BLE001 -- no report is its own answer
            gaps.append("the pytest run that writes %s produced no readable junit report (%s), "
                        "so nothing here can say whether the skip-prone checks in it ran"
                        % (os.path.basename(xml_path), exc))
            continue
        cases.extend((c.get("classname") or "", c.get("name") or "",
                      c.find("skipped") is not None)
                     for c in root.iter("testcase"))
    for module, name, gate in REQUIRED_TO_RUN:
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
            gaps.append("%s::%s SKIPPED -- %s did not run" % (module, name, gate))
    return gaps


def main(argv=None):
    try:
        # Two halves' output passes through here; a character this console cannot show must
        # not take the run down mid-report.
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
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
              "and\n   loom/node_modules are present, MOONGLADE_PACK_ART names a folder. %s was "
              "NOT\n   launched -- a dry run starts no browser, so it cannot say whether the "
              "harness would run ==" % harness_engine())
    else:
        print("\n== preflight: CI's pip list imports here, gallery/node_modules and "
              "loom/node_modules\n   are present, MOONGLADE_PACK_ART names a folder, and %s "
              "launches ==" % harness_engine())

    if dry:
        side_by_side, halves = pytest_halves()
        print("\n-- dry run: nothing below is executed --")
        for name, job, args in halves:
            print("   would run: %s\n              %s" % (
                job, subprocess.list2cmdline(PYTEST[1:] + args + ["--junitxml=<tmp>/%s.xml"
                                                                  % name])))
        print("              (%s, on this machine's %d core(s))"
              % ("side by side" if side_by_side else "one after the other",
                 os.cpu_count() or 1))
        for job in JOBS[2:]:
            print("   would run: %s" % job)
    if gaps:
        print("\nFAIL: preflight -- a run without these would report green on checks that\n"
              "      never ran. Fix the above, then re-run.")
        return 1
    if dry:
        return 0

    fails = []
    t_start = time.monotonic()

    # The junit reports go to a temp dir, never into the checkout: `git status --porcelain`
    # is the loom job's own instrument a few lines down, and a stray report file would be
    # noise in it (and in the owner's next `git status`).
    with tempfile.TemporaryDirectory(prefix="mg-ci-local-") as tmp:
        halves, t_pytest = run_pytest_halves(tmp)
        for name, ok, _, _ in halves:
            if not ok:
                fails.append("pytest (%s half)" % name)
        skipped_gates = gates_that_did_not_run([report for _, _, _, report in halves])

    print("\n== pytest wall-clock ==")
    for name, ok, seconds, _ in halves:
        print("  %-6s half  %s  %s" % (name, _clock(seconds), "passed" if ok else "FAILED"))
    print("  both halves %s" % _clock(t_pytest))

    print("\n== %s ==" % JOBS[2])
    if skipped_gates:
        for gap in skipped_gates:
            print("  DID NOT RUN: %s" % gap)
        print("  A green pytest that skipped one of these says nothing about the bundle it\n"
              "  never rebuilt or the layout it never measured.\n"
              "  Which of these CI itself runs, exactly: its pytest job installs node and\n"
              "  `npm ci`s gallery/, so the GALLERY bundle test really runs there, and its\n"
              "  render-harness job installs chromium --with-deps, so the RENDER HARNESS\n"
              "  does. Neither installs loom/node_modules, so the LOOM bundle test skips in\n"
              "  CI every time -- CI catches a stale loom/dist in its loom job instead, the\n"
              "  check mirrored below as [2b]. The PACK-ART tests skip in CI every time too:\n"
              "  the art is not in the repo. So a loom-bundle or pack-art skip here is a\n"
              "  local-only gate going quiet, and the gallery bundle and the harness are\n"
              "  gates CI will run whether you did or not.")
        fails.append("a CI check skipped locally")
    else:
        print("  both bundle-freshness tests and the pack-art tests ran, and the render "
              "harness\n  really rendered.")

    build_ok = _run(JOBS[3], "npm run build", cwd=LOOM, shell=True)
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
            print("\n== %s ==" % JOBS[4])
            print("  git status failed:\n" + (dirty.stderr or "").strip())
            fails.append("loom/dist check")
        elif dirty.stdout.strip():
            print("\n== %s ==" % JOBS[4])
            print("  STALE: loom/dist does not match a fresh build.")
            print("  Fix:  cd loom && npm run build   then commit loom/dist/")
            print(dirty.stdout.rstrip())
            subprocess.run(["git", "--no-pager", "diff", "--stat", "--", "loom/dist"],
                           cwd=ROOT)
            fails.append("loom/dist stale")
        else:
            print("\n== %s ==\n  matches a fresh build." % JOBS[4])

    if not _run(JOBS[5], "node --test", cwd=LOOM, shell=True):
        fails.append("loom node tests")

    print("\n== wall-clock ==")
    for name, ok, seconds, _ in halves:
        print("  pytest, %-6s half  %s" % (name, _clock(seconds)))
    print("  pytest, both        %s" % _clock(t_pytest))
    print("  the whole run       %s" % _clock(time.monotonic() - t_start))

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
