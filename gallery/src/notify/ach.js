/* notify/ach.js -- the achievement celebration engine, ported from static/mg-notify.js's Ach
   IIFE (no-vanilla campaign, component 6). Deliberately an IMPERATIVE module, not a React
   component: a celebration is a one-shot, self-cleaning animation sequence (badge medallion
   sweep, mascot pop with canvas alpha-bbox seating, ring pulse, tier fanfare, WebAudio chime)
   appended to document.body and removed when it ends -- forcing that timeline into JSX would be
   fighting the framework for no benefit. The React app talks to it through exactly the two
   entry points it always used: check() (mark-and-toast after a generation / on load) and
   replay(a, opts) (the Folio's click-an-earned-card, returns the scramble driver handle).

   DROPPED, deliberately and disclosed (not silently): the vanilla's entire #ach-modal "Trophy
   Hall" DOM machinery -- open/close/tab/jump/search/render/renderGrid/renderSummary/renderStats/
   renderRail/renderCarousel/card/buildLadderGroups/pick/setUnleash/poke and the .ach-modal/
   .hall-* CSS. No #ach-modal skeleton exists on any served page (the React Folio of Honors --
   FolioOverlay.jsx/useFolio.js -- replaced it), so every one of those paths was guarded
   dead code on both hosts. The vanilla's Escape listener existed only to close that modal and
   went with it -- the Escape this module listens for TODAY is a different key on a different
   layer (THE EXIT, further down: it ends a running flood parade and nothing else).
   unleashed() is KEPT (it gates the roast text on the live celebration; the React Folio manages
   the same localStorage key), as are syncSkin/applySkin (check() reconciles the active skin). */

import { apiGet } from "../api.js";
import { badgeSrc, badgeHop } from "./badgeArt.js";

let data = null;                 // last /api/achievements payload (skinName for reward ribbons)

function unleashed() {
  try { return localStorage.getItem("unleash") === "1"; } catch { return false; }
}
function skinName(d, id) {
  const s = ((d || {}).skins || []).filter((x) => x.id === id)[0];
  return s ? s.name : id;
}
function applySkin(id) {
  if (id && id !== "moonglade") document.documentElement.setAttribute("data-skin", id);
  else document.documentElement.removeAttribute("data-skin");
  try { localStorage.setItem("skin", id || "moonglade"); } catch { /* private mode */ }
}
function syncSkin(d) {           // server is source of truth; reconcile the pre-paint guess
  const srv = d.skin || "moonglade";
  let cur = null;
  try { cur = localStorage.getItem("skin"); } catch { /* private mode */ }
  if (srv !== cur) applySkin(srv);
}

function load(mark) {
  apiGet("/api/achievements" + (mark ? "?mark=1" : ""))
    .then((d) => { if (d.error) return; data = d; if (mark) toastNew(d); syncSkin(d); });
}

function toastNew(d) {
  const newly = (d.newly || [])
    .map((id) => (d.achievements || []).filter((a) => a.id === id)[0])
    .filter(Boolean);
  if (newly.length > 3) {        // a flood -> the TRAIL parade (owner ruling 2026-09-03):
    _floodParade(newly);         // every earn presents, then recedes down-screen behind the next
    return;
  }
  newly.forEach((a) => celebrate(a));   // real unlocks get the mid-screen moment (queued)
}

// ---- the mid-screen achievement MOMENT: Nel presents the badge, flair scales with rarity ----
const _q = [];
let _playing = false;
let _actx = null;
const _sfx = {};

/* Real SFX first: /branding/sfx/ach_<tier>.ogg (drop a file in, it just works); a missing or
   blocked file falls back to the synth chime. Result cached per tier. */
