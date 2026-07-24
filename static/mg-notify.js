/* mg-notify.js -- the achievement-toast celebration system, the corner Toast utility, and
   the Job activity tracker (Jobs + JobsCard), extracted verbatim from the gallery's own
   inline <script> so BOTH the vanilla gallery and the React Loom can load ONE copy instead
   of two hand-duplicated ones drifting apart (the same "Option-A cohesion" reasoning as
   static/mg-generate-drawer.js / mg-model-picker.js / mg-gallery-picker.js).

   Unlike those three, this file is NOT a custom element -- Ach/Toast/Jobs/JobsCard are plain
   global IIFEs operating directly on document.body/getElementById, matching exactly what they
   were before the move. Plain global <script src>, no build step, no shadow DOM. Self-injects
   one <style> tag (the one convention borrowed from the custom-element files) so a single
   <script src="/static/mg-notify.js"> tag carries both behavior and styling -- a host page
   needs nothing else EXCEPT two small DOM anchors for the visible Job Tracker card to render
   into: <div id="jobs-fab" onclick="JobsCard.open()" title="Activity">...</div> and
   <div id="jobs-tray" aria-label="Job activity"></div>. The achievement-toast celebration
   path (Ach's toastNew/celebrate/_mkMoment) needs NO anchor at all -- it builds its own DOM
   from scratch and fires automatically via this file's own DOMContentLoaded listener. Toast's
   own #mg-toasts container is also self-created (see Toast.box() below) -- no anchor needed.
   The achievement MODAL (the Folio of Honors, #ach-modal) is intentionally NOT included in this file's
   anchor requirements -- a host that wants the full modal must still add that HTML separately;
   Ach.open()/close() are guarded (see below) so they simply no-op if #ach-modal is absent,
   rather than crashing a host that only wants toasts + the tracker.

   De-duplication: this is now the SINGLE SOURCE for these four systems -- the gallery's own
   inline copies are deleted in favor of this file (see pixai_gallery.py), closing out the same
   kind of two-copies-drift-apart gap this codebase has hit before (the mg-generate-drawer.js
   twin-drawer situation, the friendlyGenErr/GIVE_UP_MS duplications). */
