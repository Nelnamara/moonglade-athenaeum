#!/usr/bin/env python3
"""Build the Moonglade asset container (moonglade.dat) from the coded branding source tree.

    python tools/build_container.py                      # branding_root() -> <app root>/moonglade.dat
    python tools/build_container.py --root path/to/tree  # pack a source tree that lives elsewhere
    python tools/build_container.py --out path/to.dat    # explicit output

Packs every file under the source tree -- default: branding_root(), the app's own
coded branding location -- EXCEPT _thumbs/ (a regenerable cache) into the custom
container format (moonglade_container.py -- format rationale and the protection bar
live in that module's docstring, decision record in docs/DECISIONS.md "The asset
container, re-scoped from scratch", 2026-08-10). Files are keyed by their path
relative to the root exactly as found, so the tree's coded folder names seal in
untouched -- and what those names mean is deliberately documented nowhere public,
this file included.

Also packs the achievement definitions as a payload ("achievements", JSON). The
app reads this payload for real now (_sealed_defs() in moonglade_gallery.py --
the roster no longer lives in committed source), so a container built without it
would leave the app running on its bare fallback defaults; the packer fills it
from the private donor so a built container is already complete.

The built .dat is deliberately NOT committed (git-ignored): delivery is a GitHub
Release asset fetched on first run -- decided 2026-08-10, same record. This tool
runs on the machine that has the real art -- and since the source tree is not
required to sit beside the code (it usually doesn't; the app grows its own at the
install, and the owner's master copy lives elsewhere), --root points the build
straight at wherever it actually is. `gh release upload` publishes what it
produces.

ALSO writes/refreshes moonglade_manifest.json (via moonglade_assets.py) --
version, whole-file sha256, size, and the mirror URL list the first-run
downloader reads. THAT file IS committed: it is a few lines of metadata, not
content, and every install needs it to know what container it should have.
--url can be passed (repeatable) once real release URLs exist; omitted, the
prior manifest's urls carry forward untouched (empty on a build with no
release cut yet -- the downloader then fails cleanly, never crashes).

Verification is not optional: after writing, the container is re-opened cold and
every asset is compared byte-for-byte against the source tree; any mismatch
deletes the output and fails loudly. A container that silently packed wrong bytes
is worse than no container.

STAMPS the build (moonglade_container schema 1, 2026-09-07): the container's TOC
carries `built_at` (ISO-8601 UTC) and `builder` (this script's version string, with
the app version), alongside the `schema` and `content_sha256` the format writes for
itself. The verify step above checks the stamp round-trips too. ONE CONSEQUENCE worth
knowing: the timestamp is inside the file, so two builds of identical inputs are no
longer byte-identical by default -- and the URL rule below only carries a prior
release URL forward for byte-identical bytes. Pass --built-at <the previous build's
timestamp> when a deliberate reproducible rebuild is what you want.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import moonglade_assets as ma
import moonglade_backup as core
import moonglade_container as mc
import moonglade_gallery as g

EXCLUDED_DIRS = {"_thumbs"}

# What goes in the container's `builder` stamp (moonglade_container schema 1). Bump the /N
# when THIS packer's output changes in a way a reader of an old pack should be able to tell
# apart; the app version rides along so a pack can be traced to the release that cut it.
BUILDER = "build_container.py/1"


def builder_stamp():
    return "%s moonglade/%s" % (BUILDER, core.__version__)


def utc_now_iso():
    """Second-resolution ISO-8601 UTC, e.g. 2026-09-07T14:03:11Z."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# THE CARRIED LOGIN SET (Session I decision 4b, 2026-09-28). The sign-in page is the one
# screen a fresh install shows BEFORE its pack has arrived, so the app carries a small
# copy of the pack's login mascot and login-card banner in its own bundle
# (gallery/src/art/loginArt.js, beside nelWizard.js), and the page falls back to them
# silently when the pack's files are not there. The pack build writes those copies too,
# so a new login mascot in a pack refreshes the carried one at the next app release.
#
# Sizes are the handoff's: the mascot at 340 px wide (2x its 170 px slot) and the banner
# at 760 px (2x the 380 px card), both WebP, well inside the ~120 KB the handoff allows.
# The mascot is ONE still frame: the pack's is a 91-frame animation, and even a 340 px
# animated copy weighs over 1.6 MB. As data: URIs in a module, because the repo carries no
# loose image files (nelWizard.js's own header: "this string is the only artifact").
# ---------------------------------------------------------------------------
CARRIED_NEL_W = 340
CARRIED_BANNER_W, CARRIED_BANNER_H = 760, 190
CARRIED_QUALITY = 85


def carried_login_js_path():
    """Where the carried copies live: gallery/src/art/loginArt.js in this checkout."""
    return Path(__file__).resolve().parent.parent / "gallery" / "src" / "art" / "loginArt.js"