function _chime(tier) {
  const key = tier || "common";
  if (_sfx[key] === 0) { _synth(tier); return; }
  try {
    const au = new Audio("/branding/sfx/ach_" + key + ".ogg");
    au.volume = 0.7;
    au.play().then(() => { _sfx[key] = 1; }).catch(() => { _sfx[key] = 0; _synth(tier); });
  } catch { _sfx[key] = 0; _synth(tier); }
}
function _synth(tier) {
  try {
    _actx = _actx || new (window.AudioContext || window.webkitAudioContext)();
    if (_actx.state === "suspended") _actx.resume();
  } catch { return; }
  const seq = {
    common: [523, 660], rare: [523, 660, 784], epic: [523, 660, 784, 988],
    legendary: [392, 523, 660, 784, 1047], feat: [392, 466, 622, 932],
  }[tier] || [660];
  const t = _actx.currentTime + 0.02;
  seq.forEach((f, i) => {
    const o = _actx.createOscillator(), g = _actx.createGain();
    o.type = "triangle"; o.frequency.value = f;
    o.connect(g); g.connect(_actx.destination);
    const s = t + i * 0.1;
    g.gain.setValueAtTime(0.0001, s);
    g.gain.linearRampToValueAtTime(0.15, s + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, s + 0.5);
    o.start(s); o.stop(s + 0.55);
  });
  if (tier === "legendary" || tier === "feat") {
    const lo = _actx.createOscillator(), lg = _actx.createGain();
    lo.type = "sine"; lo.frequency.value = (tier === "feat" ? 78 : 98);
    lo.connect(lg); lg.connect(_actx.destination);
    lg.gain.setValueAtTime(0.0001, t);
    lg.gain.linearRampToValueAtTime(0.28, t + 0.02);
    lg.gain.exponentialRampToValueAtTime(0.0001, t + 1.2);
    lo.start(t); lo.stop(t + 1.3);
  }
}

function esc(s) {
  return (s == null ? "" : String(s)).replace(/[&<>"]/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]
  ));
}

/* Build one toast-v2 moment (the locked 335ef4e7 design). opts: eyebrow, line, pill:false,
   badge:false (emoji instead), mascot:false. Ornate frames are GONE everywhere (owner call
   2026-08-01) -- tier reads from the band, glow, and pills; never reintroduce frame DOM. */
