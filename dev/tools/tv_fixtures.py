"""Capture the real JSON of the five routes the Apple TV client decodes.

    python dev/tools/tv_fixtures.py <output-dir>

Writes gallery-images.json, collections-detail.json, achievements.json, similar.json and
health.json into <output-dir> (created if missing; the only argument, and required).

READ-ONLY toward the install. The app is built the way dev/tests builds it (create_app, a
real sign-in through the login route, test client), but against a SCRATCH library in a
temp folder, never the real one:

  * catalog.db is COPIED from the library local/settings.json names;
  * images/, imported/ and videos/ are junctioned in, read-only in practice, so /api/similar
    can find the picture file it compares against;
  * the pack and settings.json are COPIED into a scratch local/, and config.json (with a
    throwaway account) lives there too, so nothing is written into the library, the
    checkout's config.json or local/;
  * live PixAI traffic is refused, as in the test suite.

Fixtures carry non-NSFW rows only: once collections, achievements and health are captured
from the full copy, every NSFW row is deleted from the SCRATCH catalog before the
gallery-images and similar answers are taken.
"""
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["MOONGLADE_DISABLE_WATCH"] = "1"
os.environ.pop("PIXAI_API_KEY", None)
os.environ.pop("PIXAI_TOKEN", None)

LINKED = ("images", "imported", "videos")


def _junction(link, target):
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       capture_output=True, text=True)
    return r.returncode == 0


def main(argv):
    if len(argv) != 2 or argv[1].startswith("-"):
        print("usage: python dev/tools/tv_fixtures.py <output-dir>", file=sys.stderr)
        return 2
    outdir = Path(argv[1]).resolve()

    from moonglade import backup as core
    from moonglade import paths
    from moonglade import settings as mg_settings
    from moonglade import gallery

    # Resolve the real library and the real pack BEFORE anything is re-pointed.
    real_lib = Path(mg_settings.library_path()).resolve()
    real_local = paths.local_dir()
    if not (real_lib / "catalog.db").is_file():
        print("no catalog.db in " + str(real_lib), file=sys.stderr)
        return 1

    outdir.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="mg_tv_fixtures_"))
    lib, local = scratch / "library", scratch / "local"
    lib.mkdir()
    local.mkdir()
    links = []
    try:
        shutil.copy2(real_lib / "catalog.db", lib / "catalog.db")
        for name in LINKED:
            if (real_lib / name).is_dir():
                if _junction(lib / name, real_lib / name):
                    links.append(lib / name)
                else:
                    print("note: could not link " + name + "; /api/similar may not find files",
                          file=sys.stderr)
        for name in ("moonglade.mgpack", "moonglade.mgpack.version", "settings.json"):
            if (real_local / name).is_file():
                shutil.copy2(real_local / name, local / name)

        # Re-point every machine-local path at the scratch folders (what conftest's autouse
        # fixtures do), and refuse live PixAI traffic.
        core._cfg = {}
        core._config_path = lambda: scratch / "config.json"
        paths.config_path = lambda: scratch / "config.json"
        paths.local_dir = lambda: local
        paths.local_path = lambda name: local / name
        paths.library_anchor = lambda: scratch
        gallery.branding_root = lambda: scratch / "branding"

        def _blocked(*a, **k):
            raise core.PixAIError("live PixAI blocked: tv_fixtures is read-only")
        for fn in ("_rest_get", "_rest_post", "_rest_put", "_rest_patch", "_config_get",
                   "_make_session"):
            if hasattr(core, fn):
                setattr(core, fn, _blocked)

        # Sign in for real through the login route, as conftest.login_client does, with a
        # throwaway account that exists only in the scratch config.json.
        core.WEB_PASSWORD_HASH_METHOD = "scrypt:256:1:1"
        user, pw = "tv-fixtures", secrets.token_urlsafe(18)
        core.add_or_update_web_user(user, pw)
        app = gallery.create_app(lib)
        cli = app.test_client()
        html = cli.get("/login").get_data(as_text=True)
        import re
        m = re.search(r'"csrf":\s*"([^"]+)"', html)
        if not m:
            print("login page carried no csrf token", file=sys.stderr)
            return 1
        d = cli.post("/api/login", json={"username": user, "password": pw,
                                         "csrf": m.group(1)}).get_json()
        if not (d and d.get("ok")):
            print("sign-in failed", file=sys.stderr)
            return 1

        def grab(url, name):
            r = cli.get(url)
            body = r.get_json()
            (outdir / name).write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n",
                                       encoding="utf-8")
            print("{} {} -> {} ({} bytes)".format(r.status_code, url, name,
                                                  (outdir / name).stat().st_size))
            return body

        # Full copy first: these three describe the whole install.
        grab("/api/collections/detail", "collections-detail.json")
        grab("/api/achievements", "achievements.json")
        grab("/api/health", "health.json")

        # Then drop NSFW rows from the SCRATCH catalog only; rows and similar neighbours
        # in the next two answers are non-NSFW by construction.
        con = sqlite3.connect(str(lib / "catalog.db"))
        if _has_table(con, "catalog"):
            con.execute("DELETE FROM catalog WHERE is_nsfw = '1'")
        con.commit()
        con.close()

        gi = grab("/api/gallery-images?limit=12&type=all", "gallery-images.json")
        first = next((r["media_id"] for r in (gi or {}).get("images", [])
                      if not r.get("is_video")), None)    # similar compares pictures, not clips
        if not first:
            print("gallery-images returned no image rows; cannot capture similar", file=sys.stderr)
            return 1
        grab("/api/similar/" + first, "similar.json")
        return 0
    finally:
        for link in links:                       # remove the junctions, never what they point at
            try:
                os.rmdir(link)
            except OSError:
                pass
        shutil.rmtree(scratch, ignore_errors=True)


def _has_table(con, name):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                       (name,)).fetchone() is not None


if __name__ == "__main__":
    sys.exit(main(sys.argv))
