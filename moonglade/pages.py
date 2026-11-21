"""
moonglade/pages.py
==================
The page shells' shared text: DESIGN_TOKENS_CSS (the single source of the palette and the
achievement skins), `_upscale_const_js`, the pre-paint and 401-guard scripts every shell
carries, and the Loom's shell (`_LOOM_SHELL`, `LOOM_PAGE_BUNDLE`). The routes that serve them
are moonglade/routes_gate.py's and moonglade/routes_loom.py's; dev/tools/export_design_kit.py
regenerates the design kit's token copies from this file. Moved verbatim out of
moonglade/gallery.py in the 3.22 split (phase 4).

It needs nothing from the gallery or the engine.
"""
import json

from moonglade import gen_params as _gen_params


# Design tokens: the SINGLE source of truth for the gallery's palette + achievement
# skins, shared (via the __DESIGN_TOKENS__ marker + .replace()) by the React shells
# (APP_PAGE/LOGIN_PAGE) and LOOM_PAGE_BUNDLE so every surface
# re-skins together instead of the Loom carrying its own copy that silently drifts.
DESIGN_TOKENS_CSS = r"""
  /* Z BANDS (decided 2026-08-01, gallery-era redesign): exactly three, nothing between --
     components 0-7 · overlays/modals 300-500 · ambient/celebration 510-520 (the layer that
     must paint over any modal). Normalized 2026-09-28: the legacy 200s cluster and the
     stray 99 went with the classic surfaces, and every other value that sat outside a band
     was renumbered into one in its old order. The achievement moment is 519, not the
     design's 520: its parade's skip control must paint in front of it and 520 is the
     ceiling. The ladder is gallery/src/styles/overlays.css's -- do not add values outside
     the three bands. */
  :root {
    /* Palette sampled from two reference images:
       731004762264180451.webp — teal "magic glow", green gems, rare gold trim.
       s1_06.png              — the deep violet armor (#33236d/#241f5b/#36345a/#643aac)
                                that tints the ground and surfaces below. */
    --base:    #0c0a1c; --mantle:  #0a0818; --surface0:#211f3a;
    --surface1:#3a3460; --overlay0:#6a6088; --text:    #d6d2e2;
    --subtext: #9a93ab; --lavender:#b692e6; --mauve:   #c4a6f0;
    --red:     #f38ba8; --peach:   #fab387; --green:   #46d488;
    --blue:    #47cbc3; --sapphire:#3a8a93;
    /* --loomc is the Loom's fixed-meaning cyan (hue law: cyan means the Loom in every
       skin). Same value as --blue on purpose: the UI Kit v2 designs reference the hue
       by this name, and the semantic name must exist in the pipeline or var(--loomc)
       falls back silently at handoff. --blue stays for existing usages. */
    --loomc:   #47cbc3;
    /* Moonglade Athenaeum palette: lavender leads, emerald is the "magic"
       highlight (Nelnamara's gems), gold filigree is rare. */
    --accent:  #b692e6; --accent-soft:#4fc99a; --gold: #d4af37; --emerald:#4fc99a;
    --purple-deep: #33236d; --purple-bright: #643aac;
    /* Feat tier: gunmetal band + ruby glow (the agreed 5th tier -- NOT pink). */
    --gunmetal: #8a93a2; --gunmetal-deep: #4a515c;
    --ruby: #e0355e; --ruby-deep: #a11238;
    /* Native controls (checkbox/radio/range/progress) default to the BROWSER's
       accent -- Windows Chrome's is a bright blue that belongs to no skin here.
       Three places had already set this one control at a time; declaring it on
       :root covers every control app-wide, and because it is an inherited
       property a skin that redefines --accent retints them for free. Per-control
       overrides (e.g. the ruby unleash toggle) still win on specificity. */
    accent-color: var(--accent);
    /* accent-color only tints the CHECKED fill; an unchecked box, a native select
       arrow and the scrollbars all keep light OS chrome without this. Every
       surface in this app is dark, so declaring it once here is what actually
       stops white checkboxes sitting on top of artwork. */
    color-scheme: dark;
  }
  /* ---- Skins: cosmetic palette swaps unlocked by achievements. A skin overrides
     the meaningful subset of the palette; everything else inherits :root. Applied
     via <html data-skin="..."> (set pre-paint from localStorage in <head>). ---- */
  html[data-skin="nightfallen"] {
    --base:#0a0713; --mantle:#080610; --surface0:#241a3f; --surface1:#3c2b63;
    --text:#e7ddff; --subtext:#a493c9; --overlay0:#7a6aa6;
    --accent:#a678f0; --lavender:#c9a6ff; --mauve:#d3b6ff;
    --emerald:#7f6fe0; --accent-soft:#8b7ae6; --gold:#d9b3ff;
  }
  html[data-skin="moonlit"] {
    --base:#0b1018; --mantle:#080d15; --surface0:#1c2735; --surface1:#334358;
    --text:#e6eefb; --subtext:#93a6bd; --overlay0:#6f8298;
    --accent:#8fb8e8; --lavender:#bcd6f5; --mauve:#c6dbf7;
    --emerald:#68d5e0; --accent-soft:#6fc9d6; --gold:#cfe1f5;
  }
  html[data-skin="ember"] {
    --base:#160c0c; --mantle:#120909; --surface0:#33201c; --surface1:#5a352c;
    --text:#fbe6df; --subtext:#c79b8d; --overlay0:#a5786a;
    --accent:#e8935f; --lavender:#f0b48f; --mauve:#f3c3a5;
    --emerald:#e0a94b; --accent-soft:#d67f4b; --gold:#ffcf7a;
  }
  html[data-skin="verdant"] {
    --base:#0a1410; --mantle:#08110d; --surface0:#173026; --surface1:#2a5140;
    --text:#e2f5ea; --subtext:#93bda6; --overlay0:#6f9d84;
    --accent:#5fd39a; --lavender:#8fe8bf; --mauve:#a5f3cf;
    --emerald:#4fc99a; --accent-soft:#4bd68f; --gold:#c8e6a8;
  }
"""


