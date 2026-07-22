#!/usr/bin/env python3
"""Roster board — render docs/achievements_roster_57.json as one readable HTML page.

    python tools/build_roster_board.py                        # -> docs/achievements_roster_57_board.html
    python tools/build_roster_board.py --out board.html       # somewhere else
    python tools/build_roster_board.py --no-chibis            # skip art-candidate thumbs (smaller file)

WHY THIS EXISTS. The 57-achievement roster is *designed* but not *shipped* — only 11 of
its badges have art placed so far. Reviewing the design means answering questions the raw
JSON is hostile to: does every ladder read as one escalating journey, is the tier spread
sane, does a rung's roast match its rung, which entries still have no badge art. The file
is ~3 MB and most of that is base64 thumbnails, so it cannot be skimmed in an editor and
`json.dumps` output drowns the 20 fields that matter in image data.

This turns it into a board: grouped by bucket, ladders rendered as their tracks with the
rungs in order, and the art the JSON already carries inlined next to the entry it belongs
to. Self-contained — one file, no CDN, no server, opens off disk.

READ-ONLY BY CONTRACT. The roster JSON is the design source of truth; this script opens it
for reading and never writes to it. `--out` is refused if it resolves to the roster path.

WHERE THE NUMBERS COME FROM. Points are not a field in the JSON — they are derived, and
this mirrors `pixai_gallery.achievement_points()` exactly so the board cannot quote a score
the app would disagree with: tier base (common 5 / rare 10 / epic 25 / legendary 50) plus
5 per rung above the first, and feats always score 0 by design so a points total can never
betray a hidden feat. The app *derives* rung by grouping ladder entries by metric and
sorting on threshold; the JSON carries `rung` outright. Those two agree on all 29 ladder
entries as of this writing (checked), so the JSON's own field is used here.

BADGE ART RESOLUTION. Each achievement carries a `badge` code (`PT93`, `FOE12`,
`custom:reel-director__badge.webp`, ...) that mostly points at an external art bank this
JSON does not contain. Art gets inlined when — and only when — the JSON itself carries a
matching thumb, in this order:

  1. a `P:<achievement id>` entry in `badges` (kind `placed`) — art already chosen and
     placed for that specific achievement; this is the 11 that shipped;
  2. the badge code matching a `badges` entry id, then its label — the loose art picks
     (`G*` grok / `Z*` zzip candidates) that were banked by code.

Everything else renders as a coded placeholder, which is the point: the gaps are the
review. The per-achievement `art_candidate` number indexes the `chibis` map and is shown
as a separate, clearly-labelled thumb — a candidate, not the badge.
"""
import argparse
import html
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROSTER = ROOT / "docs" / "achievements_roster_57.json"
DEFAULT_OUT = ROOT / "docs" / "achievements_roster_57_board.html"

# Mirrors pixai_gallery._TIER_POINTS -- keep in step with it, not with a doc.
TIER_POINTS = {"common": 5, "rare": 10, "epic": 25, "legendary": 50, "feat": 0}

# docs/ART.md 1.1 palette + 1.2 tier chrome. Feat uses gunmetal/ruby, never pink.
TIER_COLOR = {
    "common": "#8a8298",
    "rare": "#47cbc3",
    "epic": "#643aac",
    "legendary": "#d4af37",
    "feat": "#8a93a2",
}
TIER_ORDER = ["common", "rare", "epic", "legendary", "feat"]


def esc(v):
    return html.escape("" if v is None else str(v), quote=True)


def points(a):
    """Tier base + 5 per rung above the first; feats score 0. See module docstring."""
    if a.get("tier") == "feat":
        return 0
    return TIER_POINTS.get(a.get("tier"), 0) + 5 * (max(int(a.get("rung") or 1), 1) - 1)


def badge_art(a, by_id, by_label):
    """(data-uri or None, provenance label). Order documented in the module docstring."""
    placed = by_id.get("P:" + a["id"])
    if placed and placed.get("thumb"):
        return placed["thumb"], "placed art"
    code = a.get("badge") or ""
    for src in (by_id.get(code), by_label.get(code)):
        if src and src.get("thumb"):
            return src["thumb"], "art pick " + str(src.get("id"))
    return None, "no art yet"


def flag_chips(a):
    out = []
    if a.get("hidden"):
        out.append('<span class="chip warn">hidden</span>')
    if a.get("banner_reward"):
        out.append('<span class="chip gold">banner reward</span>')
    if a.get("skin"):
        out.append('<span class="chip gold">skin: %s</span>' % esc(a["skin"]))
    return "".join(out)