(function () {
  'use strict';

  // ---- one injected <style>, matching this app's shared DESIGN_TOKENS_CSS custom properties.
  // Verbatim from the gallery's own inline <style> blocks, with three deliberate changes:
  //   1. z-index raised for the toast-only elements (.ach-m2/.m2-conf/#mg-toasts) so a
  //      celebration or completion toast is never silently swallowed by the Loom's own
  //      full-screen overlays (Deep Focus veil z-index 450, Sequence Player z-index 500,
  //      both everyday Loom interactions) -- #jobs-fab/#jobs-tray are a persistent widget,
  //      not a time-limited celebration, so they're left at their original z-index.
  //   2. the pre-existing duplicate `.ach-modal{...}` rule is now just ONE copy.
  //   3. the dead `.ach-toast`/`.at-*` rules (zero JS references anywhere, superseded by
  //      `.ach-m2`) were not carried forward.
  var STYLE_ID = 'mg-notify-style';
  var MG_CSS = [
    // `.ach-modal` is SHARED base modal chrome -- used by #ach-modal (Achievements),
    // #contest-modal (Contests), and #art-modal (YourArt), NOT achievement-exclusive. Never
    // scope or drop this independently of those other two features.
    '.ach-modal{position:fixed;inset:0;z-index:300;background:rgba(6,4,14,.72);backdrop-filter:blur(4px);display:none;align-items:flex-start;justify-content:center;padding:5vh 16px;overflow-y:auto;}',
    '.ach-modal.open{display:flex;}',
    // The 2026-07-21 host-neutral font fix (see the #jobs-fab/#jobs-tray/#mg-toasts comment
    // below) only covered those three roots -- it missed the achievement celebration (.ach-m2,
    // below) and this Folio of Honors subtree (#ach-modal, the achievement-specific id, NOT
    // the shared `.ach-modal` class above -- scoping it to the id avoids also restyling
    // #contest-modal/#art-modal, which reuse that same base chrome class but are not part of
    // this fix). Same bug, same fix: state font-family explicitly instead of inheriting it,
    // since the gallery's BASE_HTML body sets it but _LOOM_SHELL's body does not.
    '#ach-modal{font-family:system-ui,sans-serif;}',
    '.ach-panel{position:relative;width:760px;max-width:96vw;background:var(--mantle);border:1px solid var(--surface1);border-radius:16px;box-shadow:0 30px 90px rgba(0,0,0,.6);padding:24px 26px 28px;}',
    '.ach-x{position:absolute;top:12px;right:14px;background:none;border:none;color:var(--subtext);font-size:26px;line-height:1;cursor:pointer;}',
    '.ach-x:hover{color:var(--text);}',
    '.ach-htitle{font-size:21px;font-weight:700;color:var(--text);letter-spacing:.01em;}',
    '.ach-hsub{font-size:12px;color:var(--subtext);margin-top:3px;}',
    '.ach-hsub b{color:var(--lavender);}',
    // .ach-grid is a layout ROOT (#ach-grid, the All tab's container), not a tile -- it must
    // stack its children (the carousel, the ladder row, each .hall-block section) as normal
    // full-width blocks. The 2026-07-22 redesign's own card grids (.hall-cardgrid,
    // .hall-ladders) are the ones that tile into columns now, each independently, nested
    // INSIDE these blocks -- #ach-grid itself was never meant to size its own direct
    // children as tiles. (This WAS display:grid;grid-template-columns:repeat(auto-fill,
    // minmax(216px,1fr)) for the pre-redesign flat card layout, where every direct child
    // really was one ~216px tile -- left unchanged by mistake when the redesign landed,
    // which auto-placed every new full-width section into narrow tiled columns instead of
    // stacking them -- the actual cause of the overlapping/scrambled render this fixes.)
    '.ach-grid{display:flex;flex-direction:column;margin-top:18px;}',
    '.ach-nar{width:34px;height:34px;border-radius:50%;object-fit:cover;object-position:60% 30%;cursor:pointer;border:1px solid var(--surface1);vertical-align:middle;margin-left:9px;transition:transform .12s,border-color .12s;}',
    '.ach-nar:hover{transform:scale(1.12);border-color:var(--lavender);}',
    '.ach-unleash{display:inline-flex;align-items:center;gap:6px;font-size:11px;color:var(--ruby);margin-left:12px;cursor:pointer;user-select:none;border:1px solid var(--ruby-deep);border-radius:999px;padding:3px 10px;background:rgba(224,53,94,.08);}',
    '.ach-unleash input{accent-color:var(--ruby);}',
    // ---- The Folio of Honors (Trophy Hall redesign, 2026-07-22). Tier-triad colors
    // (--tc/--tcl/--tcd) below are the SAME hex values as .ach-m2's toast triads (see
    // above), confirmed byte-for-byte identical -- one set defined here too rather than
    // sharing across scopes, since .ach-m2's are deliberately scoped and this keeps that
    // scoping intact. Everything else uses the app's real design tokens (var(--lavender)
    // etc.), never fixed hex, so the Hall keeps retinting per active skin like the rest
    // of the app.
    '.ach-hall.open{align-items:center;padding:3vh 3vw;}',
    '.ach-hall .ach-panel{width:96vw;max-width:1320px;height:94vh;max-height:860px;padding:0;display:flex;flex-direction:column;overflow:hidden;background:linear-gradient(160deg,var(--mantle) 0%,var(--base) 100%);transform-origin:top right;animation:hall-in .28s cubic-bezier(.16,.84,.34,1.06);}',
    '@keyframes hall-in{from{opacity:0;transform:scale(.93) translateY(-12px);}to{opacity:1;transform:none;}}',
    '@media (prefers-reduced-motion: reduce){ .ach-hall .ach-panel{animation:none;} }',
    '.ach-hall .ach-x{position:static;font-size:24px;flex:none;}',
    '.hall-head{display:flex;align-items:center;gap:13px;padding:12px 20px;flex:none;border-bottom:1px solid var(--surface1);background:linear-gradient(180deg,var(--surface0),transparent);}',
    '.hall-title{font-size:19px;font-weight:700;color:var(--text);display:flex;align-items:center;white-space:nowrap;}',
    // the narrator avatar doubles as the Folio's header mascot -- restyled with a glow ring
    // to match the new look, but still the SAME clickable poke-the-narrator Easter egg
    // (Ach.poke() -> the Triggered feat), deliberately kept live rather than swapped for
    // an inert decorative image.
    '.ach-hall .ach-nar{width:36px;height:36px;border:2px solid rgba(182,146,230,.85);box-shadow:0 0 0 2px rgba(120,60,200,.45),0 0 9px rgba(182,146,230,.7),0 0 20px rgba(120,60,200,.3);}',
    '.hall-score{font-size:12.5px;color:var(--subtext);white-space:nowrap;}',
    '.hall-score b{color:var(--lavender);font-variant-numeric:tabular-nums;}',
    '.hall-search{margin-left:auto;background:var(--base);border:1px solid var(--surface1);border-radius:999px;color:var(--text);font-size:12.5px;padding:7px 14px;width:190px;max-width:30vw;outline:none;}',
    '.hall-search:focus{border-color:var(--lavender);}',
    '.hall-tabs{display:flex;gap:4px;padding:8px 20px 0;border-bottom:1px solid var(--surface1);flex:none;}',
    '.htab{background:none;border:none;color:var(--subtext);font-size:13px;font-weight:600;cursor:pointer;padding:8px 14px;border-radius:8px 8px 0 0;border-bottom:2px solid transparent;}',
    '.htab:hover{color:var(--text);}',
    '.htab.on{color:var(--lavender);border-bottom-color:var(--lavender);background:rgba(182,146,230,.08);}',
    '.hall-body{flex:1;display:grid;grid-template-columns:1fr 260px;min-height:0;}',
    '.hall-main{overflow-y:auto;padding:18px 20px 28px;min-width:0;}',
    '.hall-rail{overflow-y:auto;border-left:1px solid var(--surface1);background:rgba(0,0,0,.16);padding:0;display:flex;flex-direction:column;min-height:0;}',
    '.rail-scroll{flex:1;min-height:0;overflow-y:auto;padding:16px 15px;display:flex;flex-direction:column;gap:18px;}',
    '.rail-pinned{flex:none;padding:13px 15px;border-top:1px solid var(--surface1);}',
    '.ach-hall .ach-grid{margin-top:0;}',
    '.hall-sec-h{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.09em;color:var(--overlay0);margin:0 0 11px;}',
    '.hall-sec-h .cnt{margin-left:6px;font-weight:500;color:var(--overlay0);text-transform:none;letter-spacing:normal;}',
    '.hall-block{margin-bottom:26px;}',
    '.hall-recent{display:flex;flex-direction:column;gap:8px;}',
    '.hall-recent .rrow{display:flex;align-items:center;gap:11px;background:var(--surface0);border:1px solid var(--surface1);border-radius:10px;padding:9px 12px;}',
    '.hall-recent .rrow img{width:38px;height:38px;border-radius:8px;object-fit:cover;flex:none;}',
    '.hall-recent .rrow .rt{flex:1;min-width:0;}',
    '.hall-recent .rrow .rn{font-size:13px;font-weight:650;color:var(--text);}',
    '.hall-recent .rrow .rd{font-size:10.5px;color:var(--overlay0);margin-top:1px;}',
    '.hall-recent .rrow .rp{font-size:11px;font-weight:700;color:var(--gold);font-variant-numeric:tabular-nums;flex:none;}',
    '.hall-prog{display:flex;flex-direction:column;gap:11px;padding:11px;border-radius:10px;background:rgba(0,0,0,.14);border:1px solid var(--surface1);}',
    '.prow{display:flex;align-items:center;gap:11px;font-size:12px;}',
    '.prow .pl{width:150px;color:var(--subtext);flex:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.prow .pbar{flex:1;height:6px;border-radius:5px;background:var(--surface1);overflow:hidden;}',
    '.prow .pbar i{display:block;height:100%;background:linear-gradient(90deg,var(--lavender),var(--emerald,#4fc99a));border-radius:5px;transition:width .5s;}',
    '.prow .pv{width:52px;text-align:right;color:var(--overlay0);font-variant-numeric:tabular-nums;flex:none;}',
    '.rail-h{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--overlay0);margin:0 0 9px;}',
    '.rail-nav{display:flex;flex-direction:column;gap:2px;}',
    '.rail-nav a{font-size:12.5px;color:var(--subtext);text-decoration:none;padding:7px 9px;border-radius:7px;display:flex;justify-content:space-between;cursor:pointer;border:1px solid transparent;}',
    '.rail-nav a:hover{background:var(--surface0);color:var(--text);}',
    '.rail-nav a.on{background:rgba(91,61,158,.22);border-color:rgba(91,61,158,.4);color:var(--lavender);}',
    '.rail-nav a .c{color:var(--overlay0);font-variant-numeric:tabular-nums;}',
    '.rail-div{height:1px;margin:2px 0;background:linear-gradient(90deg,transparent,rgba(182,146,230,.55) 30%,rgba(182,146,230,.75) 50%,rgba(182,146,230,.55) 70%,transparent);box-shadow:0 0 8px rgba(182,146,230,.35);flex:none;}',
    '.rail-mascot{text-align:center;}',
    '.rail-mascot img{width:100%;max-width:180px;filter:drop-shadow(0 6px 16px rgba(120,60,200,.3));}',
    '.rail-mascot .bubble{font-size:11.5px;font-style:italic;color:var(--subtext);background:var(--surface0);border:1px solid var(--surface1);border-radius:10px;padding:7px 11px;margin-top:4px;line-height:1.4;text-align:center;}',
    '.rail-reach .rc{display:flex;align-items:center;gap:9px;margin-bottom:10px;}',
    '.rail-reach .rc:last-child{margin-bottom:0;}',
    '.rail-reach .rc .ri{width:30px;height:30px;flex:none;display:flex;align-items:center;justify-content:center;font-size:17px;position:relative;filter:grayscale(1) brightness(.85);}',
    '.rail-reach .rc .ri img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;}',
    '.rail-reach .rc .rb{flex:1;min-width:0;}',
    '.rail-reach .rc .rbn{font-size:11.5px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.rail-reach .rc .rbar{height:5px;border-radius:3px;background:var(--surface1);margin-top:4px;overflow:hidden;}',
    '.rail-reach .rc .rbar i{display:block;height:100%;background:linear-gradient(90deg,#7b3fbf,#c060e8);}',
    '.rail-reach .rc .rbp{font-size:9.5px;color:var(--overlay0);margin-top:2px;font-variant-numeric:tabular-nums;}',
    '.rail-rewards{display:flex;flex-wrap:wrap;gap:7px;}',
    '.rail-rewards .chip{font-size:11px;color:var(--gold);border:1px solid #6b5330;background:rgba(230,200,120,.1);border-radius:999px;padding:4px 10px;}',
    '.rail-foot{font-size:11px;color:var(--overlay0);line-height:1.5;text-align:center;}',
    '.rail-foot a{color:var(--lavender);}',
    // ---- Relics (read-only skins display; picking a skin still lives in the Control Panel,
    // that decision is unchanged -- these rows are informational, no onclick) ----
    '.hall-relics{display:flex;flex-direction:column;gap:2px;}',
    '.relic-row{display:flex;align-items:center;gap:7px;padding:6px 8px;border-radius:8px;border:1px solid var(--surface1);background:rgba(0,0,0,.18);opacity:.5;}',
    '.relic-row.unlocked{opacity:1;}',
    '.relic-row.active{border-color:rgba(155,128,198,.6);background:rgba(91,61,158,.14);}',
    '.relic-row .rsw{display:flex;gap:2px;flex:none;}',
    '.relic-row .rsw i{width:9px;height:9px;border-radius:2px;}',
    '.relic-row .rnm{font-size:12px;font-weight:600;color:var(--subtext);flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.relic-row.active .rnm,.relic-row.unlocked .rnm{color:var(--text);}',
    '.relic-row .rck{color:var(--lavender);font-size:12px;flex:none;}',
    '.relic-row .rlk{color:var(--overlay0);font-size:11px;flex:none;}',
    // ---- Statistics tab: summary cards + by-rarity + ladder-completion breakdowns ----
    '.hall-statcards{display:grid;grid-template-columns:repeat(3,1fr);gap:11px;margin-bottom:22px;}',
    '.hall-statcard{padding:13px 14px;border-radius:11px;background:var(--surface0);border:1px solid var(--surface1);}',
    '.hall-statcard .scl{font-size:11px;color:var(--overlay0);text-transform:uppercase;letter-spacing:.05em;}',
    '.hall-statcard .scv{font-size:21px;font-weight:700;color:var(--text);line-height:1.25;margin-top:2px;font-variant-numeric:tabular-nums;}',
    '.hall-statcard .scs{font-size:11.5px;color:var(--subtext);margin-top:2px;}',
    '.hall-rarity-row{display:flex;align-items:center;gap:11px;margin-bottom:9px;}',
    '.hall-rarity-row .rl{width:76px;flex:none;font-size:12px;text-transform:capitalize;}',
    '.hall-rarity-row .rbar{flex:1;height:5px;border-radius:3px;background:var(--surface1);overflow:hidden;}',
    '.hall-rarity-row .rbar i{display:block;height:100%;border-radius:3px;transition:width .5s;}',
    '.hall-rarity-row .rv{width:44px;text-align:right;color:var(--overlay0);font-size:12px;font-variant-numeric:tabular-nums;flex:none;}',
    '.hall-ladder-row{display:flex;align-items:center;gap:11px;margin-bottom:7px;}',
    '.hall-ladder-row img{width:19px;height:19px;border-radius:5px;object-fit:cover;flex:none;opacity:.75;}',
    '.hall-ladder-row .ll{width:158px;flex:none;font-size:12px;color:var(--subtext);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.hall-ladder-row .lbar{flex:1;height:4px;border-radius:3px;background:var(--surface1);overflow:hidden;}',
    '.hall-ladder-row .lbar i{display:block;height:100%;background:linear-gradient(90deg,#5b3d9e,#9b59b6);border-radius:3px;}',
    '.hall-ladder-row .lv{width:40px;text-align:right;color:var(--overlay0);font-size:12px;font-variant-numeric:tabular-nums;flex:none;}',
    // ---- Ladder tier-triad tokens, scoped to the Hall (kept separate from .ach-m2's own
    // copy on purpose -- see the top-of-block note) ----
    '.ach-hall .t-common{--tc:#9fbad6;--tcl:#dbe8f5;--tcd:#5f7c9e;}',
    '.ach-hall .t-rare{--tc:#7fb0f4;--tcl:#d2e4ff;--tcd:#4a72b8;}',
    '.ach-hall .t-epic{--tc:#c69cff;--tcl:#ead9ff;--tcd:#8a5cc4;}',
    '.ach-hall .t-legendary{--tc:#e8cb7c;--tcl:#fff4d1;--tcd:#b3924a;}',
    '.ach-hall .t-feat{--tc:var(--ruby,#e0355e);--tcl:#f6b8c9;--tcd:var(--ruby-deep,#a11238);}',
    // ---- Ladder badges (the selector row above the tier grid) ----
    '.hall-ladders{display:grid;grid-template-columns:repeat(5,1fr);gap:11px;}',
    '.ladder-badge{cursor:pointer;user-select:none;display:flex;flex-direction:column;align-items:center;gap:5px;}',
    '.ladder-badge .lb-img{position:relative;width:100%;aspect-ratio:1/1;border-radius:13px;overflow:hidden;transition:outline-color .15s,box-shadow .15s;outline:2px solid transparent;outline-offset:2px;}',
    '.ladder-badge .lb-img img{width:100%;height:100%;object-fit:cover;transition:transform .18s;}',
    '.ladder-badge:hover .lb-img img{transform:scale(1.08);}',
    '.ladder-badge.zero .lb-img{filter:grayscale(.75) brightness(.45);}',
    '.ladder-badge.on .lb-img{outline-color:var(--tc);box-shadow:0 0 16px -2px var(--tc);}',
    '.ladder-badge .lb-pips{display:flex;gap:2px;}',
    '.ladder-badge .lb-pips i{width:5px;height:5px;border-radius:50%;background:var(--surface1);}',
    '.ladder-badge .lb-name{font-size:12.5px;text-align:center;color:var(--subtext);line-height:1.2;}',
    '.ladder-badge.on .lb-name{color:var(--lavender);}',
    // ---- The carousel (auto-rotating showcase for the active ladder) ----
    '.hall-carousel{position:relative;border-radius:15px;overflow:hidden;background:linear-gradient(135deg,var(--surface0) 0%,var(--mantle) 100%);border:1px solid var(--surface1);box-shadow:0 12px 34px rgba(0,0,0,.4);margin-bottom:22px;}',
    '.hall-carousel::before{content:"";position:absolute;top:0;left:0;right:0;height:5px;background:linear-gradient(90deg,transparent,var(--tc) 22%,var(--tcl) 50%,var(--tc) 78%,transparent);z-index:1;transition:background .5s;}',
    '.hc-row{display:flex;min-height:150px;}',
    '.hc-cap{position:relative;flex:none;width:108px;display:flex;align-items:center;justify-content:center;border-right:1px solid var(--surface1);background:radial-gradient(ellipse 110% 80% at 50% 110%,color-mix(in srgb, var(--tc) 16%, transparent) 0%,transparent 65%);transition:background .5s;}',
    '.hc-cap .hc-float{position:relative;animation:hc-float 4s ease-in-out infinite;}',
    '@keyframes hc-float{0%,100%{transform:translateY(0);}50%{transform:translateY(-7px);}}',
    '.hc-ring{position:absolute;inset:0;margin:auto;width:88px;height:88px;border-radius:50%;box-shadow:0 0 0 3px var(--tc),0 0 18px var(--tc);opacity:.7;transition:box-shadow .5s;}',
    '.hc-badge{width:88px;height:88px;border-radius:14px;overflow:hidden;filter:drop-shadow(0 0 10px var(--tc));}',
    '.hc-badge img{width:100%;height:100%;object-fit:cover;}',
    '.hc-cap.zero .hc-ring{box-shadow:0 0 0 3px rgba(58,52,96,.6);opacity:1;}',
    '.hc-cap.zero .hc-badge{filter:grayscale(.75) brightness(.4);}',
    '.hc-body{flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center;padding:16px 18px;gap:5px;}',
    '.hc-eyebrow{font-size:12.5px;font-weight:700;text-transform:uppercase;letter-spacing:.18em;color:var(--tc);transition:color .4s;}',
    '.hc-name{font:700 21px/1.1 Georgia,"Times New Roman",serif;color:var(--text);}',
    '.hc-desc{font-size:12.5px;font-style:italic;color:var(--subtext);max-width:420px;line-height:1.4;}',
    '.hc-meta{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin-top:2px;}',
    '.hc-tierpill{font:800 11px/1 sans-serif;text-transform:uppercase;letter-spacing:.07em;padding:3px 9px;border-radius:6px;color:#241c10;background:linear-gradient(180deg,var(--tcl),var(--tc) 50%,var(--tcd));}',
    '.ach-hall .t-feat .hc-tierpill{background:linear-gradient(180deg,#c7ccd6,var(--gunmetal,#8a93a2) 50%,var(--gunmetal-deep,#4a515c));color:#171a20;}',
    '.hc-ptspill{font-size:11.5px;color:var(--gold);background:rgba(230,200,120,.1);border:1px solid #6b5330;border-radius:7px;padding:3px 9px;}',
    '.hc-thresh{font-size:11px;color:var(--overlay0);}',
    '.hc-nav{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;padding-right:14px;flex:none;}',
    '.hc-nav button{width:26px;height:26px;border-radius:50%;background:var(--surface0);border:1px solid var(--surface1);color:var(--subtext);cursor:pointer;display:flex;align-items:center;justify-content:center;}',
    '.hc-nav button:hover{filter:brightness(1.3);color:var(--text);}',
    '.hc-pips{display:flex;gap:5px;padding:9px 18px;border-top:1px solid var(--surface1);}',
    '.hc-pips button{width:6px;height:6px;padding:0;border-radius:999px;border:none;cursor:pointer;background:var(--surface1);transition:width .2s,background .2s;}',
    '.hc-pips button.on{width:16px;background:var(--tc);}',
    '.hc-pips button.done{background:color-mix(in srgb, var(--tc) 45%, var(--surface1));}',
    '@media (prefers-reduced-motion: reduce){ .hc-cap .hc-float{animation:none;} }',
    // ---- Glowing pill section divider (ladder groups inside "All Ladder Tiers", plus the
    // Milestones/Masteries/Feats headers) ----
    '.hall-pilldiv{display:flex;align-items:center;gap:9px;margin:0 0 12px;}',
    '.hall-pilldiv .pd-line{height:1px;flex:1;background:linear-gradient(90deg,transparent,rgba(182,146,230,.5));box-shadow:0 0 6px rgba(182,146,230,.3);}',
    '.hall-pilldiv .pd-line.r{background:linear-gradient(90deg,rgba(182,146,230,.5),transparent);}',
    '.hall-pilldiv .pd-pill{display:flex;align-items:center;gap:6px;padding:5px 12px;border-radius:999px;background:linear-gradient(180deg,#4a3f72 0%,#2e2454 50%,#1e1840 100%);border:1px solid rgba(182,146,230,.35);box-shadow:0 0 10px rgba(182,146,230,.2),inset 0 1px 0 rgba(255,255,255,.08);white-space:nowrap;}',
    '.hall-pilldiv .pd-pill img{width:14px;height:14px;border-radius:4px;object-fit:cover;opacity:.85;}',
    '.hall-pilldiv .pd-pill .pd-nm{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#b692e6;}',
    '.hall-pilldiv .pd-pill .pd-ct{font-size:12.5px;color:rgba(182,146,230,.5);}',
    '.hall-pilldiv.feats .pd-pill .pd-nm{color:var(--ruby);}',
    // ---- Tier / milestone / mastery / feat cards ----
    '.hall-cardgrid{display:grid;grid-template-columns:1fr 1fr;gap:11px;}',
    '.hall-card{position:relative;display:flex;align-items:center;gap:11px;padding:12px;border-radius:11px;background:rgba(28,18,50,.5);border:1px solid var(--surface1);min-height:70px;transition:background .12s,box-shadow .12s;}',
    '.hall-card:hover{background:rgba(44,30,72,.5);}',
    '.hall-card.locked{opacity:.7;}',
    '.hall-card.earned{box-shadow:0 0 14px -4px var(--tc);}',
    '.hall-card.framed{border:none;}',
    '.hall-card .hcd-ico{position:relative;flex:none;width:42px;height:42px;border-radius:10px;overflow:hidden;filter:grayscale(1) brightness(.75);display:flex;align-items:center;justify-content:center;font-size:22px;background:color-mix(in srgb, var(--tc) 12%, transparent);border:1px solid color-mix(in srgb, var(--tc) 25%, transparent);}',
    '.hall-card.earned .hcd-ico{filter:none;}',
    // .hcd-badge OVERLAYS the emoji text above (position:absolute) rather than sitting next
    // to it -- a successful load fully covers the emoji; onerror="this.remove()" (a plain,
    // non-interpolated attribute -- see card()'s comment) reveals it underneath for free.
    '.hall-card .hcd-ico .hcd-badge{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:10px;}',
    '.hall-card .hcd-body{flex:1;min-width:0;}',
    '.hall-card .hcd-top{display:flex;align-items:center;gap:6px;}',
    '.hall-card .hcd-nm{font-size:13.5px;font-weight:650;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.hall-card .hcd-ds{font-size:12px;color:var(--subtext);line-height:1.35;margin-top:1px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;}',
    '.hall-card .hcd-sub{font-size:11px;color:var(--overlay0);margin-top:2px;}',
    '.hall-card .hcd-side{flex:none;text-align:right;}',
    '.hall-card .hcd-pts{font-size:11.5px;font-weight:650;border-radius:999px;padding:2px 8px;margin-bottom:3px;background:rgba(60,43,99,.6);color:#9b80c6;}',
    '.hall-card .hcd-date{font-size:11px;color:var(--overlay0);}',
    '.hall-tierpill-mini{font:800 10px/1 sans-serif;text-transform:uppercase;letter-spacing:.08em;padding:2px 7px;border-radius:999px;color:#1a1530;background:linear-gradient(180deg,var(--tcl) 0%,var(--tc) 50%,var(--tcd) 100%);box-shadow:0 0 6px color-mix(in srgb, var(--tc) 40%, transparent);flex:none;}',
    '.ach-hall .t-feat .hall-tierpill-mini{background:linear-gradient(180deg,#c7ccd6 0%,#8a93a2 50%,#4a515c 100%);}',
    '.hall-card.hidden-feat .hcd-nm{color:var(--overlay0);}',
    '.hall-card.hidden-feat .hcd-ds{color:#3e3459;}',
    '.hall-card.hidden-feat .hcd-ico{filter:none;background:rgba(25,16,42,.8);border:1px solid var(--surface1);}',
    '.hall-card .hcd-crit{display:flex;flex-wrap:wrap;gap:4px 10px;margin-top:5px;}',
    '.hall-card .hcd-crit span{font-size:10px;color:var(--overlay0);display:inline-flex;align-items:center;gap:3px;white-space:nowrap;}',
    '.hall-card .hcd-crit span.on{color:var(--emerald,#7ee0a8);font-weight:600;}',
    '.hall-card .hcd-bar{height:5px;border-radius:3px;background:var(--surface1);margin-top:6px;overflow:hidden;}',
    '.hall-card .hcd-bar i{display:block;height:100%;background:var(--accent);border-radius:3px;}',
    '.hall-card .hcd-bar+.hcd-num{font-size:10px;color:var(--overlay0);margin-top:2px;font-variant-numeric:tabular-nums;}',
    '.hall-card .hcd-roast{grid-column:1/-1;font-size:10.5px;color:#c9b8e6;line-height:1.4;margin-top:6px;padding:5px 8px;background:rgba(182,146,230,.07);border-left:2px solid var(--lavender);border-radius:0 7px 7px 0;font-style:italic;}',
    '.hall-card .hcd-bannerflag{font-size:10px;color:var(--gold);margin-top:4px;}',
    // 9-slice frame overlay for legendary/feat CARDS (same technique + real served frame
    // assets the unlock toast already uses -- see .ach-m2 .t-legendary .tframe below --
    // extending it to grid tiles was an explicit, decided change from the prior "toast only"
    // behavior, per the 2026-07-22 redesign).
    '.hall-frame{position:absolute;inset:-5px;pointer-events:none;z-index:2;border-style:solid;border-color:transparent;}',
    '.hall-frame.legendary{border-width:16px 14px;border-image-source:url(/branding/frames/legendary.png);border-image-slice:16.8% 13.3% 16.8% 13%;border-image-outset:0;}',
    '.hall-frame.feat{border-width:16px 13px;border-image-source:url(/branding/frames/feat.png);border-image-slice:15.8% 10.3% 16.8% 10%;border-image-outset:0;}',
    // ---- Section collapse chevron (reused on the ladder-groups + milestone/mastery/feat
    // pill dividers, and the classic Evolution Ladders flat section for the "All" view) ----
    '.ach-hall .ach-sect{cursor:pointer;user-select:none;}',
    '.ach-hall .ach-sect .chev{margin-left:auto;color:var(--overlay0);font-size:11px;transition:transform .15s;}',
    '.ach-hall .ach-sect.collapsed .chev{transform:rotate(-90deg);}',
    '.hall-empty{color:var(--overlay0);font-size:12px;font-style:italic;padding:8px 0;}',
    '@media(max-width:860px){ .ach-hall.open{padding:0;} .ach-hall .ach-panel{width:100vw;height:100vh;max-height:none;border-radius:0;} .hall-body{grid-template-columns:1fr;} .hall-rail{border-left:none;border-top:1px solid var(--surface1);} .hall-search{width:120px;} .hall-cardgrid,.hall-ladders{grid-template-columns:repeat(2,1fr);} .hall-statcards{grid-template-columns:1fr;} .hc-row{flex-direction:column;} .hc-cap{width:100%;border-right:none;border-bottom:1px solid var(--surface1);padding:14px 0;} .hc-nav{display:none;} }',
    '.ach-bannerflag{font-size:10px;color:var(--gold);margin-top:4px;}',
    // ---- toast v2 (the LOCKED design, artifact 335ef4e7) -- z-index raised 430->520 (see
    // top-of-file comment) so it always renders above the Loom's own full-screen overlays.
    // font-family stated explicitly for the same reason as #ach-modal above and
    // #jobs-fab/#jobs-tray/#mg-toasts below -- this is the achievement celebration's own root,
    // and without it the toast inherits nothing on /loom (_LOOM_SHELL's body sets no font).
    '.ach-m2{position:fixed;inset:0;z-index:520;display:flex;align-items:center;justify-content:center;background:rgba(8,6,16,.78);opacity:0;transition:opacity .35s;padding:20px;font-family:system-ui,sans-serif;}',
    '.ach-m2.go{opacity:1;}',
    '.ach-m2.out{opacity:0;transition:opacity .5s;}',
    '.ach-m2 .tstage{width:min(680px,94vw);}',
    '.ach-m2 .tw{position:relative;padding-top:158px;cursor:pointer;}',
    '.ach-m2 .t-common{--tc:#9fbad6;--tcl:#dbe8f5;--tcd:#5f7c9e;}',
    '.ach-m2 .t-rare{--tc:#7fb0f4;--tcl:#d2e4ff;--tcd:#4a72b8;}',
    '.ach-m2 .t-epic{--tc:#c69cff;--tcl:#ead9ff;--tcd:#8a5cc4;}',
    '.ach-m2 .t-legendary{--tc:#e8cb7c;--tcl:#fff4d1;--tcd:#b3924a;}',
    '.ach-m2 .t-feat{--tc:var(--ruby,#e0355e);--tcl:#f6b8c9;--tcd:var(--ruby-deep,#a11238);}',
    '.ach-m2 .mglow{position:absolute;top:6px;right:0;width:250px;height:190px;z-index:1;pointer-events:none;background:radial-gradient(ellipse at 60% 55%,var(--tc),transparent 66%);filter:blur(22px);opacity:0;}',
    '.ach-m2 .tw.go .mglow{animation:m2gfade .7s ease 1.3s forwards;}',
    '@keyframes m2gfade{to{opacity:.55;}}',
    '.ach-m2 .mascot{position:absolute;top:0;right:26px;height:206px;z-index:2;transform-origin:bottom center;filter:drop-shadow(0 12px 16px rgba(0,0,0,.55));opacity:0;transform:translateY(96px) scale(.9);}',
    '.ach-m2 .tw.go .mascot{animation:m2pop .66s cubic-bezier(.16,.86,.28,1.32) 1.32s forwards;}',
    '@keyframes m2pop{0%{opacity:0;transform:translateY(96px) scale(.9);}62%{opacity:1;transform:translateY(-10px) scale(1.03);}100%{opacity:1;transform:translateY(0) scale(1);}}',
    '.ach-m2 .toast{position:relative;z-index:3;background:linear-gradient(180deg,rgba(42,36,63,.94),rgba(24,21,38,.97));backdrop-filter:blur(8px);border:1px solid #37314f;border-radius:16px;padding:17px 20px 16px;display:flex;gap:16px;align-items:center;box-shadow:0 24px 54px -18px rgba(0,0,0,.72);opacity:0;transform:translateY(14px);}',
    '.ach-m2 .tw.go .toast{animation:m2rise .5s ease forwards;}',
    '@keyframes m2rise{to{opacity:1;transform:none;}}',
    '.ach-m2 .toast::before{content:"";position:absolute;left:0;right:0;top:0;height:6px;border-radius:16px 16px 0 0;background:linear-gradient(90deg,transparent,var(--tc) 22%,var(--tcl) 50%,var(--tc) 78%,transparent);box-shadow:0 0 20px 2px var(--tc);opacity:.95;}',
    '.ach-m2 .t-feat .toast::before{background:linear-gradient(90deg,transparent,var(--gunmetal,#8a93a2) 22%,#c7ccd6 50%,var(--gunmetal,#8a93a2) 78%,transparent);}',
    '.ach-m2 .cap{position:relative;flex:0 0 auto;width:118px;align-self:stretch;display:flex;align-items:center;justify-content:center;margin:-17px 16px -16px -20px;border-radius:16px 0 0 16px;border-right:1px solid rgba(255,255,255,.09);background:linear-gradient(180deg,rgba(255,255,255,.05),rgba(0,0,0,.14));box-shadow:inset 0 0 30px -6px var(--tc);}',
    '.ach-m2 .t-feat .cap{box-shadow:inset 0 0 30px -6px var(--tc),inset 0 0 0 1px rgba(224,53,94,.4);}',
    '.ach-m2 .badge{width:100px;height:100px;object-fit:contain;filter:drop-shadow(0 5px 12px rgba(0,0,0,.5));opacity:0;transform:translateX(255px) scale(.82);}',
    '.ach-m2 .badge.emoji{display:flex;align-items:center;justify-content:center;font-size:64px;line-height:1;}',
    '.ach-m2 .tw.go .badge{animation:m2sweep .62s cubic-bezier(.15,.82,.28,1.24) .15s forwards, m2bding .5s ease .74s;}',
    '@keyframes m2sweep{0%{opacity:0;transform:translateX(255px) scale(.82);}70%{opacity:1;transform:translateX(-11px) scale(1.06);}100%{opacity:1;transform:translateX(0) scale(1);}}',
    '@keyframes m2bding{0%{filter:drop-shadow(0 5px 12px rgba(0,0,0,.5)) brightness(1);}26%{filter:drop-shadow(0 0 14px var(--tc)) brightness(1.65);}100%{filter:drop-shadow(0 5px 12px rgba(0,0,0,.5)) brightness(1);}}',
    '.ach-m2 .ring{position:absolute;width:96px;height:96px;border-radius:50%;border:3px solid var(--tc);opacity:0;transform:scale(.4);pointer-events:none;}',
    '.ach-m2 .tw.go .ring{animation:m2ring .6s ease-out .76s;}',
    '@keyframes m2ring{0%{opacity:0;transform:scale(.4);}22%{opacity:.85;}100%{opacity:0;transform:scale(1.75);}}',
    '.ach-m2 .tbody{min-width:0;flex:1;}',
    '.ach-m2 .tbody .u{font:700 10px/1 sans-serif;letter-spacing:.22em;text-transform:uppercase;color:var(--tc);opacity:0;}',
    '.ach-m2 .tw.go .tbody .u{animation:m2fade .4s ease .86s forwards;}',
    '.ach-m2 .tbody .n{font:700 22px/1.08 Georgia,serif;margin:3px 0 5px;opacity:0;color:var(--text);}',
    '.ach-m2 .tw.go .tbody .n{animation:m2fade .42s ease .98s forwards;}',
    '.ach-m2 .tbody .r{font-size:13px;line-height:1.5;font-style:italic;opacity:0;margin-top:1px;background:linear-gradient(90deg,#b3a2dc 0%,#b3a2dc 43%,#efe6ff 50%,#b3a2dc 57%,#b3a2dc 100%);background-size:235% 100%;background-position:118% 0;-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:transparent;filter:drop-shadow(0 0 5px rgba(198,180,255,.22));}',
    '.ach-m2 .tw.go .tbody .r{animation:m2fade .46s ease 1.1s forwards, m2readalong 4.8s ease-in-out 1.6s infinite;}',
    '@keyframes m2readalong{0%{background-position:118% 0;}52%{background-position:-18% 0;}100%{background-position:-18% 0;}}',
    '@keyframes m2fade{from{opacity:0;transform:translateY(5px);}to{opacity:1;transform:none;}}',
    '.ach-m2 .tier-pill{position:relative;display:inline-block;margin-top:8px;font:800 9px/1 sans-serif;letter-spacing:.09em;text-transform:uppercase;color:#241c10;padding:3px 11px;border-radius:999px;overflow:hidden;background:linear-gradient(180deg,var(--tcl),var(--tc) 46%,var(--tcd));border:1px solid var(--tcl);box-shadow:inset 0 1px 0 rgba(255,255,255,.6),0 0 11px -1px var(--tc);text-shadow:0 1px 0 rgba(255,255,255,.35);opacity:0;}',
    '.ach-m2 .t-feat .tier-pill{background:linear-gradient(180deg,#c7ccd6,var(--gunmetal,#8a93a2) 46%,var(--gunmetal-deep,#4a515c));border-color:#c7ccd6;color:#171a20;box-shadow:inset 0 1px 0 rgba(255,255,255,.6),0 0 11px -1px var(--tc);}',
    '.ach-m2 .tw.go .tier-pill{animation:m2fade .4s ease 1.22s forwards;}',
    '.ach-m2 .tier-pill::after{content:"";position:absolute;top:0;left:-60%;width:45%;height:100%;background:linear-gradient(100deg,transparent,rgba(255,255,255,.75),transparent);transform:skewX(-18deg);}',
    '.ach-m2 .tw.go .tier-pill::after{animation:m2sheen 2.6s ease-in-out 1.6s infinite;}',
    '@keyframes m2sheen{0%{left:-60%;}30%{left:130%;}100%{left:130%;}}',
    '.ach-m2 .rwd{display:inline-block;margin:8px 0 0 8px;font-size:11px;color:var(--gold);border:1px solid #6b5330;background:rgba(230,200,120,.1);border-radius:7px;padding:3px 9px;opacity:0;}',
    '.ach-m2 .tw.go .rwd{animation:m2fade .4s ease 1.34s forwards;}',
    '.m2-conf{position:fixed;top:-3vh;width:7px;height:14px;border-radius:2px;z-index:521;pointer-events:none;animation:m2conffall linear forwards;}',
    '@keyframes m2conffall{to{transform:translateY(112vh) rotate(720deg);opacity:.5;}}',
    '.ach-m2 .flash{position:absolute;inset:0;border-radius:16px;pointer-events:none;opacity:0;background:radial-gradient(circle at 74% -4%,rgba(255,242,206,.9),transparent 58%);}',
    '.ach-m2 .t-feat .flash{background:radial-gradient(circle at 74% -4%,rgba(255,214,226,.9),transparent 58%);}',
    '.ach-m2 .tw.go.t-legendary .flash,.ach-m2 .tw.go.t-feat .flash{animation:m2flash .9s ease-out 1.3s;}',
    '@keyframes m2flash{0%{opacity:0;}20%{opacity:.92;}100%{opacity:0;}}',
    '@media (prefers-reduced-motion: reduce){ .ach-m2 *{animation:none!important;} .ach-m2 .toast,.ach-m2 .badge,.ach-m2 .mascot,.ach-m2 .mglow,.ach-m2 .tbody .u,.ach-m2 .tbody .n,.ach-m2 .tbody .r,.ach-m2 .tier-pill{opacity:1!important;transform:none!important;} }',
    '.ach-m2 .tframe{position:relative;z-index:3;}',
    '.ach-m2 .t-legendary .tframe,.ach-m2 .t-feat .tframe{border-style:solid;border-image-repeat:stretch;opacity:0;transform:translateY(14px);}',
    '.ach-m2 .tw.go.t-legendary .tframe,.ach-m2 .tw.go.t-feat .tframe{animation:m2rise .5s ease forwards;}',
    '.ach-m2 .t-legendary .tframe{border-width:46px 44px;border-image-source:url(/branding/frames/legendary.png);border-image-slice:16.8% 13.3% 16.8% 13%;border-image-outset:6px;}',
    '.ach-m2 .t-feat .tframe{border-width:46px 38px;border-image-source:url(/branding/frames/feat.png);border-image-slice:15.8% 10.3% 16.8% 10%;border-image-outset:6px;}',
    '.ach-m2 .t-legendary .tframe .toast,.ach-m2 .t-feat .tframe .toast{border-color:transparent;box-shadow:none;opacity:1;transform:none;animation:none;}',
    '.ach-m2 .rwd .giftbox{height:15px;width:15px;object-fit:contain;vertical-align:-3px;margin-right:5px;}',
    '.ach-m2 .pts-pill{display:inline-block;margin:8px 0 0 8px;font:800 9px/1 sans-serif;letter-spacing:.06em;color:var(--gold,#e0c268);border:1px solid #6b5330;background:rgba(230,200,120,.12);border-radius:999px;padding:3px 9px;vertical-align:middle;opacity:0;}',
    '.ach-m2 .tw.go .pts-pill{animation:m2fade .4s ease 1.26s forwards;}',
    '@media (prefers-reduced-motion: reduce){ .ach-m2 .pts-pill{opacity:1!important;} }',
    '.ach-card .ach-pts{display:inline-block;margin-left:6px;font:700 10px/1 sans-serif;color:var(--gold,#e0c268);border:1px solid #6b5330;background:rgba(230,200,120,.1);border-radius:6px;padding:2px 6px;vertical-align:middle;}',
    '@media (prefers-reduced-motion: reduce){ .ach-m2 .tframe{opacity:1!important;transform:none!important;} }',
    // ---- Jobs card: the activity tracker (bottom-left, always openable) ----
    // Each of these three roots states its own font-family, and that is load-bearing rather
    // than belt-and-braces. They set font-SIZE but used to inherit font-FAMILY from the host
    // page, and the two hosts do not agree: the gallery's BASE_HTML body says
    // `font-family: system-ui, sans-serif`, while _LOOM_SHELL's body sets only background and
    // margin. #jobs-fab / #jobs-tray / #mg-toasts are siblings of #root in that shell, so on
    // /loom they inherited nothing and fell back to the browser's default font -- the same
    // card, visibly different type on the two pages (owner spotted it comparing screenshots,
    // 2026-07-21). A shared component that changes appearance depending on who mounts it is
    // the bug; mg-notify is host-neutral by design, like its mg-* siblings, so it owns this.
    '#jobs-fab{position:fixed;left:14px;bottom:14px;z-index:234;display:none;align-items:center;gap:7px;background:var(--mantle);border:1px solid var(--surface1);border-radius:999px;box-shadow:0 6px 20px rgba(0,0,0,.45);color:var(--subtext);cursor:pointer;padding:7px 13px 7px 10px;font-family:system-ui,sans-serif;font-size:11.5px;letter-spacing:.02em;transition:border-color .15s,color .15s;}',
    '#jobs-fab.show{display:inline-flex;}',
    '#jobs-fab:hover{border-color:var(--lavender);color:var(--text);}',
    '#jobs-fab .jf-dot{width:8px;height:8px;border-radius:50%;background:var(--overlay0);flex:none;}',
    '#jobs-fab.busy .jf-dot{background:var(--lavender);box-shadow:0 0 9px rgba(182,146,230,.8);animation:jf-pulse 1.6s ease-in-out infinite;}',
    '#jobs-fab .jf-badge{background:var(--lavender);color:var(--base);border-radius:999px;font-size:10px;font-weight:700;padding:1px 6px;min-width:15px;text-align:center;display:none;}',
    '#jobs-fab.busy .jf-badge{display:inline-block;}',
    '@keyframes jf-pulse{0%,100%{opacity:.5;}50%{opacity:1;}}',
    '#jobs-tray{position:fixed;left:14px;bottom:14px;z-index:235;width:366px;min-width:260px;max-width:min(560px, calc(100vw - 28px));max-height:min(74vh,600px);display:none;flex-direction:column;overflow:hidden;resize:both;background:var(--mantle);border:1px solid var(--surface1);border-radius:12px;box-shadow:0 14px 40px rgba(0,0,0,.55);font-family:system-ui,sans-serif;}',
    '#jobs-tray.open{display:flex;}',
    '#jobs-tray .jt-head{display:flex;align-items:center;gap:6px;padding:9px 11px;border-bottom:1px solid var(--surface0);background:linear-gradient(180deg,var(--surface0),transparent);}',
    '#jobs-tray .jt-title{font-size:11px;text-transform:uppercase;letter-spacing:.11em;color:var(--lavender);font-weight:700;flex:1;display:flex;align-items:center;gap:7px;}',
    '#jobs-tray .jt-count{color:var(--overlay0);font-weight:600;letter-spacing:.03em;}',
    '#jobs-tray .jt-hbtn{background:none;border:none;color:var(--overlay0);cursor:pointer;font-size:11px;padding:3px 7px;border-radius:6px;}',
    '#jobs-tray .jt-hbtn:hover{color:var(--text);background:var(--surface1);}',
    '#jobs-tray .jt-body{overflow:auto;padding:6px;flex:1;}',
    '.jt-empty{color:var(--overlay0);font-size:12px;text-align:center;padding:30px 16px;line-height:1.55;}',
    '.jt-item{display:flex;align-items:flex-start;gap:9px;font-size:12px;color:var(--text);padding:8px;border-radius:8px;}',
    '.jt-item + .jt-item{margin-top:1px;}',
    '.jt-item:hover{background:var(--surface0);}',
    '.jt-item.st-failed{background:rgba(243,139,168,.09);}',
    '.jt-item.st-warn{background:rgba(250,179,135,.09);}',
    '.jt-ic{flex:none;width:34px;height:34px;display:flex;align-items:center;justify-content:center;margin-top:1px;position:relative;}',
    '.jt-ic .gen-moon{margin:0;}',
    '.jt-glyph{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;}',
    '.jt-ok{color:var(--emerald);font-size:15px;} .jt-err{color:var(--red);font-size:15px;} .jt-warn{color:var(--peach);font-size:15px;}',
    '.jt-nel{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;}',
    '.jt-spin{position:relative;width:48px;height:48px;}',
    '.jt-spin .jt-nel{inset:6px;width:36px;height:36px;border-radius:50%;object-fit:cover;object-position:60% 32%;animation:gen-spin 1.6s linear infinite;}',
    '.jt-spin .gen-ring{position:absolute;inset:2px;border-radius:50%;border:2px solid rgba(182,146,230,.22);border-top-color:var(--lavender);animation:gen-spin .8s linear infinite;}',
    '.jt-empty-nel{width:104px;height:104px;object-fit:contain;margin:0 auto 8px;display:block;opacity:.92;}',
    '.jt-main{flex:1;min-width:0;}',
    '.jt-lab{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.jt-sub{font-size:10.5px;margin-top:2px;display:flex;gap:8px;flex-wrap:wrap;}',
    '.jt-sub .jt-when{color:var(--overlay0);} .jt-sub .jt-kind{color:var(--subtext);text-transform:capitalize;}',
    '.jt-errmsg{color:var(--red);font-size:10.5px;margin-top:3px;white-space:normal;}',
    '.jt-bar{height:4px;border-radius:3px;background:var(--surface1);margin-top:6px;overflow:hidden;}',
    '.jt-bar i{display:block;height:100%;background:var(--lavender);border-radius:3px;transition:width .3s;}',
    '.jt-thumb{flex:none;} .jt-thumb img{width:30px;height:30px;border-radius:5px;object-fit:cover;display:block;}',
    '.jt-x{background:none;border:none;color:var(--overlay0);cursor:pointer;font-size:14px;padding:0 2px;flex:none;line-height:1;}',
    '.jt-x:hover{color:var(--red);}',
    // ---- Toasts: small, corner-stacked, reusable (job notices; achievements adopt the same
    // frame for the >3-unlock summary case). z-index raised 420->510 (see top-of-file comment).
    '#mg-toasts{position:fixed;right:16px;top:64px;z-index:510;display:flex;flex-direction:column;gap:9px;align-items:flex-end;pointer-events:none;font-family:system-ui,sans-serif;}',
    '.mg-toast{pointer-events:auto;min-width:214px;max-width:340px;display:flex;align-items:flex-start;gap:10px;background:var(--mantle);border:1px solid var(--surface1);border-left:3px solid var(--lavender);border-radius:10px;padding:11px 13px;box-shadow:0 10px 30px rgba(0,0,0,.5);animation:mg-toast-in .28s cubic-bezier(.2,.9,.3,1.2);}',
    '.mg-toast.out{animation:mg-toast-out .3s ease forwards;}',
    '.mg-toast.ok{border-left-color:var(--emerald);} .mg-toast.err{border-left-color:var(--red);}',
    '.mg-toast .mt-ic{flex:none;font-size:15px;margin-top:1px;color:var(--lavender);}',
    '.mg-toast.ok .mt-ic{color:var(--emerald);} .mg-toast.err .mt-ic{color:var(--red);}',
    '.mg-toast .mt-main{flex:1;min-width:0;}',
    '.mg-toast .mt-title{font-size:12.5px;color:var(--text);font-weight:600;}',
    '.mg-toast .mt-msg{font-size:11px;color:var(--subtext);margin-top:2px;white-space:normal;}',
    '.mg-toast .mt-thumb{width:34px;height:34px;border-radius:6px;object-fit:cover;flex:none;}',
    '.mg-toast .mt-x{background:none;border:none;color:var(--overlay0);cursor:pointer;font-size:14px;padding:0 1px;flex:none;line-height:1;}',
    '.mg-toast .mt-x:hover{color:var(--text);}',
    '@keyframes mg-toast-in{from{opacity:0;transform:translateY(-12px);}to{opacity:1;transform:translateY(0);}}',
    '@keyframes mg-toast-out{to{opacity:0;transform:translateX(20px);}}',
    '@media (prefers-reduced-motion: reduce){ #jobs-fab.busy .jf-dot{animation:none;} .mg-toast,.mg-toast.out{animation:none;} }'
  ].join('');

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = MG_CSS;
    (document.head || document.documentElement).appendChild(s);
  }
  injectStyle();

  // ================================================================================
  // Ach -- the achievement modal + toast-celebration system
  // ================================================================================
  var Ach = (function(){
    function el(id){return document.getElementById(id);}
    function esc(s){ return (s||'').replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];}); }
    function fmt(n){ return (Number(n)||0).toLocaleString(); }
    var SKIN_SW={ moonglade:['#0c0a1c','#b692e6','#4fc99a','#d4af37'],
                  nightfallen:['#0a0713','#a678f0','#7f6fe0','#d9b3ff'],
                  moonlit:['#0b1018','#8fb8e8','#68d5e0','#cfe1f5'],
                  ember:['#160c0c','#e8935f','#e0a94b','#ffcf7a'],
                  verdant:['#0a1410','#5fd39a','#4fc99a','#c8e6a8'] };
    var data=null;
    // open()/close() are guarded (unlike the original inline version) so a host that loads
    // this file WITHOUT the #ach-modal Folio of Honors skeleton (e.g. the Loom, which only wants
    // toasts + the Job tracker) doesn't crash -- close() in particular is reachable from the
    // global Escape-key listener below on every keypress, app-wide, whether or not the modal
    // exists on the current page.
    function open(){ var m=el('ach-modal'); if(!m) return; m.classList.add('open'); m.setAttribute('aria-hidden','false');
      load(false); }
    function close(){ var m=el('ach-modal'); if(!m) return; m.classList.remove('open'); m.setAttribute('aria-hidden','true'); }
    function load(mark){
      fetch('/api/achievements'+(mark?'?mark=1':''))
        .then(function(r){return r.json();})
        .then(function(d){ data=d; render(d); if(mark) toastNew(d); syncSkin(d); })
        .catch(function(){});
    }
    var BUCKETS=[['ladder','Evolution Ladders'],['milestone','Milestones'],
                 ['mastery','Masteries'],['feat','Feats of the Athenaeum']];
    function unleashed(){ try{ return localStorage.getItem('unleash')==='1'; }catch(e){ return false; } }
    function setUnleash(on){ try{ localStorage.setItem('unleash', on?'1':'0'); }catch(e){}
      if(data) render(data); }
    function tierPill(tier){ return '<span class="hall-tierpill-mini t-'+esc(tier)+'">'+esc(tier)+'</span>'; }
    // ---- The Folio of Honors card (tier / milestone / mastery / feat). Legendary and feat
    // cards get the 9-slice frame overlay -- extended from the unlock toast to grid tiles
    // here, a deliberate change from the prior "toast only" behavior (2026-07-22 redesign,
    // per docs/STATE.md's Per-tile ornate frames open question). Masked hidden feats arrive
    // from the server ALREADY sanitized (id/name/desc replaced server-side in api_achievements
    // -- see that route) so this function never has to know a real hidden feat's identity.
    function card(d,a){
      var masked=a.hidden&&!a.earned;
      var isFeat=a.tier==='feat';
      var framed=(a.tier==='legendary'||isFeat)&&!masked;
      var c=document.createElement('div');
      c.className='hall-card t-'+a.tier+(a.earned?' earned':' locked')+(masked?' hidden-feat':'')+(framed?' framed':'');
      c.setAttribute('data-q',(a.name+' '+a.desc+' '+a.tier).toLowerCase());
      // The badge <img> OVERLAYS the always-present escaped emoji text (same technique the
      // old .ico/.ico-badge pair used) rather than swapping textContent in from an inline
      // onerror attribute string -- interpolating a.icon into an event-handler ATTRIBUTE via
      // JSON.stringify would break (and, worse, be a real injection point) the moment any
      // icon value ever contained a double-quote. a.icon is currently always a short trusted
      // emoji from the server, but this way the safety doesn't depend on that staying true.
      var ico;
      if(masked){
        ico='<div class="hcd-ico"><img class="hcd-badge" src="/branding/mystery/secret_feat.png" onerror="this.remove()">'+esc(a.icon)+'</div>';
      } else if(a.earned){
        ico='<div class="hcd-ico"><img class="hcd-badge" src="/badge-thumb/'+esc(a.id)+'.png" onerror="this.remove()">'+esc(a.icon)+'</div>';
      } else {
        ico='<div class="hcd-ico emoji">'+esc(a.icon)+'</div>';
      }
      var sub=(a.bucket==='ladder'&&a.ladderName)?(esc(a.ladderName)+' &middot; '+esc(fmt(a.threshold))):'';
      var body=(framed?'<div class="hall-frame '+(isFeat?'feat':'legendary')+'"></div>':'')+ico
        +'<div class="hcd-body"><div class="hcd-top"><span class="hcd-nm">'+(masked?'???':esc(a.name))+'</span>'
        +(masked?'':tierPill(isFeat?'feat':a.tier))+'</div>'
        +'<div class="hcd-ds">'+(masked?'Hidden until earned':esc(a.desc))+'</div>'
        +(sub?'<div class="hcd-sub">'+sub+'</div>':'');
      if(a.criteria&&a.criteria.length){ body+='<div class="hcd-crit">'+a.criteria.map(function(x){
        return '<span class="'+(x.done?'on':'')+'">'+(x.done?'&#10003;':'&#9675;')+' '+esc(x.label)+'</span>'; }).join('')+'</div>'; }
      if(a.skin) body+='<div class="hcd-bannerflag">&#9733; unlocks '+esc(skinName(d,a.skin))+' skin</div>';
      if(a.banner_reward) body+='<div class="hcd-bannerflag">&#9873; unlocks a banner</div>';
      if(a.earned){ var hot=unleashed()&&a.roast_nsfw, rr=hot?a.roast_nsfw:a.roast;
        if(rr) body+='<div class="hcd-roast'+(hot?' hot':'')+'">'+esc(rr)+'</div>'; }
      if(!a.earned && !masked){ var pct=Math.min(100,Math.round(a.current/a.threshold*100));
        body+='<div class="hcd-bar"><i style="width:'+pct+'%"></i></div>'
            +'<div class="hcd-num">'+fmt(a.current)+' / '+fmt(a.threshold)+'</div>'; }
      body+='</div>';
      var ea=(d.earned_at||{})[a.id];
      body+='<div class="hcd-side"><div class="hcd-pts">'+(a.points?'+'+a.points:(isFeat?'feat':''))+'</div>'
        +'<div class="hcd-date">'+(a.earned&&ea?esc(ea):'')+'</div></div>';
      c.innerHTML=body;
      if(a.earned){ c.classList.add('clickable'); c.title='Replay this celebration';
        c.onclick=function(){ celebrate(a); }; }
      return c;
    }
    var _cur='summary', _activeBucket=null, _actLadder=null, _actIdx=0, _actTimer=null;
    function tab(name){
      _cur=name;
      var map={summary:'ach-summary',all:'ach-grid',stats:'ach-stats'};
      Object.keys(map).forEach(function(t){ var v=el(map[t]); if(v) v.style.display=(t===name)?'':'none'; });
      var tabs=el('ach-tabs'); if(tabs) tabs.querySelectorAll('.htab').forEach(function(b){
        b.classList.toggle('on', b.getAttribute('data-tab')===name); });
    }
    // jump(bucket) TOGGLES a category filter (clicking the same bucket again clears it) and
    // switches to All -- richer than the old scroll-to-section behavior, matching the
    // sidebar's new click-to-filter design. Re-renders grid+rail so both the filtered
    // content and the .rail-nav active highlight stay in sync.
    function jump(bucket){
      _activeBucket=(_activeBucket===bucket)?null:bucket;
      tab('all');
      if(data){ renderGrid(data); renderRail(data); }
    }
    function search(q){
      q=(q||'').trim().toLowerCase(); if(q) tab('all');
      var g=el('ach-grid'); if(!g) return;
      var top=el('hall-ladder-top'); if(top) top.style.display=q?'none':'';
      g.querySelectorAll('.hall-card').forEach(function(cd){
        var hay=cd.getAttribute('data-q')||''; cd.style.display=(!q||hay.indexOf(q)>=0)?'':'none'; });
    }
    function render(d){
      var all=d.achievements||[];
      var feats=all.filter(function(a){return a.tier==='feat';});
      var nonFeat=all.filter(function(a){return a.tier!=='feat';});
      var earned=nonFeat.filter(function(a){return a.earned;}).length;
      var fEarned=feats.filter(function(a){return a.earned;}).length;
      var p=el('ach-progress'); if(p) p.innerHTML='<b>'+earned+'</b> of <b>'+nonFeat.length+'</b> earned'
        +(d.feats_revealed?' &middot; <b style="color:var(--ruby)">'+fEarned+'</b> of '+feats.length+' feats':'')
        +' &middot; <b style="color:var(--gold)">'+fmt(d.earned_points||0)+'</b> / '+fmt(d.possible_points||0)+' pts';
      var slot=el('ach-unleash-slot'); if(slot){
        slot.innerHTML = d.unleash_available
          ? '<label class="ach-unleash"><input type="checkbox" '+(unleashed()?'checked':'')
            +' onchange="Ach.setUnleash(this.checked)">&#128520; Unleash the AI</label>' : ''; }
      renderSummary(d); renderGrid(d); renderStats(d); renderRail(d);
      tab(_cur);
    }
    // Groups the flat ladder-bucket achievements by track (using the top-level 'ladders'
    // list for display name + a stable order), sorted by rung. Each group's representative
    // image is its FIRST rung's badge -- always earnable/appropriate to show regardless of
    // how far the player has actually gotten, unlike using the top (spoiler) tier's art.
    function buildLadderGroups(d){
      var byTrack={};
      (d.achievements||[]).forEach(function(a){ if(a.bucket==='ladder'){
        (byTrack[a.track]=byTrack[a.track]||[]).push(a); } });
      Object.keys(byTrack).forEach(function(t){ byTrack[t].sort(function(x,y){return x.rung-y.rung;}); });
      return (d.ladders||[]).map(function(t){
        var tiers=byTrack[t.id]||[];
        return {id:t.id, name:t.name, tiers:tiers,
                img: tiers.length ? '/badge-thumb/'+encodeURIComponent(tiers[0].id)+'.png' : ''};
      }).filter(function(l){return l.tiers.length;});
    }
    function renderCarousel(d, ladders){
      var host=el('hall-carousel-slot'); if(!host) return;
      if(_actTimer){ clearInterval(_actTimer); _actTimer=null; }
      if(!ladders.length){ host.innerHTML=''; return; }
      if(!_actLadder || !ladders.some(function(l){return l.id===_actLadder;})){ _actLadder=ladders[0].id; _actIdx=0; }
      var ladder=ladders.filter(function(l){return l.id===_actLadder;})[0]||ladders[0];
      if(_actIdx>=ladder.tiers.length) _actIdx=0;
      var tier=ladder.tiers[_actIdx];
      var earnedCount=ladder.tiers.filter(function(t){return t.earned;}).length;
      var ea=(d.earned_at||{})[tier.id];
      var html='<div class="hall-carousel t-'+tier.tier+'"><div class="hc-row">'
        +'<div class="hc-cap'+(tier.earned?'':' zero')+'"><div class="hc-float"><div class="hc-ring"></div>'
        +'<div class="hc-badge"><img src="'+esc(ladder.img)+'" alt=""></div></div></div>'
        +'<div class="hc-body">'
        +'<div class="hc-eyebrow">'+esc(ladder.name)+'&ensp;&middot;&ensp;'+earnedCount+'/'+ladder.tiers.length+' tiers</div>'
        +'<div class="hc-name">'+esc(tier.name)+'</div>'
        +'<div class="hc-desc">'+esc(tier.desc)+'</div>'
        +'<div class="hc-meta">'+tierPill(tier.tier).replace('hall-tierpill-mini','hc-tierpill')
        +(tier.points?'<span class="hc-ptspill">+'+tier.points+' pts</span>':'')
        +'<span class="hc-thresh">'+esc(fmt(tier.threshold))+(tier.earned&&ea?' &middot; earned '+esc(ea):'')+'</span></div>'
        +'</div><div class="hc-nav"><button data-dir="-1" aria-label="Previous tier">&#8249;</button>'
        +'<button data-dir="1" aria-label="Next tier">&#8250;</button></div></div>'
        +'<div class="hc-pips">'+ladder.tiers.map(function(t,i){
          return '<button class="'+(i===_actIdx?'on':(t.earned?'done':''))+'" data-i="'+i+'" aria-label="'+esc(t.name)+'"></button>'; }).join('')
        +'</div></div>';
      host.innerHTML=html;
      var root=host.querySelector('.hall-carousel');
      root.querySelectorAll('.hc-nav button').forEach(function(b){
        b.onclick=function(){ _actIdx=(_actIdx+parseInt(b.getAttribute('data-dir'),10)+ladder.tiers.length)%ladder.tiers.length;
          renderCarousel(d, ladders); }; });
      root.querySelectorAll('.hc-pips button').forEach(function(b){
        b.onclick=function(){ _actIdx=parseInt(b.getAttribute('data-i'),10); renderCarousel(d, ladders); }; });
      _actTimer=setInterval(function(){ _actIdx=(_actIdx+1)%ladder.tiers.length; renderCarousel(d, ladders); }, 3500);
    }
    function renderGrid(d){
      var all=d.achievements||[]; var g=el('ach-grid'); if(!g) return;
      if(_actTimer){ clearInterval(_actTimer); _actTimer=null; }
      var showLadders=!_activeBucket||_activeBucket==='ladder';
      var ladders=buildLadderGroups(d);
      var html='';
      if(showLadders && ladders.length){
        html+='<div id="hall-carousel-slot"></div>'
          +'<div id="hall-ladder-top"><div class="hall-ladders">'+ladders.map(function(l){
            var ec=l.tiers.filter(function(t){return t.earned;}).length;
            return '<div class="ladder-badge t-'+(l.tiers.filter(function(t){return t.earned;})
                .sort(function(x,y){return {common:0,rare:1,epic:2,legendary:3}[y.tier]-{common:0,rare:1,epic:2,legendary:3}[x.tier];})[0]||{tier:'common'}).tier
                +(l.id===_actLadder?' on':'')+(ec?'':' zero')+'" data-ladder="'+esc(l.id)+'">'
              +'<div class="lb-img"><img src="'+esc(l.img)+'" alt=""></div>'
              +'<div class="lb-pips">'+l.tiers.map(function(t){return '<i style="'+(t.earned?'background:var(--tc)':'')+'"></i>';}).join('')+'</div>'
              +'<div class="lb-name">'+esc(l.name)+'</div></div>';
          }).join('')+'</div></div>';
        var activeLadder=ladders.filter(function(l){return l.id===(_actLadder||ladders[0].id);})[0]||ladders[0];
        html+='<div class="hall-block"><div class="hall-sec-h">'+esc(activeLadder.name)
          +' <span class="cnt">'+activeLadder.tiers.filter(function(t){return t.earned;}).length+'/'+activeLadder.tiers.length+' earned</span></div>'
          +'<div class="hall-cardgrid" id="hall-active-tiers"></div></div>';
        html+='<div class="hall-block"><div class="hall-sec-h">All Ladder Tiers</div><div id="hall-all-ladders"></div></div>';
      }
      var flatSections=[['milestone','Milestones'],['mastery','Masteries'],['feat','Feats of the Athenaeum']]
        .filter(function(b){ return (!_activeBucket||_activeBucket===b[0]) && (b[0]!=='feat'||d.feats_revealed); });
      flatSections.forEach(function(b){ html+='<div class="hall-block" id="hall-flat-'+b[0]+'"></div>'; });
      g.innerHTML=html;
      // populate the DOM-node-built pieces (card() returns real elements, cheaper to append
      // than to serialize achievement flavor text -- including roasts -- through innerHTML twice)
      if(showLadders && ladders.length){
        var atHost=el('hall-active-tiers');
        if(atHost) activeLadder.tiers.forEach(function(t){ atHost.appendChild(card(d, Object.assign({}, t, {ladderName:activeLadder.name}))); });
        var allHost=el('hall-all-ladders');
        if(allHost) ladders.forEach(function(l){
          var pd=document.createElement('div'); pd.className='hall-pilldiv'; pd.innerHTML=
            '<div class="pd-line"></div><div class="pd-pill"><img src="'+esc(l.img)+'" alt="">'
            +'<span class="pd-nm">'+esc(l.name)+'</span><span class="pd-ct">'
            +l.tiers.filter(function(t){return t.earned;}).length+'/'+l.tiers.length+'</span></div><div class="pd-line r"></div>';
          allHost.appendChild(pd);
          var grid=document.createElement('div'); grid.className='hall-cardgrid';
          l.tiers.forEach(function(t){ grid.appendChild(card(d, Object.assign({}, t, {ladderName:l.name}))); });
          allHost.appendChild(grid);
        });
        g.querySelectorAll('.ladder-badge').forEach(function(b){
          b.onclick=function(){ _actLadder=b.getAttribute('data-ladder'); _actIdx=0; renderGrid(data); }; });
        renderCarousel(d, ladders);
      }
      flatSections.forEach(function(b){
        var host=el('hall-flat-'+b[0]); if(!host) return;
        var rows=all.filter(function(a){return (a.bucket||'ladder')===b[0];});
        if(!rows.length) return;
        var pd=document.createElement('div'); pd.className='hall-pilldiv'+(b[0]==='feat'?' feats':'');
        pd.innerHTML='<div class="pd-line"></div><div class="pd-pill"><span class="pd-nm">'+esc(b[1])+'</span>'
          +'<span class="pd-ct">'+rows.filter(function(a){return a.earned;}).length+'/'+rows.length+'</span></div><div class="pd-line r"></div>';
        host.appendChild(pd);
        var grid=document.createElement('div'); grid.className='hall-cardgrid';
        rows.forEach(function(a){ grid.appendChild(card(d,a)); });
        host.appendChild(grid);
      });
      if(!g.children.length) g.innerHTML='<div class="hall-empty">Nothing matches this filter.</div>';
    }
    function renderSummary(d){
      var host=el('ach-summary'); if(!host) return; var all=d.achievements||[]; var ea=d.earned_at||{};
      var recent=all.filter(function(a){return a.earned && ea[a.id];})
        .sort(function(x,y){return (ea[y.id]||'').localeCompare(ea[x.id]||'');}).slice(0,6);
      var h='<div class="hall-block"><div class="hall-sec-h">Recent Achievements</div>';
      if(recent.length){ h+='<div class="hall-recent">';
        recent.forEach(function(a){ h+='<div class="rrow t-'+a.tier+'"><img src="/badge-thumb/'+esc(a.id)+'.png" onerror="this.remove()">'
          +'<div class="rt"><div class="rn">'+esc(a.name)+'</div><div class="rd">'+esc(ea[a.id])+'</div></div>'
          +(a.points?'<div class="rp">+'+a.points+'</div>':'')+'</div>'; });
        h+='</div>';
      } else { h+='<div class="hall-empty">Nothing yet &mdash; go make something.</div>'; }
      h+='</div><div class="hall-block"><div class="hall-sec-h">Progress Overview</div><div class="hall-prog">';
      function bar(label,e,t){ var pct=t?Math.round(e/t*100):0;
        return '<div class="prow"><div class="pl">'+esc(label)+'</div><div class="pbar"><i style="width:'+pct+'%"></i></div><div class="pv">'+e+' / '+t+'</div></div>'; }
      h+=bar('Overall', all.filter(function(a){return a.tier!=='feat'&&a.earned;}).length, all.filter(function(a){return a.tier!=='feat';}).length);
      BUCKETS.forEach(function(b){
        if(b[0]==='feat' && !d.feats_revealed) return;   // feats stay cloaked until the first one lands -- deliberately not shown here either
        var rows=all.filter(function(a){return (a.bucket||'ladder')===b[0];});
        if(rows.length) h+=bar(b[1], rows.filter(function(a){return a.earned;}).length, rows.length);
      });
      h+='</div></div>'; host.innerHTML=h;
    }
    var STAT_LABELS={images:'Images archived',videos:'Videos',collections:'Collections',models:'Models used',
      published:'Published works',tagged:'Tagged pieces',local_gens:'Local generations',gens_in_a_day:'Best day (generations)',
      distinct_keywords:'Distinct keywords',edits:'Edits',enhances:'Enhances',uploads:'Uploads',culled:'Culled',
      days_used:'Days visited',lora_used:'LoRA uses',lora_distinct:'Distinct LoRAs',storyboards:'Loom shots',
      similar_uses:'More-like-this uses',claims:'Rewards claimed',free_cards_applied:'Free cards used'};
    var RARITY_ORDER=['common','rare','epic','legendary'];
    var RARITY_HEX={common:'#9fbad6',rare:'#7fb0f4',epic:'#c69cff',legendary:'#e8cb7c'};
    function renderStats(d){
      var host=el('ach-stats'); if(!host) return; var all=d.achievements||[];
      var nonFeat=all.filter(function(a){return a.tier!=='feat';});
      var earnedN=nonFeat.filter(function(a){return a.earned;}).length;
      var feats=all.filter(function(a){return a.tier==='feat';});
      var h='<div class="hall-statcards">'
        +'<div class="hall-statcard"><div class="scl">Achieved</div><div class="scv">'+earnedN+'/'+nonFeat.length+'</div>'
        +'<div class="scs">'+(nonFeat.length?Math.round(earnedN/nonFeat.length*100):0)+'% complete</div></div>'
        +'<div class="hall-statcard"><div class="scl">Points Earned</div><div class="scv">'+fmt(d.earned_points||0)+'</div>'
        +'<div class="scs">of '+fmt(d.possible_points||0)+' possible</div></div>'
        +'<div class="hall-statcard"><div class="scl">Feats Earned</div><div class="scv">'
        +(d.feats_revealed?feats.filter(function(a){return a.earned;}).length+'/'+feats.length:'???')+'</div>'
        +'<div class="scs">prestige &middot; no points</div></div></div>';
      h+='<div class="hall-block"><div class="hall-sec-h">By Bucket</div><div class="hall-prog">';
      BUCKETS.forEach(function(b){
        if(b[0]==='feat' && !d.feats_revealed) return;
        var rows=all.filter(function(a){return (a.bucket||'ladder')===b[0];});
        if(!rows.length) return;
        var e=rows.filter(function(a){return a.earned;}).length, pct=Math.round(e/rows.length*100);
        h+='<div class="prow"><div class="pl">'+esc(b[1])+'</div><div class="pbar"><i style="width:'+pct+'%"></i></div><div class="pv">'+e+' / '+rows.length+'</div></div>';
      });
      h+='</div></div>';
      h+='<div class="hall-block"><div class="hall-sec-h">By Rarity</div>';
      RARITY_ORDER.forEach(function(r){
        var rows=all.filter(function(a){return a.tier===r;});
        if(!rows.length) return;
        var e=rows.filter(function(a){return a.earned;}).length, pct=Math.round(e/rows.length*100);
        h+='<div class="hall-rarity-row"><span class="rl">'+esc(r)+'</span><div class="rbar"><i style="width:'+pct+'%;background:'+RARITY_HEX[r]+'"></i></div><span class="rv">'+e+'/'+rows.length+'</span></div>';
      });
      h+='</div>';
      var ladders=buildLadderGroups(d);
      if(ladders.length){
        h+='<div class="hall-block"><div class="hall-sec-h">Ladder Completion</div>';
        ladders.forEach(function(l){
          var e=l.tiers.filter(function(t){return t.earned;}).length, pct=Math.round(e/l.tiers.length*100);
          h+='<div class="hall-ladder-row"><img src="'+esc(l.img)+'" alt=""><span class="ll">'+esc(l.name)+'</span>'
            +'<div class="lbar"><i style="width:'+pct+'%"></i></div><span class="lv">'+e+'/'+l.tiers.length+'</span></div>';
        });
        h+='</div>';
      }
      var keys=Object.keys(STAT_LABELS).filter(function(k){return (k in (d.metrics||{})) && d.metrics[k];});
      if(keys.length){
        h+='<div class="hall-block"><div class="hall-sec-h">Raw Metrics</div><div class="hall-stats">';
        keys.forEach(function(k){ h+='<div class="hall-stat"><span class="sl">'+esc(STAT_LABELS[k])+'</span><span class="sv">'+fmt(d.metrics[k])+'</span></div>'; });
        h+='</div></div>';
      }
      host.innerHTML=h;
    }
    function renderRail(d){
      var host=el('ach-rail'); if(!host) return; var all=d.achievements||[];
      var top='<div class="rail-scroll">';
      top+='<div><div class="rail-h">Categories</div><div class="rail-nav">';
      BUCKETS.forEach(function(b){
        if(b[0]==='feat' && !d.feats_revealed) return;
        var rows=all.filter(function(a){return (a.bucket||'ladder')===b[0];});
        if(!rows.length) return;
        top+='<a data-jump="'+b[0]+'" class="'+(_activeBucket===b[0]?'on':'')+'">'+esc(b[1])+'<span class="c">'+rows.filter(function(a){return a.earned;}).length+'/'+rows.length+'</span></a>';
      });
      top+='</div></div><div class="rail-div"></div>';
      var reach=all.filter(function(a){return !a.earned && !a.hidden && a.threshold>0;})
        .map(function(a){ return {a:a,pct:Math.min(99,Math.round(a.current/a.threshold*100))}; })
        .sort(function(x,y){return y.pct-x.pct;}).slice(0,3);
      top+='<div><div class="rail-h">Within Reach</div><div class="rail-reach">';
      if(reach.length){ reach.forEach(function(r){ var a=r.a;
        top+='<div class="rc"><div class="ri">'+esc(a.icon)+'</div><div class="rb"><div class="rbn">'+esc(a.name)+'</div>'
          +'<div class="rbar"><i style="width:'+r.pct+'%"></i></div><div class="rbp">'+fmt(a.current)+' / '+fmt(a.threshold)+'</div></div></div>'; });
      } else { top+='<div class="hall-empty">All caught up.</div>'; }
      top+='</div></div>';
      top+='<div class="rail-mascot"><img src="/branding/mascots/gen_nel.png" onerror="this.remove()"><div class="bubble">Keep going. The Void will not archive itself.</div></div>';
      top+='</div>';
      // Relics: read-only display of all 5 skins, locked+unlocked -- picking one still lives
      // in the Control Panel only, unchanged decision; these rows have no onclick on purpose.
      var pinned='<div class="rail-pinned"><div class="rail-h">Relics</div><div class="hall-relics">';
      (d.skins||[]).forEach(function(s){
        var sw=SKIN_SW[s.id]||[];
        var active=s.id===d.skin;
        pinned+='<div class="relic-row'+(s.earned?' unlocked':'')+(active?' active':'')+'" title="'+esc(s.desc||'')+'">'
          +'<div class="rsw">'+sw.map(function(c){return '<i style="background:'+c+'"></i>';}).join('')+'</div>'
          +'<span class="rnm">'+esc(s.name)+'</span>'
          +(active?'<span class="rck">&#10003;</span>':(!s.earned?'<span class="rlk">&#128274;</span>':''))+'</div>';
      });
      pinned+='</div><div class="rail-foot">Skins live in the <a href="/panel">Control Panel</a> now &middot; earn epics to unlock more.</div></div>';
      host.innerHTML=top+pinned;
      host.querySelectorAll('[data-jump]').forEach(function(el2){ el2.onclick=function(){ jump(el2.getAttribute('data-jump')); }; });
    }
    function skinName(d,id){ var s=(d.skins||[]).filter(function(x){return x.id===id;})[0]; return s?s.name:id; }
    function pick(id){
      fetch('/api/skin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({skin:id})})
        .then(function(r){return r.json();})
        .then(function(res){ if(res.skin){ applySkin(res.skin); if(data){ data.skin=res.skin; render(data);} } })
        .catch(function(){});
    }
    function applySkin(id){
      if(id&&id!=='moonglade') document.documentElement.setAttribute('data-skin',id);
      else document.documentElement.removeAttribute('data-skin');
      try{ localStorage.setItem('skin', id||'moonglade'); }catch(e){}
    }
    function syncSkin(d){ // server is source of truth; reconcile the pre-paint guess
      var srv=d.skin||'moonglade', cur=null;
      try{ cur=localStorage.getItem('skin'); }catch(e){}
      if(srv!==cur) applySkin(srv);
    }
    function toastNew(d){
      var newly=(d.newly||[]).map(function(id){
        return (d.achievements||[]).filter(function(a){return a.id===id;})[0]; }).filter(Boolean);
      if(newly.length>3){   // returning user with a full catalog -> one summary, not a barrage
        showToast({icon:'🏆', name:newly.length+' achievements unlocked',
                   desc:'Your catalog just earned a stack of achievements. Open '
                        +'🏆 to review them.', skin:false});
        return;
      }
      newly.forEach(function(a){ celebrate(a); });   // real unlocks get the mid-screen moment (queued)
    }
    // ---- the mid-screen achievement MOMENT: Nel presents the badge, flair scales with rarity ----
    var _q=[], _playing=false, _actx=null, _sfx={};
    /* Real SFX first: branding/sfx/ach_<tier>.ogg (drop a file in, it just works);
       missing/blocked file falls back to the synth chime. Result cached per tier. */
    function _chime(tier){
      var key=tier||'common';
      if(_sfx[key]===0){ _synth(tier); return; }
      try{
        var au=new Audio('/branding/sfx/ach_'+key+'.ogg'); au.volume=0.7;
        au.play().then(function(){ _sfx[key]=1; })
                 .catch(function(){ _sfx[key]=0; _synth(tier); });
      }catch(e){ _sfx[key]=0; _synth(tier); }
    }
    function _synth(tier){
      try{ _actx=_actx||new (window.AudioContext||window.webkitAudioContext)(); if(_actx.state==='suspended')_actx.resume(); }catch(e){ return; }
      var seq={common:[523,660],rare:[523,660,784],epic:[523,660,784,988],legendary:[392,523,660,784,1047],
               feat:[392,466,622,932]}[tier]||[660];
      var t=_actx.currentTime+0.02;
      seq.forEach(function(f,i){ var o=_actx.createOscillator(),g=_actx.createGain(); o.type='triangle'; o.frequency.value=f;
        o.connect(g); g.connect(_actx.destination); var s=t+i*0.1;
        g.gain.setValueAtTime(0.0001,s); g.gain.linearRampToValueAtTime(0.15,s+0.02); g.gain.exponentialRampToValueAtTime(0.0001,s+0.5);
        o.start(s); o.stop(s+0.55); });
      if(tier==='legendary'||tier==='feat'){ var lo=_actx.createOscillator(),lg=_actx.createGain(); lo.type='sine'; lo.frequency.value=(tier==='feat'?78:98);
        lo.connect(lg); lg.connect(_actx.destination); lg.gain.setValueAtTime(0.0001,t); lg.gain.linearRampToValueAtTime(0.28,t+0.02);
        lg.gain.exponentialRampToValueAtTime(0.0001,t+1.2); lo.start(t); lo.stop(t+1.3); }
    }
    /* Build one toast-v2 moment (the locked 335ef4e7 design). opts: eyebrow, line,
       pill:false, badge:false (emoji instead), mascot:false. */
    function _mkMoment(a, opts){
      opts=opts||{};
      var tier=a.tier||'common';
      var m=document.createElement('div'); m.className='ach-m2';
      var stage=document.createElement('div'); stage.className='tstage';
      var tw=document.createElement('div'); tw.className='tw t-'+tier;
      var line=(opts.line!=null)?opts.line
        :((unleashed()&&a.roast_nsfw)?a.roast_nsfw:(a.roast||a.desc||''));
      var rwd='';                                  // reward ribbon (gift box + text)
      if(a.skin) rwd='Unlocks skin: '+skinName(data||{skins:[]}, a.skin);
      else if(a.banner_reward) rwd='Unlocks a banner';
      // tier flair frame (9-slice border-image) wraps the toast for the top tiers only;
      // add epic:1 to frame epic too. Summary toasts (opts.badge===false) never get a frame.
      var framed=(!!({legendary:1,feat:1}[tier]))&&opts.badge!==false;
      var toastHTML='<div class="toast"><div class="cap"></div>'
        +'<div class="tbody"><div class="u">'+esc(opts.eyebrow||'New Achievement')+'</div>'
        +'<div class="n">'+esc(a.name)+'</div>'
        +'<div class="r">'+esc(line)+'</div>'
        +(opts.pill===false?'':'<span class="tier-pill">'+esc(tier)+'</span>')
        +((a.points&&opts.pill!==false)?'<span class="pts-pill">+'+a.points+'</span>':'')
        +(rwd?'<span class="rwd"><img class="giftbox" src="/branding/rewards/gift.png" onerror="this.remove()">'+esc(rwd)+'</span>':'')
        +'</div><div class="flash"></div></div>';
      tw.innerHTML='<div class="mglow"></div>'+(framed?'<div class="tframe">'+toastHTML+'</div>':toastHTML);
      stage.appendChild(tw); m.appendChild(stage);
      var cap=tw.querySelector('.cap');
      if(opts.badge===false){                       // summary: trophy in the well
        var e2=document.createElement('div'); e2.className='badge emoji';
        e2.textContent=a.icon||'🏆'; cap.appendChild(e2);
      } else {                                       // the medallion sweeps R->L into the cap
        var b=document.createElement('img'); b.className='badge';
        b.onerror=function(){ var e=document.createElement('div'); e.className='badge emoji';
          e.textContent=a.icon||'🏆';
          if(this.parentNode){ this.parentNode.replaceChild(e,this); } };
        b.src='/branding/badges/'+encodeURIComponent(a.id)+'.png';
        cap.appendChild(b);
        var ring=document.createElement('div'); ring.className='ring'; cap.appendChild(ring);
      }
      if(opts.mascot!==false){                       // the mascot leaps from the TOP edge
        var mfall=(tier==='feat')?'legendary':tier;
        var nel=document.createElement('img'); nel.className='mascot';
        // ANIMATED mascot first (drop <id>.webp beside the stills and it just moves),
        // then the still, then the tier chibi, then none. All fail-soft 404 hops.
        var chain=['/branding/mascots/ach/'+encodeURIComponent(a.id)+'.webp',
                   '/branding/mascots/ach/'+encodeURIComponent(a.id)+'.png',
                   '/branding/mascots/present_'+mfall+'.png'];
        var ci=0;
        nel.onerror=function(){ ci++; if(ci<chain.length){ this.src=chain[ci]; } else { this.remove(); } };
        nel.onload=function(){ try{ _seatMascot(this); }catch(e){} };
        nel.src=chain[0];
        tw.insertBefore(nel, tw.querySelector('.tframe')||tw.querySelector('.toast'));
      }
      return {m:m, tw:tw};
    }
    /* Adaptive seating: whatever padding the source image carries, seat the mascot so
       ~75% of its OPAQUE artwork rises above the toast band. Reads the alpha bounding
       box off a small canvas sample; any failure leaves the CSS defaults. */
    function _seatMascot(img){
      var W=48, H=64, c=document.createElement('canvas'); c.width=W; c.height=H;
      var x=c.getContext('2d'); x.drawImage(img,0,0,W,H);
      var d=x.getImageData(0,0,W,H).data, top=-1, bot=-1, r, q;
      for(r=0;r<H&&top<0;r++){ for(q=3;q<W*4;q+=16){ if(d[r*W*4+q]>24){ top=r; break; } } }
      for(r=H-1;r>=0&&bot<0;r--){ for(q=3;q<W*4;q+=16){ if(d[r*W*4+q]>24){ bot=r; break; } } }
      if(top<0||bot<=top) return;
      var opFrac=(bot-top+1)/H, topFrac=top/H;
      var BAND=158, TARGET=150;                      // ~150px of visible character
      var h=Math.max(140, Math.min(260, TARGET/opFrac));
      img.style.height=h+'px';
      img.style.top=(BAND - h*topFrac - 0.75*(h*opFrac)).toFixed(1)+'px';
    }
    /* Legendary + feat fanfare: the ROOM blows up around the toast (screen-level
       star rain + confetti, tier-colored) -- the flair the old moment had. */
    function _fanfare(m, tier){
      var glyphs=['✦','✧','⭐'], i, s, cn;
      for(i=0;i<46;i++){ s=document.createElement('div'); s.className='ee-star';
        s.textContent=glyphs[i%3]; s.style.left=(Math.random()*100)+'vw';
        s.style.color=(tier==='feat')?'var(--ruby)':'var(--gold)';
        s.style.fontSize=(12+Math.random()*22)+'px';
        s.style.animationDuration=(2.4+Math.random()*2.4)+'s';
        s.style.animationDelay=(Math.random()*1.4)+'s'; m.appendChild(s); }
      var cols=(tier==='feat')?['#e0355e','#8a93a2','#a11238','#d6d2e2','#4a515c']
                              :['#b692e6','#d4af37','#4fc99a','#c4a6f0','#ffffff'];
      for(i=0;i<80;i++){ cn=document.createElement('i'); cn.className='m2-conf';
        cn.style.background=cols[i%cols.length]; cn.style.left=(Math.random()*100)+'vw';
        cn.style.animationDuration=(1.8+Math.random()*1.8)+'s';
        cn.style.animationDelay=(0.2+Math.random()*0.9)+'s'; m.appendChild(cn); }
    }
    function _play(built, hold, after){
      var m=built.m, tw=built.tw;
      document.body.appendChild(m);
      void m.offsetWidth; m.classList.add('go'); tw.classList.add('go');
      var done=function(){ if(m._d)return; m._d=true; m.classList.add('out');
        setTimeout(function(){ if(m.parentNode)m.remove(); if(after)after(); }, 500); };
      m._t=setTimeout(done, hold);
      m.addEventListener('click', function(){ clearTimeout(m._t); done(); });
    }
    function celebrate(a){ if(a){ _q.push(a); if(!_playing) _next(); } }
    function _next(){
      if(!_q.length){ _playing=false; return; } _playing=true;
      var a=_q.shift(), tier=a.tier||'common';
      var hold={common:4200,rare:4800,epic:5400,legendary:6400,feat:6400}[tier]||4600;
      _chime(tier);
      var built=_mkMoment(a,{});
      if(tier==='legendary'||tier==='feat') _fanfare(built.m, tier);
      _play(built, hold, _next);
    }
    function showToast(a){    // the >3-unlock SUMMARY, in the same toast-v2 frame
      _play(_mkMoment({name:a.name, tier:'legendary', icon:a.icon||'🏆', id:''},
                      {badge:false, mascot:false, pill:false,
                       eyebrow:'Achievement Unlocked', line:a.desc||''}),
            6500, null);
    }
    // ---- the narrator: poke until it snaps (Triggered feat -> the Unleash toggle) ----
    var POKES=['The narrator ignores you.',
               'The narrator raises an eyebrow. Do you mind?',
               'The narrator is DESCRIBING things. Hands off.',
               'The narrator’s eye twitches. Last warning.',
               'FINE. You want the REAL commentary? Unleashed. Happy now?'];
    function poke(){
      fetch('/api/ach-event',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({event:'narrator'})})
        .then(function(r){return r.json();})
        .then(function(res){
          var n=Math.max(1,Math.min(res.pokes||1,POKES.length));
          try{ Toast.show({title:POKES[n-1], kind:(n>=POKES.length?'err':''), icon:'👆'}); }catch(e){}
          if(res.snapped) load(true);   // fires the Triggered celebration + reveals the toggle
        })
        .catch(function(){});
    }
    document.addEventListener('keydown', function(e){ if(e.key==='Escape') close(); });
    // On load: mark-and-toast any freshly earned feats, and reconcile the active skin.
    document.addEventListener('DOMContentLoaded', function(){ load(true); });
    return { open:open, close:close, poke:poke, setUnleash:setUnleash, tab:tab, search:search };
  })();

  // ================================================================================
  // Toast -- small corner notices, reusable (jobs + achievements + reward-claims share it)
  // ================================================================================
  var Toast = (function(){
    function box(){ var b=document.getElementById('mg-toasts');
      if(!b){ b=document.createElement('div'); b.id='mg-toasts'; b.setAttribute('aria-live','polite'); document.body.appendChild(b); }
      return b; }
    function esc(s){ return (s==null?'':String(s)).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
    function show(o){
      o=o||{};
      var kind=o.kind||'';   // '' | 'ok' | 'err'
      var el=document.createElement('div');
      el.className='mg-toast'+(kind?(' '+kind):'');
      var ic=o.icon||(kind==='ok'?'✓':(kind==='err'?'⚠':'◉'));
      var thumb=o.thumb?'<img class="mt-thumb" src="'+esc(o.thumb)+'" alt="">':'';
      el.innerHTML='<span class="mt-ic">'+ic+'</span><div class="mt-main"><div class="mt-title">'+esc(o.title||'')+'</div>'
        +(o.msg?'<div class="mt-msg">'+esc(o.msg)+'</div>':'')+'</div>'+thumb
        +'<button class="mt-x" aria-label="Dismiss">×</button>';
      function remove(){ if(!el.parentNode) return; el.classList.add('out'); setTimeout(function(){ if(el.parentNode) el.parentNode.removeChild(el); }, 320); }
      el.querySelector('.mt-x').onclick=remove;
      box().appendChild(el);
      if(!o.sticky){ setTimeout(remove, o.ttl||5200); }
      return remove;
    }
    return {show:show};
  })();

  // ================================================================================
  // Jobs -- submit-driver. Registers each gen in the server activity log, then polls
  // task-status so the download+catalog still happens (and survives the drawer closing).
  // The CARD (JobsCard) renders from the server log, NOT from here.
  //
  // register(id,label) is NEW (not in the original inline version): a register-ONLY entry
  // point that POSTs to /api/jobs (so the activity log/card shows it immediately) WITHOUT
  // starting a second polling loop -- for hosts (like the Loom) whose own generation flow
  // already owns a hardened, independently-completing poll loop (pollShot/_poll) and only
  // needs the submission to show up in the shared tracker, not a redundant second poller for
  // the same task_id. track(id,label,cb) is unchanged and still owns BOTH registration and
  // polling for hosts (like the gallery's own runTask) that don't have their own poll loop.
  // Both share the same `seen` de-dupe map so a stray double-call for the same id never
  // double-POSTs to /api/jobs.
  // ================================================================================
  var Jobs = (function(){
    var seen={};
    function register(id, label){
      if(!id || seen[id]) return; seen[id]=true;
      fetch('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({job_id:id, type:'generate', label:label||'Generation', status:'running'})}).catch(function(){});
      if(window.JobsCard) JobsCard.refresh();
    }
    function track(id, label, cb){
      if(!id || seen[id]) return;
      register(id, label);
      poll(id, cb);
    }
    // 6h ceiling, matching the Loom's POLL_CEILING_MS. This loop had NONE: a task
    // that never reached a terminal phase re-polled every 3s forever, and so did a
    // persistently failing fetch, because the .catch re-scheduled too. A browser
    // crawl caught it pinned on "Rendering under the eclipse..." with the Go button
    // permanently disabled while the tab hammered the server indefinitely.
    // Reports 'stalled' rather than 'failed': elapsed time is not evidence the task
    // died, only that this tab has stopped watching. A reload picks it up again.
    var POLL_CEILING_MS = 6 * 60 * 60 * 1000;
    function poll(id, cb, startedAt){
      var t0 = startedAt || Date.now();
      function again(ms){
        if(Date.now() - t0 > POLL_CEILING_MS){
          if(cb) cb('stalled', {phase:'stalled', error:'Stopped checking after 6h — the task may '+
            'still be running. Reload to resume watching, or check it on pixai.art.'});
          if(window.JobsCard) JobsCard.refresh();
          return;
        }
        setTimeout(function(){ poll(id, cb, t0); }, ms);
      }
      fetch('/api/task-status?task_id='+encodeURIComponent(id)).then(function(r){return r.json();}).then(function(d){
        if(d.phase==='done'){ if(cb) cb('done', d); if(window.JobsCard) JobsCard.refresh(); }
        else if(d.phase==='failed'){ if(cb) cb('failed', d); if(window.JobsCard) JobsCard.refresh(); }
        else { if(cb) cb('running', d); again(3000); }
      }).catch(function(){ again(4000); });
    }
    return {track:track, register:register};
  })();

  // ================================================================================
  // JobsCard -- the always-openable activity card, backed by /api/jobs. Renders the
  // server-side job log (survives reload), shows a short history, fires toasts on
  // completion/failure, and keeps failures until dismissed.
  // ================================================================================
  var JobsCard = (function(){
    var last={}, seeded=false, timer=null, LSK='mg_jobs_open';
    function el(i){ return document.getElementById(i); }
    function esc(s){ return (s==null?'':String(s)).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
    function isOpen(){ try{ return localStorage.getItem(LSK)==='1'; }catch(e){ return false; } }
    function applyState(){
      var t=el('jobs-tray'), f=el('jobs-fab'); if(!t||!f) return;
      if(isOpen()){ t.classList.add('open'); f.classList.remove('show'); }
      else { t.classList.remove('open'); f.classList.add('show'); }
    }
    function setOpen(v){ try{ localStorage.setItem(LSK, v?'1':'0'); }catch(e){} applyState(); }
    function open(){ setOpen(true); refresh(); }
    function close(){ setOpen(false); }
    function ago(ts){
      var s=Math.max(0, Math.floor(Date.now()/1000 - (ts||0)));
      if(s<60) return 'just now';
      if(s<3600) return Math.floor(s/60)+'m ago';
      if(s<86400) return Math.floor(s/3600)+'h ago';
      return Math.floor(s/86400)+'d ago';
    }
    // Where a job came from, in words. `j.type` is an internal enum -- 'cli', 'panel',
    // 'generate', 'delete', 'import' -- and this line used to render it raw under
    // `.jt-kind{text-transform:capitalize}`, which turned 'cli' into the non-word "Cli".
    // An unmapped type still falls through to its own capitalized value rather than
    // vanishing, so a new job source degrades to slightly-ugly instead of blank.
    var KIND_LABEL = { cli: 'Terminal', panel: 'Control Panel', generate: 'Generate',
                       'delete': 'Delete', 'import': 'Import' };
    function kindLabel(t){ return KIND_LABEL[t] || t || 'Job'; }
    function row(j){
      // done_with_errors (D-4): the job itself completed (exit 0 by design), but some
      // files failed after retries -- distinct from both a clean 'done' and a hard
      // 'failed'. Must be terminal/dismissable like the other two, or it's stuck
      // looking permanently in-progress with no way to clear it.
      //
      // stale: the server's own orphan-reconciliation sweep (resolve_orphan_jobs,
      // /api/jobs) found a job stuck 'running' past its age threshold AND couldn't reach
      // PixAI to find out its real state -- distinct from done_with_errors (that's a
      // completed run with partial failures) and from a plain failed. NOT in the
      // backend's terminal set (a later sweep can still resolve it for real, or a
      // task-id recovery closes it), but shown + dismissable like one so it never just
      // looks like an ordinary still-in-progress spinner forever.
      var st=j.status||'running';
      var fin=(st==='done'||st==='failed'||st==='done_with_errors'||st==='stale');
      var ic = st==='done'
             ? '<span class="jt-ok jt-glyph">✓</span><img class="jt-nel" src="/branding/mascots/trk_done.png" onerror="this.remove()">'
             : st==='done_with_errors'
             ? '<span class="jt-warn jt-glyph">⚠</span><img class="jt-nel" src="/branding/mascots/trk_done.png" onerror="this.remove()">'
             : st==='failed'
             ? '<span class="jt-err jt-glyph">⚠</span><img class="jt-nel" src="/branding/mascots/trk_fail.png" onerror="this.remove()">'
             : st==='stale'
             ? '<span class="jt-warn jt-glyph">?</span><img class="jt-nel" src="/branding/mascots/trk_fail.png" onerror="this.remove()">'
             : '<span class="jt-spin"><img class="jt-nel" src="/branding/gen_nel.png" onerror="this.remove()"><i class="gen-ring"></i></span>';
      var mid=(j.media_ids||[])[0]||'';
      var thumb=(st==='done'&&mid)?'<a class="jt-thumb" href="/image/'+encodeURIComponent(mid)+'"><img src="/thumbs/'+encodeURIComponent(mid)+'.jpg" alt=""></a>':'';
      var bar='';
      if(st==='running' && j.total){ var pct=Math.min(100, Math.round((j.done||0)/j.total*100)); bar='<div class="jt-bar"><i style="width:'+pct+'%"></i></div>'; }
      var errmsg=((st==='failed'||st==='done_with_errors'||st==='stale')&&j.error)?'<div class="jt-errmsg">'+esc(j.error)+'</div>':'';
      var sub='<div class="jt-sub"><span class="jt-kind">'+esc(kindLabel(j.type))+'</span><span class="jt-when">'+ago(j.ts)+'</span></div>';
      var x=fin?'<button class="jt-x" data-job="'+esc(j.job_id)+'" title="Dismiss">×</button>':'';
      var cls=st==='failed'?' st-failed':((st==='done_with_errors'||st==='stale')?' st-warn':'');
      return '<div class="jt-item'+cls+'"><div class="jt-ic">'+ic+'</div>'
           +'<div class="jt-main"><div class="jt-lab">'+esc(j.label||'Generation')+'</div>'+sub+bar+errmsg+'</div>'
           +thumb+x+'</div>';
    }
    function render(jobs){
      var t=el('jobs-tray'); if(!t) return;
      var running=0; jobs.forEach(function(j){ if((j.status||'running')==='running') running++; });
      var head='<div class="jt-head"><span class="jt-title">◉ Activity'
        +(jobs.length?' <span class="jt-count">'+jobs.length+'</span>':'')+'</span>'
        +'<button class="jt-hbtn" data-act="clear" title="Clear finished">clear</button>'
        +'<button class="jt-hbtn" data-act="close" title="Collapse">–</button></div>';
      var body='';
      if(!jobs.length){ body='<div class="jt-empty"><img class="jt-empty-nel" src="/branding/mascots/trk_empty.png" onerror="this.remove()"><div>The archive is quiet.<br>Generations and syncs will appear here.</div></div>'; }
      else { jobs.forEach(function(j){ body+=row(j); }); }
      t.innerHTML=head+'<div class="jt-body">'+body+'</div>';
      var f=el('jobs-fab'); if(f){ f.classList.toggle('busy', running>0); var b=el('jobs-fab-badge'); if(b) b.textContent=running||''; }
      var live=el('gen-live');
      if(live){
        if(running){
          if(!live.querySelector('.gen-nel-wrap')){   // build the spinner once so it doesn't restart each poll
            live.innerHTML='<span class="gen-nel-wrap"><img class="gen-nel" src="/branding/gen_nel.png" onerror="this.remove()"><i class="gen-ring"></i></span><span class="gen-live-txt"></span>';
          }
          var gt=live.querySelector('.gen-live-txt'); if(gt){ gt.textContent=running+' running'; }
          live.style.display='';
        } else { live.style.display='none'; }
      }
    }
    function toastTransitions(jobs){
      var TERMINAL = {done:1, failed:1, done_with_errors:1};
      jobs.forEach(function(j){
        var st=j.status||'running', prev=last[j.job_id];
        if(seeded && !TERMINAL[prev] && TERMINAL[st]){
          if(st==='done'){
            var mid=(j.media_ids||[])[0]||'';
            Toast.show({kind:'ok', title:(j.label||'Generation')+' — done', msg:'Added to your gallery.',
                        thumb: mid?('/thumbs/'+encodeURIComponent(mid)+'.jpg'):null});
          } else if(st==='done_with_errors'){
            Toast.show({kind:'err', sticky:true, title:(j.label||'Job')+' finished with errors',
                        msg:j.error||'Some files failed — see the activity card.'});
          } else {
            Toast.show({kind:'err', sticky:true, title:(j.label||'Job')+' failed', msg:j.error||'See the activity card.'});
          }
        }
        last[j.job_id]=st;
      });
      seeded=true;
    }
    function refresh(){
      return fetch('/api/jobs').then(function(r){return r.json();}).then(function(d){
        var jobs=(d&&d.jobs)||[];
        toastTransitions(jobs); render(jobs);
      }).catch(function(){});
    }
    function schedule(){
      if(timer) clearTimeout(timer);
      var f=el('jobs-fab'); var busy=f&&f.classList.contains('busy');
      timer=setTimeout(function(){
        if(document.hidden){ schedule(); return; }
        refresh().then(schedule);
      }, busy?2500:7000);
    }
    function dismiss(id){
      fetch('/api/jobs/dismiss',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:id})})
        .then(function(){ delete last[id]; refresh(); }).catch(function(){});
    }
    function clearFinished(){
      fetch('/api/jobs/dismiss',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({finished:true})})
        .then(refresh).catch(function(){});
    }
    document.addEventListener('DOMContentLoaded', function(){
      applyState();
      var t=el('jobs-tray');
      if(t){ t.addEventListener('click', function(e){
        var x=e.target.closest?e.target.closest('.jt-x[data-job]'):null;
        if(x){ dismiss(x.getAttribute('data-job')); return; }
        var h=e.target.closest?e.target.closest('.jt-hbtn[data-act]'):null;
        if(h){ var a=h.getAttribute('data-act'); if(a==='clear') clearFinished(); else if(a==='close') close(); }
      }); }
      refresh().then(schedule);
    });
    return {open:open, close:close, refresh:refresh, dismiss:dismiss, clearFinished:clearFinished};
  })();

  window.Ach = Ach;
  window.Toast = Toast;
  window.Jobs = Jobs;
  window.JobsCard = JobsCard;
})();