def _upscale_const_js():
    """The upscale constants, handed to the client from core, through the
    __UPSCALE_CONST__ marker (same idiom as __DESIGN_TOKENS__).

    Two things ride along and both have one source of truth here rather than a retyped
    copy in a template or a component:

    * the five upscaler names, which PixAI matches LITERALLY -- mixed underscores, spaces
      and plus signs and all ("R-ESRGAN 4x+ Anime6B") -- so a typo is a rejected submit;
    * UPSCALE_PIXEL_CEILING, so <UpscalePanel> can derive the same dynamic ratio cap
      the server clamps to WITHOUT a second hand port of max_upscale_ratio. The Generate
      drawer still carries its own ported copy (documented, and pinned against the Python
      by dev/tests/test_upscale_boosters.py); this exists so the new surface does not add a
      third place for those numbers to drift.

    Substituted into APP_PAGE and the Loom shells (the surfaces with upscale UI)
    since the classic cut (2026-08-08) removed the INDEX/DETAIL pages it was
    originally built for.
    """
    from moonglade import backup as core
    return ("<script nonce=\"__CSP_NONCE__\">window.MG_UPSCALE={};window.MG_LORA={};</script>".format(
        json.dumps({
            "enlargeModels": list(_gen_params.ENLARGE_MODELS),
            "defaultEnlargeModel": _gen_params.DEFAULT_ENLARGE_MODEL,
            "ceiling": _gen_params.UPSCALE_PIXEL_CEILING,
            # So the panel can upscale an image whose model the catalog never recorded,
            # instead of refusing until one is picked -- PixAI's own dialog has no model
            # control at all. Served rather than retyped, like everything else here. It is
            # a VERSION id, so the panel sends it as version_id; see core for why.
            "fallbackVersionId": _gen_params.UPSCALE_FALLBACK_VERSION_ID,
            "denoise": {"strength": _gen_params.DEFAULT_UPSCALE_DENOISING_STRENGTH,
                        "steps": _gen_params.DEFAULT_UPSCALE_DENOISING_STEPS},
        }, separators=(",", ":")),
        # LoRA weight bounds per base architecture -- DiT allows 0..1.2, the SD family
        # -2..2. One table, served, so the drawer's slider and the builder's clamp cannot
        # drift into offering a weight the architecture rejects.
        json.dumps({
            "ranges": {k: list(v) for k, v in _gen_params.LORA_WEIGHT_RANGES.items()},
            "fallback": [_gen_params.LORA_WEIGHT_MIN, _gen_params.LORA_WEIGHT_MAX],
            "step": _gen_params.LORA_WEIGHT_STEP,
        }, separators=(",", ":"))))