function _mkMoment(a, opts) {
  opts = opts || {};
  const tier = a.tier || "common";
  const m = document.createElement("div"); m.className = "ach-m2";
  const stage = document.createElement("div"); stage.className = "tstage";
  const tw = document.createElement("div"); tw.className = "tw t-" + tier;
  const line = (opts.line != null) ? opts.line
    : ((unleashed() && a.roast_nsfw) ? a.roast_nsfw : (a.roast || a.desc || ""));
  let rwd = "";                                  // reward ribbon (gift box + text)
  if (a.skin) rwd = "Unlocks skin: " + skinName(data || { skins: [] }, a.skin);
  else if (a.banner_reward) rwd = "Unlocks a banner";
  const toastHTML = '<div class="toast"><div class="cap"></div>'
    + '<div class="tbody"><div class="u">' + esc(opts.eyebrow || "New Achievement") + "</div>"
    + '<div class="n">' + esc(a.name) + "</div>"
    + '<div class="r">' + esc(line) + "</div>"
    + (opts.pill === false ? "" : '<span class="tier-pill">' + esc(tier) + "</span>")
    + ((a.points && opts.pill !== false) ? '<span class="pts-pill">+' + (Number(a.points) || 0) + "</span>" : "")
    + (rwd ? '<span class="rwd"><i class="giftbox"></i>' + esc(rwd) + "</span>" : "")
    + '</div><div class="flash"></div></div>';
  tw.innerHTML = '<div class="mglow"></div>' + toastHTML;
  stage.appendChild(tw); m.appendChild(stage);
  const cap = tw.querySelector(".cap");
  if (opts.badge === false) {                    // summary: trophy in the well
    const e2 = document.createElement("div"); e2.className = "badge emoji";
    e2.textContent = a.icon || "🏆"; cap.appendChild(e2);
  } else {                                       // the medallion sweeps R->L into the cap
    const b = document.createElement("img"); b.className = "badge";
    b.onerror = function () {
      // The badge walks a fail-soft ladder of its own now, exactly like the mascot below:
      // animated master -> still thumb -> emoji. badgeHop is false only once it's spent.
      if (badgeHop(this, a.id, 384)) return;
      const e = document.createElement("div"); e.className = "badge emoji";
      e.textContent = a.icon || "🏆";
      if (this.parentNode) this.parentNode.replaceChild(e, this);
    };
    b.src = badgeSrc(a.id, 384);   // <id>.webp when the medallion is animated; else the 384px cached thumb -- crisp on HiDPI at the enlarged medallion, still tiny vs the 5.6MB master; the achievement is always earned when its toast fires, so a sealed feat badge still serves
    cap.appendChild(b);
    const ring = document.createElement("div"); ring.className = "ring"; cap.appendChild(ring);
    // Badge-local ambient decoration, legendary/feat only -- positions/counts verbatim from
    // Ambient Layer.dc.html's achMotes (5 at 72°, alternating 5/7px) and achWisps (8, staggered).
    if (tier === "legendary") {
      const halo = document.createElement("div"); halo.className = "m2-halo"; cap.appendChild(halo);
      const moteWrap = document.createElement("div"); moteWrap.className = "m2-motewrap";
      [0, 72, 144, 216, 288].forEach((deg, i) => {
        const r = 50, rad = deg * Math.PI / 180;
        const x = 50 + r * Math.cos(rad), y = 50 + r * Math.sin(rad), sz = i % 2 ? 5 : 7;
        const mt = document.createElement("span"); mt.className = "m2-mote";
        mt.style.left = x.toFixed(1) + "%"; mt.style.top = y.toFixed(1) + "%";
        mt.style.width = sz + "px"; mt.style.height = sz + "px";
        moteWrap.appendChild(mt);
      });
      cap.appendChild(moteWrap);
    } else if (tier === "feat") {
      const flame = document.createElement("div"); flame.className = "m2-flameglow"; cap.appendChild(flame);
      cap.appendChild(document.createElement("div")).className = "m2-runeA";
      cap.appendChild(document.createElement("div")).className = "m2-runeB";
      for (let wi = 0; wi < 8; wi++) {
        const sway = (wi % 2 ? 1 : -1) * (10 + wi * 3);
        const rot = (wi % 2 ? 1 : -1) * (8 + wi * 2);
        const sz = 10 + (wi % 3) * 4;
        const wisp = document.createElement("div"); wisp.className = "m2-wisp";
        wisp.style.left = (16 + wi * 9) + "%";
        wisp.style.width = sz + "px"; wisp.style.height = sz + "px";
        wisp.style.setProperty("--sway", sway + "px");
        wisp.style.setProperty("--rot", rot + "deg");
        wisp.style.animationDuration = (1.1 + (wi % 4) * 0.15).toFixed(2) + "s";
        wisp.style.animationDelay = (1.4 + wi * 0.12).toFixed(2) + "s";
        cap.appendChild(wisp);
      }
    }
  }
  if (opts.mascot !== false) {                   // the mascot leaps from the TOP edge
    const mfall = (tier === "feat") ? "legendary" : tier;
    const nel = document.createElement("img"); nel.className = "mascot";
    // ANIMATED mascot first (drop <id>.webp beside the stills and it just moves), then the
    // still, then the tier chibi, then none. All fail-soft 404 hops.
    const chain = [
      "/branding/mascots/ach/" + encodeURIComponent(a.id) + ".webp",
      "/branding/mascots/ach/" + encodeURIComponent(a.id) + ".png",
      "/branding/mascots/present_" + mfall + ".png",
    ];
    let ci = 0;
    nel.onerror = function () { ci++; if (ci < chain.length) this.src = chain[ci]; else this.remove(); };
    nel.onload = function () { try { _seatMascot(this); } catch { /* leave CSS defaults */ } };
    nel.src = chain[0];
    tw.insertBefore(nel, tw.querySelector(".toast"));
  }
  return { m, tw };
}

/* Adaptive seating: whatever padding the source image carries, seat the mascot so ~85% of its
   OPAQUE artwork rises above the toast band. Reads the alpha bounding box off a small canvas
   sample; any failure leaves the CSS defaults. */
function _seatMascot(img) {
  const W = 48, H = 64, c = document.createElement("canvas");
  c.width = W; c.height = H;
  const x = c.getContext("2d");
  x.drawImage(img, 0, 0, W, H);
  const d = x.getImageData(0, 0, W, H).data;
  let top = -1, bot = -1, r, q;
  for (r = 0; r < H && top < 0; r++) { for (q = 3; q < W * 4; q += 16) { if (d[r * W * 4 + q] > 24) { top = r; break; } } }
  for (r = H - 1; r >= 0 && bot < 0; r--) { for (q = 3; q < W * 4; q += 16) { if (d[r * W * 4 + q] > 24) { bot = r; break; } } }
  if (top < 0 || bot <= top) return;
  const opFrac = (bot - top + 1) / H, topFrac = top / H;
  const BAND = 158, TARGET = 150;                // ~150px of visible character
  const h = Math.max(140, Math.min(260, TARGET / opFrac));
  img.style.height = h + "px";
  img.style.top = (BAND - h * topFrac - 0.85 * (h * opFrac)).toFixed(1) + "px";
}