def card(a, by_id, by_label, chibis, show_chibis):
    thumb, prov = badge_art(a, by_id, by_label)
    tier = a.get("tier", "common")
    art = ('<img class="badge-img" alt="badge art for %s" src="%s">' % (esc(a["name"]), esc(thumb))
           if thumb else '<div class="badge-none">%s</div>' % esc(a.get("badge") or "?"))

    chibi = ""
    if show_chibis:
        cand = chibis.get(str(a.get("art_candidate")))
        if cand:
            chibi = ('<figure class="cand"><img alt="art candidate %s" src="%s">'
                     '<figcaption>cand #%s<br><span>%s</span></figcaption></figure>'
                     % (esc(a.get("art_candidate")), esc(cand),
                        esc(a.get("art_candidate")), esc(a.get("art_label") or "")))

    rung = ""
    if a.get("rungs_total"):
        rung = '<span class="chip rung">rung %s / %s</span>' % (esc(a["rung"]), esc(a["rungs_total"]))

    roast = ""
    if a.get("roast") or a.get("roast_nsfw"):
        roast = ('<details class="roast"><summary>roast</summary>'
                 '<p>%s</p>%s</details>'
                 % (esc(a.get("roast") or ""),
                    ('<p class="nsfw"><span>nsfw</span> %s</p>' % esc(a["roast_nsfw"]))
                    if a.get("roast_nsfw") else ""))

    # data-* carries the filter haystack so the toolbar never has to re-read the DOM text.
    return """
<article class="card t-{tier}" data-ach="{aid}" data-tier="{tier}" data-bucket="{bucket}"
         data-hidden="{hid}" data-q="{q}">
  <div class="art">
    <div class="badge-wrap" title="{prov}">{art}</div>
    <div class="prov">{prov}</div>
    {chibi}
  </div>
  <div class="body">
    <h3>{name} <span class="aid">{aid}</span></h3>
    <div class="chips"><span class="chip tier">{tier}</span>
      <span class="chip pts">{pts} pts</span>{rung}{flags}</div>
    <p class="desc">{desc}</p>
    <dl class="meta">
      <dt>badge</dt><dd class="code">{badge}</dd>
      <dt>trigger</dt><dd class="code">{trigger}</dd>
      <dt>metric</dt><dd class="code">{metric} &ge; {threshold}</dd>
      <dt>telemetry</dt><dd class="code">{telemetry}</dd>
    </dl>
    {roast}
  </div>
</article>""".format(
        tier=esc(tier), aid=esc(a["id"]), bucket=esc(a.get("bucket")),
        hid="1" if a.get("hidden") else "0",
        q=esc(" ".join(str(a.get(k) or "") for k in
                       ("id", "name", "desc", "badge", "metric", "trigger", "art_label")).lower()),
        prov=esc(prov), art=art, chibi=chibi, name=esc(a.get("name")),
        pts=points(a), rung=rung, flags=flag_chips(a), desc=esc(a.get("desc")),
        badge=esc(a.get("badge")), trigger=esc(a.get("trigger")),
        metric=esc(a.get("metric")), threshold=esc(a.get("threshold")),
        telemetry=esc(a.get("telemetry")), roast=roast)