# ---------------------------------------------------------------------------
# THE PRE-PAINT BOOT SCRIPT, injected into EVERY page head (the React shells and
# _LOOM_SHELL), immediately before the 401 guard below.
#
# Two per-device looks are stored in localStorage and PAINT THE PAGE, so both have to be
# applied in <head> before the first frame or the app renders in the wrong colours/face
# and then visibly jumps:
#   skin   -- html[data-skin], read by every skin rule in DESIGN_TOKENS_CSS.
#   fonts  -- the System + Hero type pairing (2026-09-04, Identity Chrome handoff C1),
#             written as inline --font-hero/--font-system custom properties on <html>.
#             The stored record carries the STACKS themselves, not just an id, precisely
#             so this script needs no copy of the pairing table -- swapping the
#             (deliberately provisional) set in gallery/src/lib/fonts.js changes nothing
#             here. gallery/src/lib/fonts.js reconciles the id against the current table
#             once the bundle is up.
# Both reads are wrapped: storage throws outright in private mode / with site data
# blocked, and an unstyled page is a far better failure than a blank one.
#
# ONE COPY, three shells. The skin line used to be hand-pasted into APP_PAGE, LOGIN_PAGE
# and _LOOM_SHELL separately; a second stored look would have made that three drifting
# copies of two things instead of one.
_PREPAINT_BOOT_JS = r"""<script nonce="__CSP_NONCE__">/* apply the saved skin + type pairing before first paint (no FOUC)
   -- see _PREPAINT_BOOT_JS in moonglade_gallery.py. Same keys/origin the gallery writes,
   so a change made there re-dresses the Loom too. */
try{var _sk=localStorage.getItem('skin');if(_sk&&_sk!=='moonglade')document.documentElement.setAttribute('data-skin',_sk);}catch(e){}
try{var _ft=JSON.parse(localStorage.getItem('fonts')||'null');if(_ft&&typeof _ft==='object'){if(_ft.hero)document.documentElement.style.setProperty('--font-hero',_ft.hero);if(_ft.system)document.documentElement.style.setProperty('--font-system',_ft.system);}}catch(e){}</script>"""


# ---------------------------------------------------------------------------
# Global 401 guard, injected into EVERY page head (the React shells and _LOOM_SHELL).
#
# Why an interceptor and not a helper at each call site: when it was written there were ~90
# fetch() calls across moonglade_gallery.py's inline JS, static/*.js and the Loom bundle, and
# a browser crawl found that NOT ONE of them inspects response status. The gate
# answers an expired session with a JSON 401 -- valid JSON -- so `r.json()`
# resolves happily, `.catch` never fires, and callers read the error body as
# data. Observed consequences: the job poller reads `d.phase` as undefined,
# decides "still running", and re-polls every 3s FOREVER with the drawer pinned
# on "Rendering under the eclipse..."; the picker renders "No images found" for
# a full library; the Loom's pollImg/runGen loops never terminate.
#
# Wrapping fetch once covers all ~90 sites, including code inside the prebuilt
# bundle that no call-site edit could reach, and cannot miss one the way a
# 90-site refactor could.
#
# Defined ONCE here and injected into both shells. Today produced two separate
# bugs from hand-synced duplicate copies (the Loom hook preamble, and a login
# CSS block) -- not adding a third.
_AUTH_401_GUARD_JS = r"""<script nonce="__CSP_NONCE__">/* Global 401 guard -- see _AUTH_401_GUARD_JS in moonglade_gallery.py */
(function(){
  if (!window.fetch) return;
  var orig = window.fetch, redirecting = false;
  window.fetch = function(input, init){
    return orig.apply(this, arguments).then(function(res){
      try{
        if (res && res.status === 401 && !redirecting) {
          var url = new URL((typeof input === 'string' ? input : (input && input.url) || ''),
                            location.href);
          /* Same-origin only: a 401 from a third party is not our session. And
             never bounce while already on /login, which would loop. */
          if (url.origin === location.origin && location.pathname !== '/login') {
            redirecting = true;
            location.href = '/login?next=' +
              encodeURIComponent(location.pathname + location.search);
          }
        }
      }catch(e){ /* never let the guard break a real response */ }
      return res;   /* hand the response back untouched -- callers are unchanged */
    });
  };
})();
</script>"""


