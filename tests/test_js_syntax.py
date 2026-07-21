"""Regression guard: the gallery's JS is embedded in Python triple-quoted strings,
so an unescaped '\\n' (or stray quote/backtick) silently turns into invalid JS that
breaks the WHOLE <script> block at runtime (lightbox, keyboard nav, selection
restore all die). Render each page and syntax-check the embedded <script> blocks
with Node. Skips cleanly if Node isn't installed."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pixai_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_client

NODE = shutil.which("node")


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


@pytest.fixture
def client(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", prompt_preview="x",
             created_at="2025-01-01T00:00:00"),
        _row(media_id="2", filename="b_2.png", prompt_preview="y",
             created_at="2025-01-02T00:00:00"),
    ])
    return login_client(tmp_path)


def _scripts(html):
    return re.findall(r"<script>(.*?)</script>", html, flags=re.S)


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("path", ["/", "/image/1", "/health", "/duplicates", "/panel", "/login"])
def test_embedded_js_is_valid(client, tmp_path, path):
    html = client.get(path).get_data(as_text=True)
    blocks = _scripts(html)
    assert blocks, f"no <script> found on {path}"
    js = "\n;\n".join(blocks)
    f = tmp_path / "page.js"
    f.write_text(js, encoding="utf-8")
    out = tmp_path / "node.out"
    # Redirect to real files + DEVNULL stdin: some sandboxes can't duplicate
    # pytest's captured std handles (WinError 50). Skip if the OS blocks spawn.
    try:
        with open(out, "w", encoding="utf-8") as fh, open(os.devnull) as nul:
            rc = subprocess.call([NODE, "--check", str(f)],
                                 stdin=nul, stdout=fh, stderr=subprocess.STDOUT)
    except OSError as e:
        pytest.skip(f"cannot spawn node in this environment: {e}")
    assert rc == 0, f"{path} has invalid JS:\n{out.read_text(encoding='utf-8')}"


@pytest.mark.parametrize("path", ["/", "/panel", "/health", "/duplicates", "/loom", "/login"])
def test_every_page_carries_the_401_guard(client, path):
    """A browser crawl found ~90 fetch() calls across the inline JS, static/*.js and
    the Loom bundle, and NOT ONE inspected response status. The front door answers an
    expired session with a JSON 401 -- valid JSON -- so r.json() resolves, .catch never
    fires, and callers read the error body as data: the job poller decides "still
    running" and re-polls forever, the picker renders "No images found" for a full
    library.

    The fix is one interceptor in the shared head rather than 90 call-site edits, so
    what has to be guarded is its PRESENCE on every shell. Both BASE_HTML and
    _LOOM_SHELL must carry it -- they are separate templates, and the Loom's bundle
    contains fetch calls no call-site refactor could have reached. /login is included
    deliberately: the guard must be there too and must NOT loop on itself."""
    html = client.get(path).get_data(as_text=True)
    assert "Global 401 guard" in html, "{} is missing the 401 interceptor".format(path)
    assert "location.pathname !== '/login'" in html, (
        "{}: the guard lost its /login loop-guard".format(path))


def _hook_list(text, label):
    """Pull the hook names out of a `... { a, b, c } ... React` construct."""
    m = re.search(r"\{([^}]*)\}\s*(?:from\s*[\"']react[\"']|=\s*React)", text)
    assert m, "no React hook destructure/import found in " + label
    return [h.strip() for h in m.group(1).split(",") if h.strip()]


def test_loom_hook_preamble_matches_source_in_every_delivery_path():
    """The Loom ships two ways, and BOTH strip master-storyboard.jsx's `import React,
    {...}` line and inject their own `const {...} = React;` preamble in its place:
    pixai_gallery.py's LOOM_PAGE (the default Babel-standalone path) and
    loom/dist/master-storyboard.bundle.js (the ?bundle=1 path, emitted by
    loom/scripts/build.mjs).

    Those preambles were hand-maintained copies of one list, and they rotted exactly as
    build.mjs's own comment warned they could: `useMemo` was added to the .jsx (imported
    L1, used L2344) and to LOOM_PAGE, but not to build.mjs. The committed bundle then
    destructured four hooks while the bundled code called a fifth, so /loom?bundle=1 threw
    `ReferenceError: useMemo is not defined` during mount and rendered a blank page -- and
    because the throw happens in App, a PARENT of the app's own error boundary, the
    boundary could not catch it either. Nothing failed: the Node suite covers pure logic,
    not the bundle's mount, and the default path was fine, so the opt-in path was broken
    alone and silently. Found by a browser crawl, not by any test.

    build.mjs now derives its list from the source. This test pins the remaining two.

    NOTE this catches only preamble drift -- a stale bundle whose hook list happens to
    still match sails through. The full staleness gate is
    test_committed_loom_bundle_matches_a_fresh_build below (and the "Fail if the
    committed bundle is stale" step in .github/workflows/tests.yml, which is the
    authoritative one because CI always has the pinned toolchain)."""
    root = Path(__file__).resolve().parent.parent
    jsx = root / "loom" / "master-storyboard.jsx"
    if not jsx.is_file():
        pytest.skip("loom/master-storyboard.jsx not present in this checkout")
    src_hooks = _hook_list(
        re.search(r"^[ \t]*import\s+React\s*,\s*\{[^}]*\}\s*from\s*[\"']react[\"'].*$",
                  jsx.read_text(encoding="utf-8"), flags=re.M).group(0),
        "master-storyboard.jsx")

    # 1. The default Babel path's preamble, as literally written in pixai_gallery.py.
    py = (root / "pixai_gallery.py").read_text(encoding="utf-8")
    m = re.search(r"const \{[^}]*\} = React;", py)
    assert m, "pixai_gallery.py no longer contains a `const {...} = React;` preamble"
    assert _hook_list(m.group(0), "pixai_gallery.py LOOM_PAGE") == src_hooks, (
        "LOOM_PAGE's hook preamble has drifted from master-storyboard.jsx's import.\n"
        "  jsx imports : {}\n  LOOM_PAGE   : {}\n"
        "Any hook in the source but missing here is a ReferenceError on mount."
        .format(src_hooks, _hook_list(m.group(0), "LOOM_PAGE")))

    # 2. The committed bundle. A stale bundle is exactly how this shipped broken, so a
    #    checkout that HAS one must have a current one -- rebuild with `npm run build`.
    bundle = root / "loom" / "dist" / "master-storyboard.bundle.js"
    if bundle.is_file():
        bm = re.search(r"var \{[^}]*\} = React;", bundle.read_text(encoding="utf-8"))
        assert bm, "the built bundle has no `var {...} = React;` preamble"
        assert _hook_list(bm.group(0), "the built bundle") == src_hooks, (
            "loom/dist/master-storyboard.bundle.js is STALE relative to "
            "master-storyboard.jsx.\n  jsx imports : {}\n  bundle has  : {}\n"
            "Run `npm run build` in loom/ and commit the result."
            .format(src_hooks, _hook_list(bm.group(0), "the bundle")))


def test_committed_loom_bundle_matches_a_fresh_build(tmp_path):
    """loom/dist/master-storyboard.bundle.js is COMMITTED and served verbatim by
    /loom?bundle=1, and nothing forces a rebuild: change master-storyboard.jsx, forget
    `npm run build`, and that route quietly keeps serving the old code. The preamble
    test above only notices when the drift reaches the React hook list -- every other
    edit (a fixed handler, a renamed field, a new panel) leaves the stale bundle
    completely invisible.

    So: rebuild, and require the fresh output to equal the committed file. That works
    because esbuild's output is deterministic -- no banner, no timestamp, no build id,
    and module-path comments use forward slashes on every platform (verified: a Windows
    rebuild reproduced the Linux-built committed artifact byte for byte). Only line
    endings are normalized here, for checkouts where git materialized the file as CRLF.

    This is the LOCAL mirror of the real gate, which is the "Fail if the committed
    bundle is stale" step in .github/workflows/tests.yml -- that one runs after `npm ci`
    so its esbuild is exactly the version pinned in loom/package-lock.json, and it
    compares via `git status`, i.e. against the committed blob rather than the working
    tree. Here we skip unless the toolchain is actually present, so a plain
    `pip install -r ... && pytest` checkout (and the Python CI job, which never runs
    `npm ci`) is unaffected.

    build.mjs only knows one output path, so this necessarily rebuilds in place; the
    original bytes are restored afterwards, and a stale bundle is REPORTED, never
    silently fixed. Set MOONGLADE_SKIP_LOOM_BUILD=1 to opt out entirely."""
    root = Path(__file__).resolve().parent.parent
    loom = root / "loom"
    bundle = loom / "dist" / "master-storyboard.bundle.js"
    script = loom / "scripts" / "build.mjs"

    if os.environ.get("MOONGLADE_SKIP_LOOM_BUILD"):
        pytest.skip("MOONGLADE_SKIP_LOOM_BUILD is set")
    if NODE is None:
        pytest.skip("node not installed")
    if not script.is_file() or not bundle.is_file():
        pytest.skip("loom/ build tooling or dist bundle not present in this checkout")
    if not (loom / "node_modules" / "esbuild").is_dir():
        pytest.skip("loom/node_modules missing -- run `npm ci` in loom/ to enable this check")

    committed = bundle.read_bytes()
    out = tmp_path / "build.out"
    try:
        # Same spawn shape as test_embedded_js_is_valid: real file handles + DEVNULL
        # stdin, because some sandboxes can't duplicate pytest's captured handles.
        try:
            with open(out, "w", encoding="utf-8") as fh, open(os.devnull) as nul:
                rc = subprocess.call([NODE, str(script)], cwd=str(loom),
                                     stdin=nul, stdout=fh, stderr=subprocess.STDOUT)
        except OSError as e:
            pytest.skip("cannot spawn node in this environment: {}".format(e))
        log = out.read_text(encoding="utf-8", errors="replace")
        assert rc == 0, "loom's `npm run build` failed, so the bundle can't be " \
                        "checked for staleness:\n" + log
        fresh = bundle.read_bytes()
    finally:
        if bundle.read_bytes() != committed:
            bundle.write_bytes(committed)   # leave the checkout exactly as we found it

    def _norm(b):
        return b.replace(b"\r\n", b"\n")

    assert _norm(fresh) == _norm(committed), (
        "loom/dist/master-storyboard.bundle.js is STALE -- it does not match a fresh "
        "build of loom/master-storyboard.jsx.\n"
        "  committed: {:,} bytes\n  rebuilt  : {:,} bytes\n"
        "/loom?bundle=1 serves the committed file, so it is serving code that no "
        "longer matches the source.\n"
        "Fix: `cd loom && npm run build`, then commit loom/dist/.\n"
        "(If you DID rebuild, your local esbuild may differ from the version pinned in "
        "loom/package-lock.json -- run `npm ci` in loom/ first.)"
        .format(len(committed), len(fresh)))


def test_no_real_newline_inside_confirm_string(client):
    """Even without Node: the cloud-delete confirm must keep its escaped newline as
    the two chars backslash-n, not an actual line break that splits the literal."""
    html = client.get("/").get_data(as_text=True)
    m = re.search(r"confirm\('Delete '.*?\)\)", html, flags=re.S)
    assert m, "confirmBulkDeleteCloud string not found"
    assert "\n" not in m.group(0).split("typed")[0][:200] or "\\n\\n" in html