CSS = """
:root{--base:#0c0a1c;--mantle:#0a0818;--surface0:#211f3a;--surface1:#3a3460;
 --overlay0:#6a6088;--text:#d6d2e2;--subtext:#9a93ab;--lavender:#b692e6;--mauve:#c4a6f0;
 --emerald:#4fc99a;--gold:#d4af37;--purple-deep:#33236d;--purple-bright:#643aac;
 --blue:#47cbc3;--gunmetal:#8a93a2;--ruby:#e0355e}
*{box-sizing:border-box}
body{margin:0;background:var(--base);color:var(--text);
 font:15px/1.5 "Segoe UI",system-ui,-apple-system,sans-serif}
a{color:var(--lavender)}
header.top{position:sticky;top:0;z-index:9;background:var(--mantle);
 border-bottom:1px solid var(--surface1);padding:14px 22px}
header.top h1{margin:0;font-size:21px;letter-spacing:.4px;color:var(--mauve);font-weight:600}
header.top h1 small{color:var(--subtext);font-size:12px;font-weight:400;letter-spacing:0}
.tally{margin:8px 0 0;color:var(--subtext);font-size:12.5px}
.tally b{color:var(--text);font-weight:600}
.tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px}
.tools input[type=search],.tools select{background:var(--surface0);color:var(--text);
 border:1px solid var(--surface1);border-radius:6px;padding:5px 9px;font:inherit;font-size:13px}
.tools label{color:var(--subtext);font-size:12.5px;display:flex;gap:5px;align-items:center}
.jump{margin-left:auto;display:flex;gap:6px;flex-wrap:wrap}
.jump a{font-size:12px;text-decoration:none;border:1px solid var(--surface1);
 border-radius:999px;padding:3px 10px;color:var(--subtext)}
.jump a:hover{color:var(--mauve);border-color:var(--purple-bright)}
main{padding:20px 22px 60px;max-width:1500px;margin:0 auto}
section.bucket{margin:0 0 34px}
section.bucket>h2{margin:0 0 4px;font-size:18px;color:var(--gold);
 border-bottom:1px solid var(--surface1);padding-bottom:6px}
section.bucket>h2 span{color:var(--subtext);font-size:12px;font-weight:400;float:right;
 padding-top:6px}
.note{color:var(--subtext);font-size:13px;margin:8px 0 16px;max-width:110ch}
.track{margin:0 0 22px;border-left:2px solid var(--purple-bright);padding-left:14px}
.track>h3{margin:0 0 2px;font-size:15px;color:var(--mauve)}
.track>h3 span{color:var(--subtext);font-size:12px;font-weight:400;margin-left:8px}
.track .note{margin:4px 0 12px;font-size:12.5px}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(430px,1fr))}
.card{display:flex;gap:14px;background:var(--surface0);border:1px solid var(--surface1);
 border-left:5px solid var(--overlay0);border-radius:9px;padding:12px 14px}
.card.t-common{border-left-color:#8a8298}
.card.t-rare{border-left-color:var(--blue)}
.card.t-epic{border-left-color:var(--purple-bright)}
.card.t-legendary{border-left-color:var(--gold)}
.card.t-feat{border-left-color:var(--gunmetal);box-shadow:inset 0 0 0 1px rgba(224,53,94,.22)}
.art{flex:0 0 104px;text-align:center}
.badge-wrap{width:104px;height:104px;display:flex;align-items:center;justify-content:center;
 background:var(--purple-deep);border:1px solid var(--surface1);border-radius:8px;overflow:hidden}
.badge-img{max-width:100%;max-height:100%;display:block}
.badge-none{font:600 12px/1.3 ui-monospace,Consolas,monospace;color:var(--subtext);
 padding:6px;word-break:break-all}
.prov{font-size:10.5px;color:var(--subtext);margin-top:4px;letter-spacing:.3px}
.cand{margin:8px 0 0}
.cand img{width:72px;height:72px;object-fit:cover;border-radius:6px;
 border:1px dashed var(--overlay0);opacity:.85}
.cand figcaption{font-size:10px;color:var(--subtext);margin-top:3px;line-height:1.3}
.cand figcaption span{color:var(--overlay0)}
.body{flex:1 1 auto;min-width:0}
.body h3{margin:0 0 6px;font-size:16px;color:var(--text);font-weight:600}
.aid{font:400 11px ui-monospace,Consolas,monospace;color:var(--overlay0);margin-left:6px}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:7px}
.chip{font-size:10.5px;text-transform:uppercase;letter-spacing:.6px;border-radius:999px;
 padding:2px 8px;border:1px solid var(--surface1);color:var(--subtext)}
.t-common .chip.tier{color:#8a8298;border-color:#8a8298}
.t-rare .chip.tier{color:var(--blue);border-color:var(--blue)}
.t-epic .chip.tier{color:#c69cff;border-color:var(--purple-bright)}
.t-legendary .chip.tier{color:#e8cb7c;border-color:var(--gold)}
.t-feat .chip.tier{color:var(--ruby);border-color:var(--gunmetal)}
.chip.pts{color:var(--emerald);border-color:rgba(79,201,154,.45)}
.chip.warn{color:var(--ruby);border-color:rgba(224,53,94,.5)}
.chip.gold{color:var(--gold);border-color:rgba(212,175,55,.5)}
.desc{margin:0 0 8px;font-size:13.5px}
dl.meta{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;margin:0;font-size:11.5px}
dl.meta dt{color:var(--overlay0);text-transform:uppercase;letter-spacing:.5px;font-size:10px;
 padding-top:1px}
dl.meta dd{margin:0;color:var(--subtext)}
.code{font-family:ui-monospace,Consolas,monospace}
details.roast{margin-top:8px}
details.roast summary{cursor:pointer;color:var(--overlay0);font-size:11px;
 text-transform:uppercase;letter-spacing:.6px}
details.roast p{margin:6px 0 0;font-size:12.5px;color:var(--subtext);font-style:italic}
details.roast .nsfw span{color:var(--ruby);font-style:normal;font-size:10px;
 text-transform:uppercase;letter-spacing:.5px;margin-right:4px}
.hide{display:none}
footer{color:var(--overlay0);font-size:11.5px;border-top:1px solid var(--surface1);
 padding:14px 22px;max-width:1500px;margin:0 auto}
"""