/* Legendary + feat fanfare: the ROOM blows up around the toast (screen-level star rain +
   confetti, tier-colored). The .ee-star rules ride notify.css (scoped .ach-m2 .ee-star) so the
   star-rain works on BOTH hosts -- the vanilla relied on the gallery's styles.css and the rain
   silently no-opped on the Loom. */
function _fanfare(m, tier) {
  const glyphs = ["✦", "✧", "⭐"];
  let i, s, cn;
  for (i = 0; i < 46; i++) {
    s = document.createElement("div"); s.className = "ee-star";
    s.textContent = glyphs[i % 3];
    s.style.left = (Math.random() * 100) + "vw";
    s.style.color = (tier === "feat") ? "var(--ruby)" : "var(--gold)";
    s.style.fontSize = (12 + Math.random() * 22) + "px";
    s.style.animationDuration = (2.4 + Math.random() * 2.4) + "s";
    s.style.animationDelay = (Math.random() * 1.4) + "s";
    m.appendChild(s);
  }
  const cols = (tier === "feat")
    ? ["#e0355e", "#8a93a2", "#a11238", "#d6d2e2", "#4a515c"]
    : ["#b692e6", "#d4af37", "#4fc99a", "#c4a6f0", "#ffffff"];
  for (i = 0; i < 84; i++) {
    cn = document.createElement("i"); cn.className = "m2-conf";
    cn.style.background = cols[i % cols.length];
    cn.style.left = (Math.random() * 100) + "vw";
    cn.style.animationDuration = (1.8 + Math.random() * 1.8) + "s";
    cn.style.animationDelay = (0.2 + Math.random() * 0.9) + "s";
    m.appendChild(cn);
  }
}

function _play(built, hold, after) {
  const m = built.m, tw = built.tw;
  document.body.appendChild(m);
  void m.offsetWidth;
  m.classList.add("go"); tw.classList.add("go");
  const done = () => {
    if (m._d) return;
    m._d = true;
    m.classList.add("out");
    setTimeout(() => { if (m.parentNode) m.remove(); if (after) after(); }, 500);
  };
  m._t = setTimeout(done, hold);
  m.addEventListener("click", () => { clearTimeout(m._t); done(); });
}

const HOLD = { common: 4200, rare: 4800, epic: 5400, legendary: 6400, feat: 6400 };

/* ---- the flood TRAIL (owner ruling 2026-09-03, mock-approved): during a >3 flood each
   achievement presents front-and-center with its normal moment, then RECEDES down the screen
   into a shrinking, dimming stack of the already-earned while the next pops in front. The
   stack is presented HISTORY, never the pending queue. Receded layers drop their scrim and
   all pointer events; ~4 stay visible, older ones leave as the counter chip keeps score. */
const FLOOD_DWELL_MS = 2400;   // flood cadence -- deliberately tunable in one place
const _trail = [];
let _chip = null;              // the "×N earned" counter -- presented history, never clickable
let _skip = null;              // the skip control beside it (see THE EXIT below)

function _recede(m) {
  m.classList.add("trail");
  _trail.unshift(m);
  _trail.forEach((el, i) => {
    el.classList.remove("trail-1", "trail-2", "trail-3", "trail-4");
    if (i < 4) el.classList.add("trail-" + (i + 1));
  });
  while (_trail.length > 4) {
    const old = _trail.pop();
    old.classList.add("out");
    setTimeout(() => { if (old.parentNode) old.remove(); }, 500);
  }
}

// The pending "the trail bows out" timer, held so it can be CANCELLED. Without this a
// replay that starts while a parade is winding down inherits the parade's 3.2s timer,
// which then rips the replay's own trail and chip out of the DOM mid-moment.
let _clearTimer = null;

/* The LIVE parade, or null when none is on screen: {q, m, ended}. `q` is the flood's own
   pending list (the moments not yet shown) and `m` the one currently front-and-center.
   Holding that at module scope is what lets THE EXIT below reach a parade already in
   flight -- the queue used to live only inside _floodParade's closure, where nothing
   outside could stop it (not even replay()'s takeover, which cleared _q and the trail but
   left the flood happily stepping on behind the replay's own moment). */