# The Loom (Seedance video storyboard tool) is served at /loom. Its React source
# lives in loom/master-storyboard.jsx; this page loads React + picker-core from
# locally-vendored files (loom/vendor/, served by /loom/vendor/<file>; zero network
# calls to paint) and, per the tool's own integration notes, swaps window.storage onto
# the gallery backend so a board persists server-side (shared across devices) instead
# of per-browser localStorage.
# viewport-fit=cover for the same reason APP_PAGE carries it (2026-09-06): the Loom is
# reachable from the phone (AppMobile's Loom sheet links straight here) and
# master-storyboard.jsx's own chrome reads env(safe-area-inset-top/bottom) in five places,
# every one of which resolved to 0 while this meta stayed narrow.
_LOOM_SHELL = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>The Loom - Moonglade Athenaeum</title>
<link rel="icon" type="image/png" href="/branding/favicon.png">
""" + _PREPAINT_BOOT_JS + _AUTH_401_GUARD_JS + r"""
<style>
__DESIGN_TOKENS__
/* font-family here, not just in .sb-root: anything mounted OUTSIDE #root inherits from
   body, and this shell deliberately mounts things there -- the toast stack, the ? FAB.
   Without it they fell back to the browser default font while the gallery shell gave them
   system-ui, so the same components looked different on the two pages. notify.css now also
   states its own family (host-neutral by design), but the shell should not be handing
   anything an unstyled baseline. */
body { background: var(--base); margin: 0; font-family: var(--font-system, system-ui, sans-serif); }
/* The old #jobs-fab/#jobs-tray positioning overrides (bottom:88px to clear the Cast panel's
   own buttons; z-index:401/402 to climb over .lv-overlay's 400) were retired 2026-08-09
   (Claude Design handoff, drift item 39). The Activity control is no longer a body-portaled
   floating tray -- it's .lv-top-act-wrap, a normal child of .lv-overlay itself
   (master-storyboard.jsx's own toolbar), so it was never competing with .lv-overlay's z-index
   at the root context in the first place; it just paints in normal document order, correctly
   UNDER Deep Focus's veil like everything else inside .lv-overlay, with no !important
   reconciliation needed anywhere. */

/* Clearance under the ? help FAB, which is the cost of making it visible at all.
   #eb-help-btn is position:fixed bottom:18px + 38px tall, so it floats over the
   bottom-right ~56px of the viewport -- and on /loom the bottom-right IS the Generate
   drawer (.lv-side.right is 560px wide). .mgd-go and <mg-cost-badge> sit in .lv-gen's
   NORMAL FLOW, not a pinned footer, so once the drawer is scrolled to its end -- the
   ordinary position right before you submit -- the FAB covered the right edge of the
   Generate button and clipped the tail of the cost readout ("· saves ~84,000 credits",
   the expiry sub-line). This project's standing rule is to report the real cost of every
   generation, so a partly-obscured cost line is not an acceptable trade for a visible
   help button.
   Padding, not another z-index change: the FAB SHOULD stay on top, the content just
   needs somewhere to scroll to. 64px = the FAB's 56px footprint + breathing room.
   #root out-specifies the .lv-gen rule in master-storyboard.jsx's STYLES regardless of
   which <style> React injects first -- and keeping it here rather than in the jsx means
   the FAB and its clearance live together, and no bundle rebuild is needed. */
#root .lv-gen { padding-bottom: 64px; }
</style>
<script src="/loom/vendor/react.production.min.js"></script>
<script src="/loom/vendor/react-dom.production.min.js"></script>
<!-- The video Generate drawer and its cost badge are the React <VideoDrawer> / <CostBadge>,
     bundled into master-storyboard.bundle.js as of the 2026-08-08 no-vanilla port -- no static
     script tags. -->