JS = """
(function(){
 var q=document.getElementById('q'),t=document.getElementById('tier'),
     h=document.getElementById('onlyhidden'),n=document.getElementById('shown'),
     cards=[].slice.call(document.querySelectorAll('.card'));
 function apply(){
  var s=q.value.trim().toLowerCase(),tv=t.value,ho=h.checked,c=0;
  cards.forEach(function(el){
   var ok=(!s||el.dataset.q.indexOf(s)>=0)&&(!tv||el.dataset.tier===tv)&&
          (!ho||el.dataset.hidden==='1');
   el.classList.toggle('hide',!ok); if(ok)c++;
  });
  // Collapse groups that filtered down to nothing so the page has no empty headings.
  [].forEach.call(document.querySelectorAll('.track,.bucket'),function(g){
   g.classList.toggle('hide',!g.querySelector('.card:not(.hide)'));
  });
  n.textContent=c;
 }
 q.addEventListener('input',apply);t.addEventListener('change',apply);
 h.addEventListener('change',apply);apply();
})();
"""


def build(data, source, show_chibis=True):
    roster = data.get("roster") or {}
    achievements = roster.get("achievements") or []
    buckets = roster.get("buckets") or []
    tracks = roster.get("tracks") or []
    by_id = {b.get("id"): b for b in data.get("badges") or []}
    by_label = {}
    for b in data.get("badges") or []:
        by_label.setdefault(b.get("label"), b)
    chibis = data.get("chibis") or {}

    tiers = Counter(a.get("tier") for a in achievements)
    per_bucket = Counter(a.get("bucket") for a in achievements)
    arted = sum(1 for a in achievements if badge_art(a, by_id, by_label)[0])
    total_pts = sum(points(a) for a in achievements)

    parts = []
    for b in buckets:
        bid = b.get("id")
        mine = [a for a in achievements if a.get("bucket") == bid]
        body = []
        # Ladders are only legible as their tracks -- rungs in order, one journey per block.
        # Any ladder entry whose track is missing from roster.tracks still gets rendered,
        # in an explicit leftovers group, rather than silently vanishing from the board.
        if bid == "ladder":
            placed_ids = set()
            for tr in [t for t in tracks if t.get("bucket") == bid]:
                rungs = sorted([a for a in mine if a.get("track") == tr.get("id")],
                               key=lambda a: (a.get("rung") or 0, a.get("threshold") or 0))
                if not rungs:
                    continue
                placed_ids.update(a["id"] for a in rungs)
                body.append(
                    '<div class="track"><h3>%s<span>%s &middot; %s rungs &middot; metric %s</span></h3>'
                    '<p class="note">%s</p><div class="grid">%s</div></div>'
                    % (esc(tr.get("name")), esc(tr.get("id")), len(rungs), esc(tr.get("metric")),
                       esc(tr.get("note")),
                       "".join(card(a, by_id, by_label, chibis, show_chibis) for a in rungs)))
            orphans = [a for a in mine if a["id"] not in placed_ids]
            if orphans:
                body.append('<div class="track"><h3>Unassigned<span>no matching track in '
                            'roster.tracks</span></h3><div class="grid">%s</div></div>'
                            % "".join(card(a, by_id, by_label, chibis, show_chibis)
                                      for a in orphans))
        else:
            body.append('<div class="grid">%s</div>'
                        % "".join(card(a, by_id, by_label, chibis, show_chibis) for a in mine))
        parts.append('<section class="bucket" id="b-%s"><h2>%s<span>%s of %s</span></h2>'
                     '<p class="note">%s</p>%s</section>'
                     % (esc(bid), esc(b.get("name")), len(mine), len(achievements),
                        esc(b.get("note")), "".join(body)))

    # Anything whose bucket isn't declared in roster.buckets would otherwise never render.
    stray = [a for a in achievements if a.get("bucket") not in {b.get("id") for b in buckets}]
    if stray:
        parts.append('<section class="bucket" id="b-stray"><h2>Unbucketed<span>%s</span></h2>'
                     '<p class="note">bucket id not declared in roster.buckets.</p>'
                     '<div class="grid">%s</div></section>'
                     % (len(stray), "".join(card(a, by_id, by_label, chibis, show_chibis)
                                            for a in stray)))

    jump = "".join('<a href="#b-%s">%s</a>' % (esc(b.get("id")), esc(b.get("name")))
                   for b in buckets)
    tier_opts = "".join('<option value="%s">%s (%s)</option>' % (t, t, tiers.get(t, 0))
                        for t in TIER_ORDER if tiers.get(t))
    tier_tally = " &middot; ".join(
        '<b style="color:%s">%s</b> %s' % (TIER_COLOR.get(t, "#fff"), tiers.get(t, 0), t)
        for t in TIER_ORDER if tiers.get(t))
    bucket_tally = " &middot; ".join("<b>%s</b> %s" % (per_bucket.get(b.get("id"), 0),
                                                      esc(b.get("name")))
                                     for b in buckets)

    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Moonglade Athenaeum — achievement roster board ({total})</title>