let _parade = null;

// THE ONE TEARDOWN. Natural end, replay()'s takeover and the exit all land here; nothing
// else removes a trail layer or a chip, so there is no second path to race this one.
function _clearParade() {
  _clearTimer = null;
  _parade = null;
  _trail.splice(0).forEach((el) => {
    el.classList.add("out");
    setTimeout(() => { if (el.parentNode) el.remove(); }, 500);
  });
  [_chip, _skip].forEach((c) => {
    if (!c) return;
    c.classList.add("out");
    setTimeout(() => { if (c.parentNode) c.remove(); }, 500);
  });
  _chip = null; _skip = null;
}

/* ---- THE EXIT (owner ruling 2026-09-04, DECISIONS.md "The achievement parade gets an
   exit"): a long parade is skippable -- Escape, or the skip chip beside the counter.

   PRESENTATION ONLY. The earns were already recorded server-side by the
   /api/achievements?mark=1 load that produced this list (load() -> toastNew()); a moment in
   the step loop below is a chime plus DOM and nothing else -- it marks nothing, posts
   nothing, grants nothing. The reward a badge announces (a skin, a banner) is granted with
   the earn and applied from the same payload by syncSkin(), not by the moment. So an
   achievement whose moment never played is earned exactly like one that was watched.

   The moment on screen JOINS THE TRAIL rather than being ripped out of the DOM, which is
   what makes it fade instead of vanishing mid-frame -- and it fades through the same .out
   class, on the same 500ms, as the click-dismiss that has always shipped. Then _clearParade
   takes the layer down. No second teardown, nothing new for the existing ones to race. */
function _paradeUp() { return !!(_parade || _clearTimer || _trail.length); }

function _endParade() {
  const p = _parade;
  if (p) {
    p.ended = true;                 // the step loop is over, whatever timer fires next
    p.q.length = 0;                 // the moments still queued: skipped, and already earned
    const m = p.m;
    // A false _adv is the tell that the front moment has NOT receded, so it is not in
    // _trail yet and _clearParade would leave it stranded on screen.
    if (m && !m._adv) { clearTimeout(m._t); m._adv = true; _trail.unshift(m); }
  }
  if (_clearTimer) { clearTimeout(_clearTimer); _clearTimer = null; }
  _clearParade();
}

/* The skip control: the counter chip's twin, one line above it. A SEPARATE element because
   the counter is presented history and deliberately takes no pointer events -- making it
   clickable would change what an approved surface means. It is a real <button> so touch and
   assistive tech get the same exit the keyboard does. */
function _mkSkipChip() {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "ach-trailchip ach-skipchip";
  b.setAttribute("aria-label", "Skip the rest of the achievement parade");
  b.addEventListener("click", (e) => { e.stopPropagation(); _endParade(); });
  document.body.appendChild(b);
  return b;
}

/* Escape ends the parade -- and ONLY while one is up. Registered at module load, in CAPTURE
   on window, which puts it ahead of every Escape handler the React tree mounts afterwards
   (App.jsx's overlay closer, useCommandPalette's one global listener, the drawer/picker/panel
   ladders -- every one of them registers from an effect, and main.jsx calls installNotify()
   before createRoot().render()). That ordering is the point: the parade layer is z-index 520,
   above everything, so while it plays Escape is its key and is consumed here.

   With no parade up the handler returns without touching the event at all -- the app's Escape
   ladder behaves exactly as it did. A Folio replay is deliberately NOT a parade: Escape still
   closes the Folio, which dismisses the moment through useFolio's unmount cleanup. */
function _onKey(e) {
  if (e.key !== "Escape" || !_paradeUp()) return;
  e.preventDefault();
  e.stopPropagation();
  e.stopImmediatePropagation();
  _endParade();
}
if (typeof window !== "undefined" && window.addEventListener) {
  window.addEventListener("keydown", _onKey, true);
}

function _playFlood(built, after) {
  const m = built.m, tw = built.tw;
  document.body.appendChild(m);
  void m.offsetWidth;
  m.classList.add("go"); tw.classList.add("go");
  const advance = () => {
    if (m._adv) return;
    m._adv = true;
    _recede(m);
    if (after) after();
  };
  m._t = setTimeout(advance, FLOOD_DWELL_MS);
  m.addEventListener("click", () => { clearTimeout(m._t); advance(); });  // click = next, same gesture as dismiss
}

