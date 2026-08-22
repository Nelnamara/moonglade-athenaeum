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
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import moonglade_assets as ma
import moonglade_container as mc
import moonglade_gallery as g

EXCLUDED_DIRS = {"_thumbs"}


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
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else g.branding_root()
    if not root.is_dir():
        sys.exit("No source tree at %s -- nothing to pack." % root)
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

    n_assets, n_payloads = mc.write_container(out_path, assets, payloads)

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
                "bytes. The manifest was NOT written." % (
                    whole_sha256[:12], str(prior.get("sha256"))[:12]))
    else:
        urls = []
    ma.write_manifest(version, whole_sha256, size, urls)

    print("Wrote %s (%d assets, %d payload(s), %.1f MB) -- verified byte-for-byte."
          % (out_path, n_assets, n_payloads, out_path.stat().st_size / 1e6))
    print("Manifest: version %s, %s..., %d mirror URL(s)"
          % (version, whole_sha256[:12], len(urls)))


if __name__ == "__main__":
    main()