<style>{css}</style></head><body>
<header class="top">
  <h1>Achievement roster board <small>{total} designed &middot; {source}</small></h1>
  <p class="tally"><b>{total}</b> achievements &middot; {bucket_tally} &middot; <b>{ntracks}</b>
   ladders &middot; {tier_tally} &middot; <b>{total_pts}</b> points possible &middot;
   badge art placed for <b>{arted}</b>, <b>{unarted}</b> still coded-only</p>
  <div class="tools">
    <input type="search" id="q" placeholder="filter name / desc / badge / metric&hellip;" size="34">
    <select id="tier"><option value="">all tiers</option>{tier_opts}</select>
    <label><input type="checkbox" id="onlyhidden"> hidden only</label>
    <label><span id="shown">{total}</span> shown</label>
    <nav class="jump">{jump}</nav>
  </div>
</header>
<main>{parts}</main>
<footer>Generated {when} by tools/build_roster_board.py from {source} (read-only —
 the roster JSON is the design source of truth and is never written by this tool).
 Points mirror pixai_gallery.achievement_points(): tier base + 5 per rung above the first,
 feats score 0. "cand #N" thumbs are art <em>candidates</em> from the roster's chibis map,
 not placed badge art.</footer>
<script>{js}</script></body></html>
""".format(css=CSS, js=JS, parts="".join(parts), total=len(achievements),
           source=esc(source), jump=jump, tier_opts=tier_opts, tier_tally=tier_tally,
           bucket_tally=bucket_tally, ntracks=len(tracks), total_pts=total_pts,
           arted=arted, unarted=len(achievements) - arted,
           when=datetime.now().strftime("%Y-%m-%d %H:%M"))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Render the designed achievement roster JSON as one self-contained "
                    "HTML board. Reads the roster; never writes to it.")
    ap.add_argument("--roster", type=Path, default=DEFAULT_ROSTER,
                    help="roster JSON to read (default: docs/achievements_roster_57.json)")
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT,
                    help="HTML file to write (default: docs/achievements_roster_57_board.html)")
    ap.add_argument("--no-chibis", action="store_true",
                    help="omit the art-candidate thumbs (much smaller file)")
    ap.add_argument("-q", "--quiet", action="store_true", help="no summary on stdout")
    args = ap.parse_args(argv)

    roster_path = args.roster.resolve()
    out_path = args.out.resolve()
    if not roster_path.is_file():
        ap.error("roster not found: %s" % roster_path)
    # The roster is the design source of truth. Refuse to be the tool that eats it.
    if out_path == roster_path or out_path.suffix.lower() == ".json":
        ap.error("--out would overwrite the roster (or another JSON): %s" % out_path)

    with roster_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    src = roster_path.relative_to(ROOT).as_posix() if roster_path.is_relative_to(ROOT) \
        else roster_path.as_posix()
    doc = build(data, src, show_chibis=not args.no_chibis)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")

    if not args.quiet:
        achs = (data.get("roster") or {}).get("achievements") or []
        by_id = {b.get("id"): b for b in data.get("badges") or []}
        by_label = {}
        for b in data.get("badges") or []:
            by_label.setdefault(b.get("label"), b)
        arted = sum(1 for a in achs if badge_art(a, by_id, by_label)[0])
        print("read  {}  ({} achievements, {} tracks, {} buckets)".format(
            src, len(achs), len((data.get("roster") or {}).get("tracks") or []),
            len((data.get("roster") or {}).get("buckets") or [])))
        print("wrote {}  ({:.1f} KB)".format(out_path, out_path.stat().st_size / 1024.0))
        print("      badge art inlined for {} / {}; {} still coded-only".format(
            arted, len(achs), len(achs) - arted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
