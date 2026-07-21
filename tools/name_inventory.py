#!/usr/bin/env python3
"""Naming inventory — two different naming problems, one tool.

    python tools/name_inventory.py modules   # the pixai_* -> moonglade_* rename surface
    python tools/name_inventory.py labels    # user-facing labels vs PixAI's own wording
    python tools/name_inventory.py           # both

WHY TWO MODES. "Naming" has meant two unrelated things in this project and
conflating them wasted a round trip:

  modules  Internal Python module names (pixai_gallery, pixai_gallery_backup, ...).
           A mechanical rename, deliberately deferred to its own branch. This mode
           sizes it so the decision is made against a number, not a guess.

  labels   USER-FACING control labels versus PixAI's own vocabulary. A different
           concern entirely: someone who uses PixAI's site and then this app should
           recognise the same setting by the same name. Divergence here is a real
           usability bug, not tidiness -- the gallery's video drawer labelled
           PixAI's "Basic / Professional" control as "Priority", while a genuinely
           different priority control (Turbo) sat directly above it.

The labels mode cannot be fully automatic: PixAI's UI wording is not machine-
readable from here. It checks the vocabulary we have RE'd into the code (the API
enum values we submit) against the labels we render, and flags controls whose
submitted values come from PixAI's vocabulary while their visible label does not
mention it. Judgement still required; this narrows where to look.
"""
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".webp", ".ico", ".db", ".ogg", ".mp4", ".zip"}


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout
    return [ROOT / f for f in out.split()]


def read(p):
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def modules():
    """Size the pixai_* -> moonglade_* rename surface."""
    pat = re.compile(r"\bpixai_[a-z_]+\b")
    names, byfile, buckets, filesof = Counter(), Counter(), Counter(), {}
    for p in tracked_files():
        if p.suffix in SKIP_SUFFIX:
            continue
        hits = pat.findall(read(p))
        if not hits:
            continue
        rel = p.relative_to(ROOT).as_posix()
        byfile[rel] = len(hits)
        for h in hits:
            names[h] += 1
        kind = ("code" if p.suffix == ".py" else
                "js" if p.suffix in (".js", ".jsx") else
                "docs" if p.suffix == ".md" else
                "cfg" if p.suffix in (".json", ".yml", ".yaml", ".txt", ".cfg", ".ini")
                else "other")
        buckets[kind] += len(hits)
        filesof.setdefault(kind, set()).add(rel)

    print("=== identifiers ===")
    for n, c in names.most_common():
        note = ""
        if n == "pixai_backup":
            note = "   <-- OUTPUT DIRECTORY, in every user's config: renaming breaks installs"
        print("  {:28} {:5}{}".format(n, c, note))
    print("\n=== by file type ===")
    for k, c in buckets.most_common():
        print("  {:6} {:5} refs across {:3} files".format(k, c, len(filesof[k])))
    print("\n  TOTAL {} references in {} files".format(sum(buckets.values()), len(byfile)))
    print("\n=== heaviest files ===")
    for f, c in byfile.most_common(10):
        print("  {:5}  {}".format(c, f))


# PixAI's own vocabulary, as RE'd into our submit paths. Values here are the ones we
# actually send, so they are authoritative about what PixAI calls the setting.
PIXAI_VOCAB = {
    "basic/professional": ["basic", "professional"],
    "normal/enhanced": ["normal", "enhanced"],
}


def labels():
    """Flag controls whose submitted values are PixAI vocabulary but whose visible
    label doesn't use PixAI's word for it."""
    surfaces = [p for p in (ROOT / "pixai_gallery.py",
                            ROOT / "static" / "mg-generate-drawer.js",
                            ROOT / "loom" / "master-storyboard.jsx") if p.is_file()]
    # <div class="...lbl">LABEL</div> ... <select ...><option value="VOCAB">
    # The gap tolerates JS string-concatenation noise ("</div>' +\n  '<select"),
    # because the shared drawer builds its markup that way -- a stricter gap
    # silently skipped it, which would have reported false coverage.
    sel = re.compile(r'(?:gen-lbl|mgd-lbl)"?>([^<]{1,40})</div>'
                     r"[^<]{0,60}"
                     r'<select[^>]*>(.{0,400}?)</select>', re.S)
    print("=== controls submitting PixAI vocabulary ===")
    flagged = 0
    for p in surfaces:
        txt = read(p)
        for m in sel.finditer(txt):
            label, body = m.group(1).strip(), m.group(2)
            vals = set(re.findall(r'value="([a-z0-9._-]+)"', body))
            for concept, words in PIXAI_VOCAB.items():
                if not set(words) <= vals:
                    continue
                ok = any(w in label.lower() for w in words)
                line = txt[:m.start()].count("\n") + 1
                mark = "ok  " if ok else "FLAG"
                if not ok:
                    flagged += 1
                print("  [{}] {}:{}  label={!r}  submits {}".format(
                    mark, p.relative_to(ROOT).as_posix(), line, label, sorted(vals & set(words))))
    print("\n  {} control(s) flagged: submits PixAI's values, doesn't use PixAI's word."
          .format(flagged))
    if flagged:
        print("  Judgement required -- a deliberate rename may be right, but it should be"
              "\n  deliberate. See docs/STATE.md.")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("modules", "both"):
        modules()
    if which == "both":
        print("\n" + "=" * 70 + "\n")
    if which in ("labels", "both"):
        labels()
