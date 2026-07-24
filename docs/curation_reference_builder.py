"""Moonglade art curation workspace — the REFERENCE IMPLEMENTATION of the house
Curation Standard (docs/archive/CURATION_STANDARD_2026-07-17.md). Clone this for
any vote/selection artifact; never start a picker from a blank file.

Click-to-enlarge lightbox, Pick toggle (primary), optional star-rank, notes,
picks tray, export, localStorage persistence, hard completeness assertion.

TO REUSE — swap these three things for the new vote:
  1. INPUT: `FOLDER` / `gems_sigils` (where candidates come from).
  2. CLASSIFY: the `for f in folder_imgs` block that routes files into sections,
     and `SEC_DEF` (the section list). Anything unmatched MUST fall through to a
     catch-all section so nothing is dropped — the `assert len(placed) == ...`
     below enforces it.
  3. PICKS: the `rec(...)` calls + `RATIONALE` (Claude's grounded recommendations,
     written AFTER viewing the art — never guessed from filenames/alpha%).
Everything else (front-end, lightbox, tray, export, JS) is the standard; leave it.
Then: smoke-test in a browser (pick/rank/lightbox/export) before publishing."""
from pathlib import Path
from PIL import Image, ImageDraw
import base64, io, json, os, re

# INPUT/OUTPUT are per-vote and machine-local -- this file is a template meant to be
# cloned per curation task (see docstring above), not a script with working defaults.
# Set both env vars before running:
#   CURATION_INPUT_DIR = folder of this vote's candidate images (the thing being classified)
#   CURATION_OUT_DIR   = scratch dir that already contains gems_sigils_paths.json (built by
#                        a separate, earlier step that pulls existing vault reference images
#                        for this vote) and where art_selection5.html will be written
FOLDER = os.environ.get("CURATION_INPUT_DIR")
OUT = os.environ.get("CURATION_OUT_DIR")
if not FOLDER or not OUT:
    raise SystemExit(
        "curation_reference_builder.py needs local configuration before running: set the "
        "CURATION_INPUT_DIR and CURATION_OUT_DIR environment variables (see comment above)."
    )
FOLDER = Path(FOLDER)
OUT = Path(OUT)