def carried_login_sources(root):
    """(mascot, banner) source files in a branding tree, or None for a missing one. The
    coded layout the pack is built from comes first; the public names (login_nel.webp at
    the root, banner_login/banner_login.png) are the layout of a mirrored design export."""
    root = Path(root)

    def first(*rels):
        for rel in rels:
            p = root / rel
            if p.is_file():
                return p
        return None
    mascot = first(g._role_rel("system", "login_nel.webp"), g._role_rel("system", "login_nel.png"),
                   "login_nel.webp", "login_nel.png")
    banner = first(g._flat_default_rel("banner_login"), "banner_login/banner_login.png")
    return mascot, banner


def _webp_data_uri(img, quality):
    import base64
    import io
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=quality, method=6)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def carried_login_js(mascot_path, banner_path):
    """The loginArt.js module text for one mascot and one banner source."""
    from PIL import Image, ImageOps
    with Image.open(mascot_path) as im:
        im.seek(0)                                   # frame 0 of an animation: the still
        nel = im.convert("RGBA")
    nel = nel.resize((CARRIED_NEL_W, max(1, round(nel.height * CARRIED_NEL_W / nel.width))),
                     Image.LANCZOS)
    with Image.open(banner_path) as im:
        ban = ImageOps.fit(im.convert("RGB"), (CARRIED_BANNER_W, CARRIED_BANNER_H),
                           Image.LANCZOS, centering=(0.5, 0.5))
    return (
        "// GENERATED by tools/build_container.py (the pack build) -- do not edit by hand.\n"
        "// The carried login set (Session I decision 4b): the pack's login mascot as one\n"
        "// %d px still and its login-card banner at %dx%d, WebP, for the sign-in page to fall\n"
        "// back to while the pack is not installed. See LoginPage.jsx and hooks/useLogin.js.\n"
        "export const LOGIN_NEL = \"%s\";\n"
        "export const LOGIN_BANNER = \"%s\";\n"
    ) % (CARRIED_NEL_W, CARRIED_BANNER_W, CARRIED_BANNER_H,
         _webp_data_uri(nel, CARRIED_QUALITY), _webp_data_uri(ban, CARRIED_QUALITY))


def write_carried_login_art(root, out_js=None):
    """Refresh the carried login set from a branding tree. Returns the path written, or
    None when the tree carries no login mascot or banner (a partial tree -- a test's, or a
    pack without login art -- leaves the committed copies alone rather than blanking them)."""
    mascot, banner = carried_login_sources(root)
    if not mascot or not banner:
        return None
    out = Path(out_js) if out_js else carried_login_js_path()
    text = carried_login_js(mascot, banner)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    return out


