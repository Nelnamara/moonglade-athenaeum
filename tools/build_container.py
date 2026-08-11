#!/usr/bin/env python3
"""Build the Moonglade asset container (moonglade.dat) from the real branding/ tree.

    python tools/build_container.py                    # -> <app root>/moonglade.dat
    python tools/build_container.py --out path/to.dat  # explicit output

Packs every file under branding_root() EXCEPT _thumbs/ (a regenerable cache) into
the custom container format (moonglade_container.py -- format rationale and the
protection bar live in that module's docstring, decision record in
docs/DECISIONS.md "The asset container, re-scoped from scratch", 2026-08-10).

Also packs the achievement definitions as a reserved payload ("achievements",
JSON). The app does NOT read this payload yet -- wiring it up requires moving the
definitions out of committed source, and how far that removal goes is an open
owner decision. The slot exists so the container format never needs a version
bump for it; the packer fills it so a built container is already complete.

The built .dat is deliberately NOT committed (git-ignored): delivery is a GitHub
Release asset fetched on first run -- decided 2026-08-10, same record. This tool
runs on the machine that has the real art; `gh release upload` publishes what it
produces.

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
    ap.add_argument("--out", default=None,
                    help="output path (default: <app root>/moonglade.dat)")
    args = ap.parse_args()

    root = g.branding_root()
    if not root.is_dir():
        sys.exit("No branding/ folder at %s -- nothing to pack." % root)
    out_path = Path(args.out) if args.out else root.parent / "moonglade.dat"

    assets = gather(root)
    if not assets:
        sys.exit("branding/ at %s is empty -- refusing to build an empty container." % root)
    payloads = {"achievements": json.dumps(g.ACHIEVEMENTS).encode("utf-8")}

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

    print("Wrote %s (%d assets, %d payload(s), %.1f MB) -- verified byte-for-byte."
          % (out_path, n_assets, n_payloads, out_path.stat().st_size / 1e6))


if __name__ == "__main__":
    main()