folder_imgs = sorted([f for f in FOLDER.iterdir()
                      if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")],
                     key=lambda f: f.name.lower())
gems_sigils = json.load(open(OUT / "gems_sigils_paths.json"))


def alpha_of(im):
    return im.mode in ("RGBA", "LA") and im.convert("RGBA").getextrema()[-1][0] < 250


def checker(w, h, sq):
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(0, h, sq):
        for x in range(0, w, sq):
            d.rectangle([x, y, x + sq, y + sq], fill=(58, 54, 76) if (x // sq + y // sq) % 2 else (86, 82, 108))
    return im


def embed(f, side=340):
    im = Image.open(f)
    w0, h0 = im.size
    alpha = alpha_of(im)
    im = im.convert("RGBA") if alpha else im.convert("RGB")
    im.thumbnail((side, side))
    if alpha:
        bg = checker(im.width, im.height, max(7, im.width // 30))
        bg.paste(im, (0, 0), im)
        im = bg
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=70)
    uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    return uri, alpha, (w0, h0)


# ---- classify (completeness-asserted) ----
placed = {}
def has_alpha_file(f):
    try:
        return alpha_of(Image.open(f))
    except Exception:
        return False

for f in folder_imgs:
    n = f.name.lower()
    if "secret" in n or "gemini_generated" in n:
        placed[str(f)] = "MYS"
    elif "casting_bar" in n or "energy_bar" in n or "title_banner" in n:
        placed[str(f)] = "BAR"
    elif "gunmetal" in n or "obsidian" in n or "void-touched" in n or "crowned ruby" in n or "chatgpt image" in n:
        placed[str(f)] = "FEAT"
    elif ("golden frame" in n or "radiant" in n or "picture-frame" in n or "restrained" in n
          or "royal gold" in n or ("ornate" in n and "frame" in n)):
        placed[str(f)] = "LEG"
    elif "gift box" in n or "amethyst crystal" in n or "faceted emerald" in n or "one large" in n or "ruby cabochon" in n:
        placed[str(f)] = "CLAIM"
    elif f.name == "00046-2164985502.png":
        placed[str(f)] = "LEG"
    elif re.match(r"^\d{5}-\d+t?\.(png|jpg)$", f.name):
        placed[str(f)] = "CLAIM" if has_alpha_file(f) else "OTHER"
    else:
        placed[str(f)] = "OTHER"

assert len(placed) == len(folder_imgs), "DROPPED FILES"

def sec_files(s):
    return [f for f in folder_imgs if placed[str(f)] == s]

SEC_DEF = [
    ("CLAIM", "Claim Icons", "currency · gems · gifts",
     [(Path(r["path"]), "gallery") for r in gems_sigils] + [(f, "folder") for f in sec_files("CLAIM")]),
    ("LEG", "Legendary Frames", "the radiant-gold tier", [(f, "folder") for f in sec_files("LEG")]),
    ("FEAT", "Feat Frames", "gunmetal + ruby", [(f, "folder") for f in sec_files("FEAT")]),
    ("BAR", "Progress Bars", "the casting-gauge lane", [(f, "folder") for f in sec_files("BAR")]),
    ("MYS", "Mystery Tiles", "hidden-feat covers", [(f, "folder") for f in sec_files("MYS")]),
    ("OTHER", "Everything Else", "portraits · key-art · misc — rankable so nothing hides",
     [(f, "folder") for f in sec_files("OTHER")]),
]

# build item records + id map
items_by_sec = {}
idmap = {}
ITEMS = []
for prefix, title, sub, files in SEC_DEF:
    files = [(f, k) for f, k in files if Path(f).exists()]
    lst = []
    for i, (f, kind) in enumerate(files, 1):
        cid = "%s%d" % (prefix, i)
        uri, alpha, (w, h) = embed(f)
        rec = {"id": cid, "sec": prefix, "file": Path(f).name, "kind": kind,
               "alpha": alpha, "w": w, "h": h, "uri": uri}
        ITEMS.append(rec)
        idmap[str(f)] = cid
        lst.append(rec)
    items_by_sec[prefix] = lst

def idof(sub):
    for f, ident in idmap.items():
        if sub.lower() in f.lower():
            return ident
    return None

# Claude's recommended ids + rationale
REC = {}
def rec(sec, *subs):
    ids = [idof(s) for s in subs if idof(s)]
    REC[sec] = ids
    return ids

rec("CLAIM", "19h48m28s", "19h52m22s", "19h38m19s", "18h48m09s", "18h21m21s")
rec("LEG", "18h07m44s", "18h10m07s", "18h12m42s")
rec("FEAT", "18h18m09s", "18h20m17s", "17h52m19s")
rec("BAR", "2025638407087585424", "2025638347209702693", "2025637520349357989")
rec("MYS", "SecretFeatSquareAlpha", "SecretCurtainSquare")
REC["OTHER"] = []

RATIONALE = {
 "CLAIM": ("<b>Gem (daily-credit claim):</b> <span class='r1'>%s</span> is my #1 — fullest, most symmetric "
   "fan-cluster, richest magenta, cleanest facets. <span class='r1'>%s</span> #2 (top alpha, 81.6%%). "
   "<span class='r1'>%s</span> #3, sharper single-spike flavor. "
   "<span class='warn'>Skip 19h24m52s / 19h30m02s (crystal tiny in the left third of a wide canvas); "
   "19h31m26s sits on black with a green edge-fringe.</span><br>"
   "<b>Gift (card redemption):</b> <span class='r1'>%s</span> gold-bow, bolder silhouette; <span class='r1'>%s</span> "
   "green-bow variant as a 2nd state. First 67 (blue tag) = the historical gallery vault.")
   % (REC["CLAIM"][0], REC["CLAIM"][1], REC["CLAIM"][2], REC["CLAIM"][3], REC["CLAIM"][4]),
 "LEG": ("<span class='r1'>%s</span> is my #1 — the only frame carrying the house palette (lavender rim + "
   "emerald corner gems on gold). <span class='r1'>%s</span> #2, pearl cabochons, richest craft but pure gold. "
   "<span class='r1'>%s</span> #3, highest alpha / cleanest cut / plainest — safe fallback.")
   % (REC["LEG"][0], REC["LEG"][1], REC["LEG"][2]),
 "FEAT": ("<span class='r1'>%s</span> best alpha of the haul (73%%), truest gunmetal-grey. <span class='r1'>%s</span> "
   "my theme pick — violet smoke + ruby corners, the Void-touched concept. <span class='r1'>%s</span> same family, backup.")
   % (REC["FEAT"][0], REC["FEAT"][1], REC["FEAT"][2]),
 "BAR": ("<span class='r1'>%s</span> is the standout of the whole session — a literal <b>moon-phase progress "
   "gauge</b> (crescent→full→star→gibbous→crescent over a fill track, gold+amethyst caps). It enacts "
   "the app's own name. Near finished-asset quality. <span class='r1'>%s</span> / <span class='r1'>%s</span> gold+lavender "
   "crescent-cap alternates; the silver/celestial pair is a cooler direction.")
   % (REC["BAR"][0], REC["BAR"][1], REC["BAR"][2]),
 "MYS": ("<span class='r1'>%s</span> (SecretFeatSquareAlpha) and <span class='r1'>%s</span> (SecretCurtainSquare) are "
   "the true keyed 1:1 tiles — straight into the badge grid. <span class='warn'>SecretFeatSquare looks identical but "
   "its alpha is fully opaque — use the Alpha one.</span> The Wide crops suit the section banner, not the small tile.")
   % (REC["MYS"][0], REC["MYS"][1]),
 "OTHER": "Not achievement-pool material — Nel portraits, the twin-sorceress key-art, HappyHorse clips, the dream frame. Shown + rankable so nothing is hidden; rank anything if you disagree with the filing.",
}

DATA = {"items": ITEMS, "sections": [(p, t, s) for p, t, s, _ in SEC_DEF], "rec": REC}

# ---------- FRONT END ----------
CSS = r"""
:root{
  --bg:#0d0b1a; --bg2:#14111f; --pan:#191530; --pan2:#221c3e; --line:#322a52; --line2:#40376a;
  --ink:#ece8f8; --dim:#a99fce; --faint:#6f6893;
  --lav:#b692e6; --mauve:#c9a6ff; --emer:#4fc99a; --gold:#e0c268; --ruby:#e0355e; --gun:#8a93a2;
  --shadow:0 18px 44px -20px rgba(0,0,0,.8);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;font:15px/1.55 "Segoe UI",system-ui,sans-serif;color:var(--ink);
  background:radial-gradient(120% 80% at 50% -12%,#241a44 0,var(--bg) 58%) fixed;min-height:100vh}
.serif{font-family:Georgia,"Times New Roman",serif}
::selection{background:rgba(182,146,230,.35)}

/* command bar */
.cmd{position:sticky;top:0;z-index:80;background:rgba(11,9,22,.86);backdrop-filter:blur(12px);
  border-bottom:1px solid var(--line);padding:11px 0}
.cmd .in{max-width:1440px;margin:0 auto;padding:0 22px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.brand{font:600 18px/1 Georgia,serif;letter-spacing:.01em}
.brand .g{color:var(--gold)}
.count{display:flex;gap:16px;align-items:center;font-size:12.5px;color:var(--dim)}
.count b{font:700 16px/1 ui-monospace,monospace;font-variant-numeric:tabular-nums}
.count .pk b{color:var(--emer)} .count .rk b{color:var(--gold)}
.spacer{flex:1}
.btn{background:var(--pan);border:1px solid var(--line2);color:var(--ink);border-radius:10px;
  padding:8px 14px;font:600 12.5px/1 sans-serif;cursor:pointer;transition:.14s}
.btn:hover{border-color:var(--lav);transform:translateY(-1px)}
.btn.primary{background:linear-gradient(180deg,#f0d585,var(--gold));color:#2a2008;border-color:var(--gold)}
.btn.ghost{background:transparent}
.nav{display:flex;gap:6px;flex-wrap:wrap;margin-top:2px}
.nav a{font:600 11px/1 sans-serif;color:var(--dim);text-decoration:none;background:var(--pan);
  border:1px solid var(--line);border-radius:999px;padding:5px 11px}
.nav a:hover{border-color:var(--lav);color:var(--ink)}
.nav a b{color:var(--emer);font-variant-numeric:tabular-nums}

.wrap{max-width:1440px;margin:0 auto;padding:26px 22px 140px}
.lede{color:var(--dim);font-size:13.5px;max-width:96ch;margin:0 0 6px}
.lede b{color:var(--lav)}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11.5px;color:var(--faint);margin:10px 0 4px}
.legend span{display:inline-flex;align-items:center;gap:5px}
.dot{width:9px;height:9px;border-radius:50%}
.dot.pk{background:var(--emer)} .dot.rk{background:var(--gold)} .dot.al{background:#7fb0f4}
.dot.gl{background:#7fb0f4} .dot.fo{background:var(--emer)}

/* section */
.sec{margin-top:34px}
.sec-h{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;cursor:pointer;
  padding:12px 0 10px;border-top:1px solid var(--line)}
.sec-h .t{font:600 22px/1 Georgia,serif}
.sec-h .s{font-size:12.5px;color:var(--faint);font-style:italic}
.sec-h .badges{margin-left:auto;display:flex;gap:8px;align-items:center}
.chip{font:700 11px/1 ui-monospace,monospace;border-radius:999px;padding:4px 9px;border:1px solid}
.chip.tot{color:var(--dim);border-color:var(--line2)}
.chip.pk{color:var(--emer);border-color:#2f6b52;background:rgba(89,211,160,.09)}
.chevron{color:var(--faint);font-size:15px;transition:transform .2s}
.sec.closed .chevron{transform:rotate(-90deg)}
.sec.closed .sec-body{display:none}
.pick-note{font-size:12.5px;line-height:1.55;background:linear-gradient(90deg,rgba(182,146,230,.10),rgba(182,146,230,.02));
  border-left:3px solid var(--lav);border-radius:0 10px 10px 0;padding:10px 14px;margin:10px 0}
.pick-note .lead{font:700 11px/1 sans-serif;letter-spacing:.14em;text-transform:uppercase;color:var(--lav);display:block;margin-bottom:5px}
.pick-note b{color:var(--mauve)}
.pick-note .r1{font:800 11px/1 ui-monospace,monospace;background:rgba(224,194,104,.16);color:var(--gold);
  border:1px solid #6b5330;border-radius:5px;padding:1px 5px}
.pick-note .warn{color:#f0b866}
.notes{width:100%;background:#0f0c1e;border:1px dashed var(--line2);border-radius:10px;color:var(--ink);
  padding:9px 12px;font:13px/1.45 "Segoe UI",sans-serif;resize:vertical;min-height:44px;margin:4px 0 12px}
.notes::placeholder{color:var(--faint);font-style:italic}
.notes:focus{outline:none;border-color:var(--lav);border-style:solid}

/* grid + cards */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(176px,1fr));gap:12px}
.card{position:relative;background:var(--pan);border:1px solid var(--line);border-radius:13px;
  padding:8px;transition:transform .14s,border-color .14s,box-shadow .14s}
.card:hover{transform:translateY(-3px);border-color:var(--line2);box-shadow:var(--shadow)}
.card.picked{border-color:var(--emer);box-shadow:0 0 0 1px var(--emer),0 12px 30px -16px rgba(79,201,154,.5)}
.card.rec::after{content:"\2726 my pick";position:absolute;left:8px;bottom:44px;font:700 8.5px/1 sans-serif;
  letter-spacing:.03em;color:var(--gold);background:rgba(13,11,26,.82);border:1px solid #6b5330;
  border-radius:5px;padding:3px 6px;pointer-events:none}
.thumb{position:relative;aspect-ratio:1;border-radius:9px;overflow:hidden;background:#0f0c1e;cursor:zoom-in}
.thumb img{width:100%;height:100%;object-fit:contain;display:block;transition:transform .2s}
.thumb:hover img{transform:scale(1.06)}
.thumb .exp{position:absolute;right:6px;bottom:6px;width:24px;height:24px;border-radius:7px;
  background:rgba(13,11,26,.72);border:1px solid var(--line2);color:var(--dim);display:flex;
  align-items:center;justify-content:center;font-size:12px;opacity:0;transition:.14s;pointer-events:none}
.thumb:hover .exp{opacity:1}
.idb{position:absolute;top:6px;left:6px;font:800 9px/1 ui-monospace,monospace;background:rgba(13,11,26,.82);
  color:var(--gold);border-radius:5px;padding:3px 6px;z-index:2}
.alp{position:absolute;top:6px;left:52px;width:8px;height:8px;border-radius:50%;background:#7fb0f4;
  box-shadow:0 0 0 2px rgba(13,11,26,.7);z-index:2}
.kb{position:absolute;top:6px;right:6px;font:700 8px/1 sans-serif;text-transform:uppercase;border-radius:5px;
  padding:3px 5px;z-index:2}
.kb.gallery{background:rgba(127,176,244,.2);color:#9cc3ff} .kb.folder{background:rgba(79,201,154,.16);color:var(--emer)}
.row{display:flex;align-items:center;gap:8px;margin-top:8px}
.pick{flex:1;display:flex;align-items:center;justify-content:center;gap:6px;cursor:pointer;user-select:none;
  border:1px solid var(--line2);border-radius:9px;padding:6px 8px;font:700 11.5px/1 sans-serif;color:var(--dim);
  background:var(--pan2);transition:.13s}
.pick:hover{border-color:var(--emer);color:var(--ink)}
.pick .bx{width:15px;height:15px;border-radius:5px;border:1.5px solid var(--faint);display:flex;
  align-items:center;justify-content:center;font-size:11px;color:transparent;transition:.13s}
.card.picked .pick{background:rgba(79,201,154,.14);border-color:var(--emer);color:var(--emer)}
.card.picked .pick .bx{background:var(--emer);border-color:var(--emer);color:#0b2018}
.stars{display:flex;gap:1px}
.star{cursor:pointer;font-size:15px;color:#3b3460;line-height:1;transition:.1s}
.star:hover{transform:scale(1.15)} .star.on{color:var(--gold)}
.rankn{position:absolute;top:-7px;left:50%;transform:translateX(-50%);background:var(--gold);color:#2a2008;
  font:800 9px/1 sans-serif;border-radius:999px;padding:2px 7px;display:none;z-index:4;box-shadow:0 2px 6px rgba(0,0,0,.4)}
.card.ranked .rankn{display:block}

/* lightbox */
#lb{position:fixed;inset:0;z-index:200;background:rgba(7,5,14,.9);backdrop-filter:blur(6px);
  display:none;align-items:center;justify-content:center;padding:3vh 4vw}
#lb.on{display:flex}
#lb .stage{max-width:1100px;width:100%;display:flex;flex-direction:column;align-items:center;gap:14px}
#lb .imgwrap{max-height:74vh;display:flex;align-items:center;justify-content:center;border-radius:14px;
  overflow:hidden;box-shadow:0 30px 80px -20px #000;background:#0f0c1e}
#lb img{max-width:100%;max-height:74vh;object-fit:contain;display:block;image-rendering:auto}
#lb .cap{display:flex;align-items:center;gap:14px;flex-wrap:wrap;justify-content:center}
#lb .meta{font-size:12.5px;color:var(--dim)}
#lb .meta b{color:var(--ink)} #lb .meta .mono{font-family:ui-monospace,monospace;color:var(--gold)}
#lb .lbpick{display:inline-flex;align-items:center;gap:8px;cursor:pointer;border:1px solid var(--line2);
  border-radius:10px;padding:9px 16px;font:700 13px/1 sans-serif;color:var(--dim);background:var(--pan)}
#lb .lbpick.on{background:rgba(79,201,154,.16);border-color:var(--emer);color:var(--emer)}
#lb .lbpick .bx{width:17px;height:17px;border-radius:5px;border:1.5px solid var(--faint);display:flex;
  align-items:center;justify-content:center;color:transparent}
#lb .lbpick.on .bx{background:var(--emer);border-color:var(--emer);color:#0b2018}
#lb .lbstars .star{font-size:20px}
#lb .arrow{position:fixed;top:50%;transform:translateY(-50%);width:52px;height:52px;border-radius:50%;
  background:rgba(25,21,48,.8);border:1px solid var(--line2);color:var(--ink);font-size:22px;cursor:pointer;
  display:flex;align-items:center;justify-content:center}
#lb .arrow:hover{border-color:var(--lav)} #lb .prev{left:2vw} #lb .next{right:2vw}
#lb .x{position:fixed;top:16px;right:20px;width:42px;height:42px;border-radius:50%;background:rgba(25,21,48,.8);
  border:1px solid var(--line2);color:var(--ink);font-size:20px;cursor:pointer}
#lb .hint{font-size:11px;color:var(--faint)}

/* picks tray */
#tray{position:fixed;left:0;right:0;bottom:0;z-index:90;background:rgba(11,9,22,.94);backdrop-filter:blur(12px);
  border-top:1px solid var(--line2);transform:translateY(calc(100% - 44px));transition:transform .25s}
#tray.open{transform:translateY(0)}
#tray .bar{height:44px;display:flex;align-items:center;gap:12px;padding:0 22px;cursor:pointer}
#tray .bar .t{font:700 12.5px/1 sans-serif;letter-spacing:.1em;text-transform:uppercase;color:var(--lav)}
#tray .bar .n{font:800 14px/1 ui-monospace,monospace;color:var(--emer)}
#tray .body{max-height:38vh;overflow-y:auto;padding:6px 22px 18px}
#tray .grp{margin-top:10px}
#tray .grp h4{font:700 11px/1 sans-serif;letter-spacing:.08em;text-transform:uppercase;color:var(--dim);margin:6px 0}
#tray .strip{display:flex;gap:8px;flex-wrap:wrap}
#tray .ti{position:relative;width:72px}
#tray .ti img{width:72px;height:72px;object-fit:contain;background:#0f0c1e;border:1px solid var(--line2);border-radius:8px}
#tray .ti .rn{position:absolute;top:-6px;left:-6px;background:var(--gold);color:#2a2008;font:800 9px/1 sans-serif;border-radius:999px;padding:2px 6px}
#tray .ti .rm{position:absolute;top:-6px;right:-6px;width:18px;height:18px;border-radius:50%;background:var(--ruby);
  color:#fff;border:none;font-size:12px;line-height:1;cursor:pointer;display:none}
#tray .ti:hover .rm{display:block}
#tray .empty{color:var(--faint);font-size:12.5px;padding:8px 0}

/* export modal */
#exp{position:fixed;inset:0;z-index:210;background:rgba(7,5,14,.88);display:none;align-items:center;justify-content:center;padding:20px}
#exp.on{display:flex}
#exp .box{background:var(--pan);border:1px solid var(--gold);border-radius:16px;padding:20px;max-width:720px;width:100%;box-shadow:var(--shadow)}
#exp h3{font:600 18px/1 Georgia,serif;color:var(--gold);margin:0 0 10px}
#exp textarea{width:100%;height:300px;background:#0f0c1e;border:1px solid var(--line2);border-radius:10px;
  color:var(--ink);font:12.5px/1.5 ui-monospace,monospace;padding:12px}
@media (prefers-reduced-motion:reduce){*{transition:none!important}html{scroll-behavior:auto}}
@media (max-width:640px){.grid{grid-template-columns:repeat(auto-fill,minmax(140px,1fr))}}
"""

def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

H = ['<title>Moonglade — Art Curation</title>', '<style>' + CSS + '</style>']

# command bar
navchips = "".join('<a href="#sec-%s">%s <b>%d</b></a>' % (p, t, len(items_by_sec[p])) for p, t, s, _ in SEC_DEF)
H.append('<div class="cmd"><div class="in">'
         '<span class="brand serif">Moonglade <span class="g">Curation</span></span>'
         '<span class="count"><span class="pk">Picked <b id="c-pick">0</b></span>'
         '<span class="rk">Ranked <b id="c-rank">0</b></span></span>'
         '<span class="spacer"></span>'
         '<button class="btn ghost" onclick="collapseAll()">Collapse all</button>'
         '<button class="btn ghost" onclick="clearAll()">Clear</button>'
         '<button class="btn primary" onclick="openExp()">Export</button>'
         '</div><div class="in"><div class="nav">%s</div></div></div>' % navchips)

H.append('<div class="wrap">')
H.append('<p class="lede" style="font-size:15px;color:var(--ink);margin-bottom:2px">'
         '<span class="serif" style="font-size:19px">Pick the winners.</span> '
         'Every candidate is here — <b>%d</b> across six needs, nothing dropped.</p>' % len(ITEMS))
H.append('<p class="lede"><b>Click any image</b> to view it large (arrow keys to move, <b>P</b> to pick). '
         'Hit <b>Pick</b> to select — that is the real choice. Stars are optional, for ordering favorites. '
         'Your picks collect in the tray at the bottom. Notes autosave.</p>')
H.append('<div class="legend">'
         '<span><i class="dot pk"></i> picked</span>'
         '<span><i class="dot rk"></i> ranked</span>'
         '<span><i class="dot al"></i> has real alpha</span>'
         '<span><i class="dot gl"></i> gallery collection</span>'
         '<span><i class="dot fo"></i> 7.12 folder</span>'
         '<span>✦ = my pick</span></div>')

for prefix, title, sub, _ in SEC_DEF:
    lst = items_by_sec[prefix]
    H.append('<section class="sec" id="sec-%s"><div class="sec-h" onclick="toggleSec(this)">'
             '<span class="chevron">▾</span>'
             '<span class="t serif">%s</span><span class="s">%s</span>'
             '<span class="badges"><span class="chip pk" id="secpk-%s">0 picked</span>'
             '<span class="chip tot">%d</span></span></div><div class="sec-body">'
             % (prefix, title, sub, prefix, len(lst)))
    if prefix in RATIONALE:
        H.append('<div class="pick-note"><span class="lead">✦ Claude’s read</span>%s</div>' % RATIONALE[prefix])
    H.append('<textarea class="notes" data-sec="%s" placeholder="Notes / ideas for %s…" oninput="saveNotes(this)"></textarea>' % (prefix, title))
    H.append('<div class="grid">')
    recset = set(REC.get(prefix, []))
    for r in lst:
        cid = r["id"]
        cls = "card rec" if cid in recset else "card"
        kb = '<span class="kb %s">%s</span>' % (r["kind"], "vault" if r["kind"] == "gallery" else "7.12")
        alp = '<span class="alp" title="has alpha"></span>' if r["alpha"] else ''
        stars = "".join('<span class="star" data-n="%d" onclick="event.stopPropagation();rank(\'%s\',%d)">★</span>' % (n, cid, n) for n in range(1, 6))
        H.append(
          '<div class="%s" id="c_%s"><div class="rankn" id="rn_%s"></div>'
          '<div class="thumb" onclick="openLb(\'%s\')"><div class="idb">%s</div>%s%s'
          '<img src="%s" loading="lazy" alt="%s"><span class="exp">⛶</span></div>'
          '<div class="row"><div class="pick" onclick="pick(\'%s\')"><span class="bx">✓</span><span>Pick</span></div>'
          '<div class="stars">%s</div></div></div>'
          % (cls, cid, cid, cid, cid, alp, kb, r["uri"], esc(r["file"]), cid, stars))
    H.append('</div></div></section>')

H.append('</div>')  # wrap

# lightbox
H.append('<div id="lb"><button class="x" onclick="closeLb()">✕</button>'
         '<button class="arrow prev" onclick="lbStep(-1)">‹</button>'
         '<button class="arrow next" onclick="lbStep(1)">›</button>'
         '<div class="stage"><div class="imgwrap"><img id="lb-img" alt=""></div>'
         '<div class="cap"><span class="meta" id="lb-meta"></span>'
         '<span class="lbpick" id="lb-pick" onclick="pick(LB.cur,true)"><span class="bx">✓</span><span id="lb-pick-t">Pick</span></span>'
         '<span class="stars lbstars" id="lb-stars"></span></div>'
         '<div class="hint">← → move · P pick · Esc close</div></div></div>')

# tray
H.append('<div id="tray"><div class="bar" onclick="toggleTray()">'
         '<span class="t">Your picks</span><span class="n" id="tray-n">0</span>'
         '<span class="spacer" style="flex:1"></span><span style="font-size:11px;color:var(--faint)" id="tray-hint">click to expand</span></div>'
         '<div class="body" id="tray-body"></div></div>')

# export
H.append('<div id="exp"><div class="box"><h3 class="serif">Your picks + notes</h3>'
         '<textarea id="exp-ta" readonly></textarea>'
         '<div style="display:flex;gap:8px;margin-top:10px"><button class="btn primary" onclick="cpExp(this)">Copy</button>'
         '<span style="flex:1"></span><button class="btn ghost" onclick="document.getElementById(\'exp\').classList.remove(\'on\')">Close</button></div></div></div>')

H.append('<script id="d" type="application/json">%s</script>' % json.dumps(DATA))
H.append(r"""<script>
var D=JSON.parse(document.getElementById('d').textContent);
var BYID={}; D.items.forEach(function(r){BYID[r.id]=r;});
var picks={};   // id -> true
var ranks={};   // sec -> {rank: id}
var LB={cur:null,list:[]};

function load(){
  try{picks=JSON.parse(localStorage.getItem('mg5_picks')||'{}')}catch(e){}
  try{ranks=JSON.parse(localStorage.getItem('mg5_ranks')||'{}')}catch(e){}
  try{var n=JSON.parse(localStorage.getItem('mg5_notes')||'{}');
    document.querySelectorAll('.notes').forEach(function(t){if(n[t.dataset.sec])t.value=n[t.dataset.sec];});}catch(e){}
}
function saveP(){localStorage.setItem('mg5_picks',JSON.stringify(picks))}
function saveR(){localStorage.setItem('mg5_ranks',JSON.stringify(ranks))}
function saveNotes(t){var n={};try{n=JSON.parse(localStorage.getItem('mg5_notes')||'{}')}catch(e){}
  n[t.dataset.sec]=t.value;localStorage.setItem('mg5_notes',JSON.stringify(n));}
function secOf(id){return id.replace(/[0-9]+$/,'')}
function rankOf(id){var s=secOf(id),r=ranks[s]||{};for(var k in r){if(r[k]===id)return +k;}return 0;}

function pick(id,fromLb){
  picks[id]=!picks[id]; if(!picks[id])delete picks[id];
  saveP(); paintCard(id); if(fromLb)paintLb(); paintCounts(); paintTray();
}
function rank(id,n){
  var s=secOf(id); ranks[s]=ranks[s]||{};
  if(ranks[s][n]===id)delete ranks[s][n];
  else{for(var k in ranks[s]){if(ranks[s][k]===id)delete ranks[s][k];}ranks[s][n]=id;}
  if(!picks[id]){picks[id]=true;saveP();} // ranking implies a pick
  saveR(); paintCard(id); paintLb(); paintCounts(); paintTray();
}
function paintCard(id){
  var c=document.getElementById('c_'+id); if(!c)return;
  var pk=!!picks[id], rk=rankOf(id);
  c.classList.toggle('picked',pk); c.classList.toggle('ranked',rk>0);
  var rn=document.getElementById('rn_'+id); if(rn)rn.textContent=rk>0?('#'+rk):'';
  c.querySelectorAll('.star').forEach(function(s){s.classList.toggle('on',(+s.dataset.n)<=rk);});
}
function paintCounts(){
  document.getElementById('c-pick').textContent=Object.keys(picks).length;
  var rc=0;for(var s in ranks)rc+=Object.keys(ranks[s]).length;
  document.getElementById('c-rank').textContent=rc;
  D.sections.forEach(function(sd){var p=sd[0],n=0;
    D.items.forEach(function(r){if(r.sec===p&&picks[r.id])n++;});
    var el=document.getElementById('secpk-'+p);if(el)el.textContent=n+' picked';});
}
function paintTray(){
  var ids=Object.keys(picks); document.getElementById('tray-n').textContent=ids.length;
  var b=document.getElementById('tray-body');
  if(!ids.length){b.innerHTML='<div class="empty">No picks yet — hit “Pick” on the ones you want.</div>';return;}
  var html='';
  D.sections.forEach(function(sd){
    var p=sd[0],mine=D.items.filter(function(r){return r.sec===p&&picks[r.id];});
    if(!mine.length)return;
    mine.sort(function(a,b){return (rankOf(a.id)||99)-(rankOf(b.id)||99);});
    html+='<div class="grp"><h4>'+sd[1]+' ('+mine.length+')</h4><div class="strip">';
    mine.forEach(function(r){var rk=rankOf(r.id);
      html+='<div class="ti">'+(rk?'<span class="rn">#'+rk+'</span>':'')+
        '<button class="rm" onclick="pick(\''+r.id+'\')">×</button>'+
        '<img src="'+r.uri+'" onclick="openLb(\''+r.id+'\')" title="'+r.id+'"></div>';
    });
    html+='</div></div>';
  });
  b.innerHTML=html;
}
function toggleTray(){document.getElementById('tray').classList.toggle('open');
  document.getElementById('tray-hint').textContent=document.getElementById('tray').classList.contains('open')?'click to collapse':'click to expand';}
function toggleSec(h){h.parentNode.classList.toggle('closed');}
function collapseAll(){document.querySelectorAll('.sec').forEach(function(s){s.classList.add('closed');});}
function clearAll(){if(confirm('Clear all picks, ranks and notes?')){picks={};ranks={};saveP();saveR();
  localStorage.removeItem('mg5_notes');document.querySelectorAll('.notes').forEach(function(t){t.value='';});
  D.items.forEach(function(r){paintCard(r.id);});paintCounts();paintTray();}}

/* lightbox */
function openLb(id){var r=BYID[id];if(!r)return;
  LB.list=D.items.filter(function(x){return x.sec===r.sec;}).map(function(x){return x.id;});
  LB.cur=id; renderLb(); document.getElementById('lb').classList.add('on');}
function renderLb(){var r=BYID[LB.cur];
  document.getElementById('lb-img').src=r.uri;
  document.getElementById('lb-meta').innerHTML='<span class="mono">'+r.id+'</span> · '+r.file.replace(/</g,'')+
    ' · <b>'+r.w+'×'+r.h+'</b>'+(r.alpha?' · <b style="color:#7fb0f4">alpha</b>':'');
  var st=document.getElementById('lb-stars');st.innerHTML='';
  for(var n=1;n<=5;n++){var s=document.createElement('span');s.className='star';s.textContent='★';
    (function(nn){s.onclick=function(){rank(LB.cur,nn);};})(n);st.appendChild(s);}
  paintLb();
}
function paintLb(){if(!LB.cur||!document.getElementById('lb').classList.contains('on'))return;
  var r=BYID[LB.cur];var pk=!!picks[LB.cur],rk=rankOf(LB.cur);
  var lp=document.getElementById('lb-pick');lp.classList.toggle('on',pk);
  document.getElementById('lb-pick-t').textContent=pk?'Picked':'Pick';
  document.getElementById('lb-stars').querySelectorAll('.star').forEach(function(s,i){s.classList.toggle('on',(i+1)<=rk);});
}
function lbStep(d){var i=LB.list.indexOf(LB.cur);i=(i+d+LB.list.length)%LB.list.length;LB.cur=LB.list[i];renderLb();}
function closeLb(){document.getElementById('lb').classList.remove('on');}
document.getElementById('lb').addEventListener('click',function(e){if(e.target===this)closeLb();});
document.addEventListener('keydown',function(e){
  if(!document.getElementById('lb').classList.contains('on'))return;
  if(e.key==='ArrowLeft')lbStep(-1);else if(e.key==='ArrowRight')lbStep(1);
  else if(e.key==='Escape')closeLb();else if(e.key.toLowerCase()==='p'){pick(LB.cur,true);}
});

/* export */
function openExp(){var L=[];
  D.sections.forEach(function(sd){var p=sd[0];
    var mine=D.items.filter(function(r){return r.sec===p&&picks[r.id];});
    if(mine.length){mine.sort(function(a,b){return (rankOf(a.id)||99)-(rankOf(b.id)||99);});
      L.push('== '+sd[1]+' ('+p+') ==');
      mine.forEach(function(r){var rk=rankOf(r.id);L.push('  '+(rk?'#'+rk+' ':'• ')+r.id+'  ('+r.file.replace(/</g,'')+')');});
      L.push('');}});
  var notes=[];try{notes=JSON.parse(localStorage.getItem('mg5_notes')||'{}')}catch(e){}
  var nk=Object.keys(notes).filter(function(k){return (notes[k]||'').trim();});
  if(nk.length){L.push('== notes ==');nk.forEach(function(k){L.push('['+k+'] '+notes[k].trim());});}
  document.getElementById('exp-ta').value=L.join('\n')||'(no picks yet)';
  document.getElementById('exp').classList.add('on');
}
function cpExp(btn){var ta=document.getElementById('exp-ta');ta.focus();ta.select();var ok=false;
  try{ok=document.execCommand('copy')}catch(e){}
  if(!ok&&navigator.clipboard){navigator.clipboard.writeText(ta.value);ok=true;}
  btn.textContent=ok?'✓ copied':'Ctrl-C';setTimeout(function(){btn.textContent='Copy';},1500);}
document.getElementById('exp').addEventListener('click',function(e){if(e.target===this)this.classList.remove('on');});

load();
D.items.forEach(function(r){paintCard(r.id);});
paintCounts();paintTray();
</script>""")

(OUT / "art_selection5.html").write_text("\n".join(H), encoding="utf-8")
sz = (OUT / "art_selection5.html").stat().st_size
print("wrote art_selection5.html: %.2f MB, %d items" % (sz / 1e6, len(ITEMS)))
print("sections:", {p: len(items_by_sec[p]) for p, _, _, _ in SEC_DEF})
print("completeness: all %d folder imgs placed = %s" % (len(folder_imgs), len(placed) == len(folder_imgs)))