def gather(root):
    files = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if EXCLUDED_DIRS & set(rel.parts[:-1]):
            continue
        files[rel.as_posix()] = p.read_bytes()
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None,
                    help="the branding source tree to pack (default: the app's own "
                         "branding_root()). Point it at the owner's real source tree "
                         "when it lives away from the code; files are keyed relative "
                         "to this root either way, so the layout seals in as found.")
    ap.add_argument("--out", default=None,
                    help="output path (default: <app root>/moonglade.dat, even when "
                         "--root points elsewhere -- that is where the app looks)")
    ap.add_argument("--version", default=None,
                    help="manifest version string (default: bump the current "
                         "manifest's integer version by 1, or '1' if none exists)")
    ap.add_argument("--url", action="append", default=[],
                    help="a download URL for the manifest's mirror list "
                         "(repeatable, tried in order). Omit to leave the "
                         "existing manifest's urls untouched; the manifest's "
                         "urls start empty if none has ever been written.")
    ap.add_argument("--donor", default=None,
                    help="path to the SEALED achievement-definitions JSON (roster + "
                         "ancillary tables). Default: the private sibling repo "
                         "../moonglade-internal/achievements_sealed_donor.json -- the "
                         "definitions no longer live in this public tree.")
    ap.add_argument("--built-at", default=None,
                    help="the ISO-8601 UTC build time stamped into the container "
                         "(default: now). Pin it to reproduce an earlier build's exact "
                         "bytes -- the stamp is inside the file, so a rebuild with a "
                         "different time is a different sha256, and the manifest's "
                         "carry-the-URL-forward rule only fires on byte-identical bytes.")
    ap.add_argument("--carry-to", default=None,
                    help="where to write the carried login set (default: "
                         "gallery/src/art/loginArt.js in this checkout)")
    ap.add_argument("--carry-only", action="store_true",
                    help="refresh the carried login set from --root and stop: no container, "
                         "no manifest")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else g.branding_root()
    if not root.is_dir():
        sys.exit("No source tree at %s -- nothing to pack." % root)
    if args.carry_only:
        wrote = write_carried_login_art(root, args.carry_to)
        if not wrote:
            sys.exit("No login mascot and banner in %s -- the carried set was not written." % root)
        print("Wrote the carried login set: %s" % wrote)
        return
    # Output defaults to the APP root even when --root points elsewhere: that is
    # where _container_path() looks for the .dat, and the manifest written below
    # describes that file. --out overrides for anything unusual.
    out_path = Path(args.out) if args.out else g.branding_root().parent / "moonglade.dat"

    assets = gather(root)
    if not assets:
        sys.exit("Source tree at %s is empty -- refusing to build an empty container." % root)
    # Pack the SEALED achievement definitions from the PRIVATE donor -- NOT from source
    # (the roster no longer lives in this public tree). Same class as config.json: a file
    # the public build reads but the public repo does not carry.
    donor_path = Path(args.donor) if args.donor else (
        Path(__file__).resolve().parents[2] / "moonglade-internal"
        / "achievements_sealed_donor.json")
    if not donor_path.is_file():
        sys.exit("Sealed-definitions donor missing at %s -- can't build the achievements "
                 "payload. Pass --donor, or clone the private companion repo." % donor_path)
    defs = json.loads(donor_path.read_text(encoding="utf-8"))
    missing = [k for k in ("roster", "skins", "skin_unlock", "ach_criteria", "ladder_tracks")
               if k not in defs]
    if missing:
        sys.exit("Donor %s is missing required keys: %s" % (donor_path, ", ".join(missing)))
    payloads = {"achievements": json.dumps(defs, separators=(",", ":")).encode("utf-8")}

    built_at = args.built_at or utc_now_iso()
    builder = builder_stamp()
    n_assets, n_payloads = mc.write_container(out_path, assets, payloads,
                                              builder=builder, built_at=built_at)

    box = mc.open_container(out_path)
    problems = []
    if box is None:
        problems.append("container failed to re-open cold")
    else:
        if set(box.paths()) != set(assets):
            problems.append("path set mismatch: %r" % (
                set(box.paths()) ^ set(assets)))
        for rel, raw in assets.items():
            if box.get(rel) != raw:
                problems.append("%s: bytes mismatch on read-back" % rel)
        if box.payload("achievements") != payloads["achievements"]:
            problems.append("achievements payload mismatch on read-back")
        # The build stamp is verified on the same terms as the bytes: a container whose
        # provenance did not survive the round trip is not one to publish. (open_container
        # has already re-derived and matched content_sha256 -- a mismatch there is why box
        # would be None -- so this checks that what we ASKED to be stamped is what is
        # stamped, and that the schema is the one this reader vouches for.)
        stamp = box.stamp()
        if stamp["schema"] != mc.SUPPORTED_SCHEMA:
            problems.append("stamp schema %r, expected %r" % (
                stamp["schema"], mc.SUPPORTED_SCHEMA))
        if stamp["built_at"] != built_at or stamp["builder"] != builder:
            problems.append("build stamp mismatch on read-back: %r" % (stamp,))
        if not stamp["content_sha256"]:
            problems.append("container carries no content_sha256")
    if problems:
        out_path.unlink(missing_ok=True)
        sys.exit("Verification FAILED, container deleted:\n  " + "\n  ".join(problems))

    # The manifest describes the container by its whole-file identity (what a
    # downloader fetches and verifies), independent of the TOC-level format
    # write_container() already checked above.
    import hashlib
    whole_sha256 = hashlib.sha256(out_path.read_bytes()).hexdigest()
    size = out_path.stat().st_size

    prior = ma.read_manifest()
    if args.version:
        version = args.version
    elif prior and str(prior.get("version", "")).isdigit():
        version = str(int(prior["version"]) + 1)
    else:
        version = "1"
    # URL selection -- fail CLOSED on the one combination that ships a broken release:
    # bytes CHANGED (new sha256) but no --url given, so the prior manifest's URL(s) still
    # point at the OLD file. A fresh install would then download bytes that fail the new
    # checksum and end up permanently undressed with no fallback. Carry the prior URL
    # forward ONLY when the bytes are byte-identical (same sha) -- then the existing URL
    # genuinely still serves them. (Adversarial release-integrity finding, 2026-08-22.)
    if args.url:
        urls = list(args.url)
    elif prior and prior.get("urls"):
        if whole_sha256 == prior.get("sha256"):
            urls = prior["urls"]
        else:
            sys.exit(
                "Container bytes changed (sha256 %s, was %s) but no --url was given.\n"
                "The manifest's existing URL(s) point at the OLD file, so a fresh install "
                "would download bytes that fail the new checksum and end up undressed.\n"
                "Pass --url <new release asset URL> for this build, or rebuild identical "
                "bytes -- which since the build stamp (2026-09-07) also means passing "
                "--built-at with the previous build's timestamp, because the stamp is "
                "inside the file. The manifest was NOT written." % (
                    whole_sha256[:12], str(prior.get("sha256"))[:12]))
    else:
        urls = []
    ma.write_manifest(version, whole_sha256, size, urls)

    # The carried login set follows the pack it was cut from (decision 4b). Written only
    # after the container verified and the manifest landed, so a failed build changes
    # nothing in the app's own source either.
    carried = write_carried_login_art(root, args.carry_to)
    if carried:
        print("Carried login set refreshed: %s (rebuild gallery/dist to ship it)" % carried)

    print("Wrote %s (%d assets, %d payload(s), %.1f MB) -- verified byte-for-byte."
          % (out_path, n_assets, n_payloads, out_path.stat().st_size / 1e6))
    print("Manifest: version %s, %s..., %d mirror URL(s)"
          % (version, whole_sha256[:12], len(urls)))
    print("Stamp: schema %d, built %s by %s"
          % (mc.SUPPORTED_SCHEMA, built_at, builder))


if __name__ == "__main__":
    main()