function _floodParade(list) {
  const q = list.slice();
  const p = { q, m: null, ended: false };
  _parade = p;                                     // published so the exit can reach it
  let shown = 0;
  const step = () => {
    if (p.ended) return;                           // skipped: this parade is finished
    if (!q.length) { _clearTimer = setTimeout(_clearParade, 3200); return; }  // lingers, then bows out
    const a = q.shift(); shown++;
    const tier = a.tier || "common";
    _chime(tier);
    const built = _mkMoment(a, {});
    if (tier === "legendary" || tier === "feat") _fanfare(built.m, tier);
    p.m = built.m;
    _playFlood(built, step);
    if (shown > 1) {
      if (!_chip) { _chip = document.createElement("div"); _chip.className = "ach-trailchip"; document.body.appendChild(_chip); }
      _chip.textContent = "×" + shown + " earned";
      // The skip chip arrives with the counter, i.e. once it is demonstrably a parade and
      // not a single moment, and counts what SKIPPING would cost -- the pending queue.
      if (!_skip) _skip = _mkSkipChip();
      _skip.textContent = q.length ? ("skip ×" + q.length + " · Esc") : "skip · Esc";
    }
  };
  step();
}

function celebrate(a) { if (a) { _q.push(a); if (!_playing) _next(); } }
function _next() {
  if (!_q.length) { _playing = false; return; }
  _playing = true;
  const a = _q.shift(), tier = a.tier || "common";
  _chime(tier);
  const built = _mkMoment(a, {});
  if (tier === "legendary" || tier === "feat") _fanfare(built.m, tier);
  _play(built, HOLD[tier] || 4600, _next);
}

/* The old >3-unlock SUMMARY toast (showToast) is gone -- the trail parade replaced it
   outright (owner ruling 2026-09-03); nothing else consumed it. */

/* check(): the mark-and-toast pass -- fired on install (the old DOMContentLoaded auto-check)
   and after a real action completes (App.jsx onGenDone, submitTask). Exactly load(true). */
export function check() { load(true); }

/* replay(a, opts): re-plays the REAL celebration moment for an ALREADY-EARNED achievement, on
   demand. NOT routed through the _q/_next queue -- that queue is for real earn-events arriving
   together; a manual replay click is a single, immediate, user-driven action. opts.line forces
   the initial roast text (the Folio's ruby-scramble reveal starts from the CLEAN line on its own
   timing). Returns the driver handle useFolio.js consumes; {} if there is nothing to celebrate. */
export function replay(a, opts) {
  if (!a || !a.id) return {};
  opts = opts || {};
  // SERIALIZED against the parade. This path deliberately does not queue (a replay click
  // is immediate and hands its driver handle back synchronously), which meant a click
  // during a running parade opened a SECOND full-screen layer sharing the module-level
  // _trail/_chip -- two moments on screen at once, and whichever finished first tore down
  // the other's DOM. So the replay takes over instead of joining: any queued moments are
  // dropped, the parade's own teardown is cancelled, and its trail clears before this one
  // builds. Overlap is now impossible in either direction.
  // The takeover is THE EXIT, run for a different reason (2026-09-04): _endParade cancels
  // the linger timer and clears the trail exactly as the inline sequence here used to, and
  // additionally stops a parade still in FLIGHT -- whose pending moments and front layer
  // were out of this function's reach while they lived in _floodParade's closure.
  _q.length = 0;
  _playing = false;
  _endParade();
  const tier = a.tier || "common";
  _chime(tier);
  const built = _mkMoment(a, { eyebrow: "Achievement · Replay", line: opts.line });
  if (tier === "legendary" || tier === "feat") _fanfare(built.m, tier);
  _play(built, HOLD[tier] || 4600, null);
  const rEl = built.tw.querySelector(".toast .tbody .r");
  return {
    setText(text) { if (rEl) rEl.textContent = text; },
    setGlitching(on) { if (rEl) rEl.classList.toggle("glitch", !!on); },
    setSettledNsfw(on) { if (rEl) rEl.classList.toggle("settled-nsfw", !!on); },
    dismiss() { if (built.m && built.m.parentNode) built.m.click(); },
  };
}