__UPSCALE_CONST__
</head><body>
<div id="root"></div>
<!-- The #jobs-fab/#jobs-tray anchors lived here until the 2026-08-08 no-vanilla port, then
     were rendered by the portaled React <ActivityTray> with the same ids. Both are gone as
     of 2026-08-09 (Claude Design handoff, drift item 39): the Activity control is inline in
     the toolbar (master-storyboard.jsx's own .lv-top-act-wrap) now, not body-level. -->
<script nonce="__CSP_NONCE__">
/* Session P (BUILD-w5-p s3.5, review F15): every call now REJECTS on a failed answer instead
   of reading one as "nothing there" -- a failed or unreadable get used to come back null, and
   the boot path seeded a blank board over the key. get also hands back the board's rev (and
   missing:true for an absent key); set takes an optional {base_rev} and resolves {ok, rev} or
   {conflict, value, rev} (the server's compare-and-swap), throwing on anything else. */
window.storage = (function(){
  function fail(r, d){ var e = new Error((d && d.error) || ('HTTP ' + r.status)); e.status = r.status; e.unreadable = !!(d && d.error === 'unreadable'); throw e; }
  function body(r){ return r.json().catch(function(){ return null; }); }
  return {
    get:function(k){ return fetch('/api/loom/get?key='+encodeURIComponent(k)).then(function(r){ return body(r).then(function(d){ if(!r.ok || !d) fail(r, d); if (d.value != null) return {value:d.value, rev:d.rev}; return d.missing ? {value:null, missing:true, rev:d.rev} : null; }); }); },
    set:function(k,v,shared,opts){ var b={key:k,value:v}; if (opts && opts.base_rev != null) b.base_rev = opts.base_rev; return fetch('/api/loom/set',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}).then(function(r){ return body(r).then(function(d){ if (r.status === 409 && d && d.conflict) return {conflict:true, value:d.value, rev:d.rev}; if(!r.ok || !d || d.ok === false) fail(r, d); return {ok:true, rev:d.rev}; }); }); },
    list:function(p){ return fetch('/api/loom/list?prefix='+encodeURIComponent(p||'')).then(function(r){ return body(r).then(function(d){ if(!r.ok || !d) fail(r, d); return {keys:(d.keys)||[]}; }); }); },
    delete:function(k){ return fetch('/api/loom/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:k})}).then(function(r){ return body(r).then(function(d){ if(!r.ok || (d && d.ok === false)) fail(r, d); return d; }); }); }
  };
})();
/* The feat beacon's per-render nonce (2026-09-07 ruling -- see api_ach_event()). Since
   Session I (2026-09-28) this shell posts NOTHING itself: the "?" below opens the guide, and
   the guide's own open sends the docs event through gallery/src/notify/achNonce.js, which the
   Loom bundle carries -- the one poster, with the one set of rules (send the nonce, adopt
   next_nonce, one conditional stale-page retry). That module reads its first nonce from
   here when there is no MG_BOOT. The value below is a PLACEHOLDER the /loom route substitutes
   on the way out -- a fresh mint per render, exactly as app_page puts one in MG_BOOT.
   (Naming the placeholder token in this comment would substitute it here too.) */
window.MG_ACH_NONCE = "__ACH_NONCE__";
</script>
__RUNTIME_SCRIPT_BLOCK__
<!-- The Loom's "?" (Session I decision 2): the hand-written quick guide that used to open
     here retired; the button opens the in-app guide (the wiki this install carries) on The
     Loom's page, through the verb the bundle publishes (gallery/src/help/helpStore.js). -->
<button id="eb-help-btn"
  style="position:fixed;bottom:18px;right:18px;z-index:401;width:38px;height:38px;border-radius:50%;background:var(--accent);color:var(--base);border:none;font-size:19px;font-weight:700;cursor:pointer;box-shadow:0 4px 18px rgba(0,0,0,.5);"
  title="The Loom's page of the guide (?)" aria-label="Open the guide">?</button>
<!-- Its click is wired here, not in an onclick attribute: the page's script policy runs only
     nonced scripts (CSP_PAGE_POLICY), and an inline handler is not one. -->
<script nonce="__CSP_NONCE__">
document.getElementById("eb-help-btn").addEventListener("click", function () {
  if (window.mgHelp) window.mgHelp.open('The-Loom');
});
</script>
</body></html>"""

# The Loom's ONE delivery path (bundle-only since the Babel-standalone retirement,
# 2026-08-08): the pre-transpiled loom/dist/master-storyboard.bundle.js (built by
# `npm run build` in loom/, via esbuild). A real module build -- shared modules are
# plain imports, no client-side transpile, no inline-stripping.
LOOM_PAGE_BUNDLE = (_LOOM_SHELL
    .replace("__RUNTIME_SCRIPT_BLOCK__",
             # The CSS esbuild emits for the shared React components master-storyboard.jsx
             # imports (gallery-picker.css today; grows as the vanilla campaign moves more
             # components into the bundle). Only these on-demand modals need it, so loading
             # it here (not the <head>) is fine -- no first-paint FOUC. Absent => harmless
             # 404 until the bundle is built.
             '<link rel="stylesheet" href="/loom/dist/master-storyboard.bundle.css">\n'
             '<script src="/loom/dist/master-storyboard.bundle.js"></script>\n'
             '<script nonce="__CSP_NONCE__">ReactDOM.createRoot(document.getElementById("root"))'
             '.render(React.createElement(LoomBundle.default));</script>')
    .replace("__DESIGN_TOKENS__", DESIGN_TOKENS_CSS))
