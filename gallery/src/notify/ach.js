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

/* ---- BESPOKE MOMENTS (owner ruling 2026-09-10) -----------------------------------------
   A couple of feats have a celebration of their own, and a bespoke moment REPLACES the
   generic flair rather than layering on it. Two rules, both enforced here rather than at
   the call sites so that a new caller cannot forget one:

     1. While a bespoke moment owns the screen, this module builds NOTHING, so the standard
        achievement toast plays AFTER the bespoke moment. On a FIRST earn the two cannot
        share the screen at all -- the moment's DOM has not been built yet, which is overlap
        made impossible by construction rather than by two timers happening to miss each
        other.
        The hold is ONE GATE ON ONE DEQUEUE. Every moment this module can put on screen --
        a queued earn, a parade step, a Folio replay -- is an entry in _q, and _drain() is
        the only function that builds one; hold _drain and nothing reaches the screen.
        NO CALLER IS EXEMPT. A Folio replay used to be, on the grounds that a click has to
        hand its driver handle back synchronously and a parked entry could only return a
        dead one -- so a replay clicked during a cast opened .ach-m2 (z-index 520) straight
        over it. An exemption is a door left ajar, and one door ajar is the whole invariant;
        the handle waits WITH the entry instead and drives the moment the dequeue eventually
        builds (see replay() and _driver below).
        An earlier mechanism parked CONTINUATIONS instead (one from the celebration's front
        door, one from the queue's own re-entry, one from the parade's step) and replayed
        them on release. Three parked closures draining in a row is three callers racing to
        build, and the "a moment is playing" flag had to be lowered while they were parked,
        so a release could start a second moment over one still on screen. Replaced, not
        patched: there is no flag to lower now, only _cur -- the element being presented --
        and a dequeue that refuses while it is set.
        The REVERSE direction is closed by whenClear() below: a cast that would otherwise
        paint UNDER something already on screen waits for the screen to be empty first.
     2. An achievement in BESPOKE_FEATS never gets _fanfare ON AN EARN: its own moment IS
        the fanfare. A Folio REPLAY is not that moment (replay builds the standard moment
        and casts nothing), so suppressing there would leave a celebration thinner than the
        one that shipped before this rule, with nothing replacing it -- the replay keeps its
        ordinary feat fanfare. "Never layer flair over a moment that is on screen" is not a
        second gate any more: rule 1 means nothing is BUILT while one owns the screen, so
        there is no celebration here for flair to ride on.

   Deliberately pure module state: BOTH hosts load this file and the Loom has none of the
   gallery's bespoke-moment DOM or CSS, so nothing here may read an element, a class or a
   stylesheet -- the owner of a moment tells us it started and tells us it ended. */
export const BESPOKE_FEATS = new Set(["the-konami-code", "under-the-hood"]);

let _bespoke = 0;                // depth, not a bool: two moments may overlap and compose
let _pendingDrain = false;       // the dequeue was asked to run while the gate was closed
const _whenClear = [];           // callers waiting for the celebration layer to be EMPTY

/* THE LAYER LEDGER. Everything this module paints is body-level and sits ABOVE the cast's
   own layer -- a moment .ach-m2 at z-index 520, the parade's two chips at 519/521, against
   .ee-layer's 449 -- so "the celebration layer is clear" has to mean the DOM is empty of
   all of it. A receded trail card is not a moment, but it is still four dimmed cards
   painted over a starfall. Every append goes through _mount and every removal through
   _unmount, so the ledger cannot drift from the DOM; the module still reads no element,
   class or stylesheet, it only counts what it put there itself. */
const _live = new Set();
function _mount(el) { _live.add(el); document.body.appendChild(el); }
function _unmount(el) {
  _live.delete(el);
  if (el.parentNode) el.remove();
  _flushClear();
}

/* THE GATE, as one predicate. The dequeue is held while a bespoke moment owns the screen,
   and while a cast is WAITING to take it -- that cast is about to arm, and building one
   more moment in front of it is the same overlap one link earlier in the chain. */
function _heldOff() { return _bespoke > 0 || _whenClear.length > 0; }

/* THE ONE RELEASE. Both holds lift through here, and it calls the dequeue exactly once.
   _drain carries its own "is a moment on screen" check, so a release that lands while
   something is still presenting cannot start a second one -- the release does not need to
   know, and cannot get it wrong. */
function _resume() {
  if (_heldOff()) return;
  if (!_pendingDrain) return;    // the queue never asked; there is nothing parked
  _pendingDrain = false;
  _drain();
}

export function beginBespokeMoment() { _bespoke++; }
export function endBespokeMoment() {
  if (_bespoke > 0) _bespoke--;
  _resume();
}

/* whenClear(fn): the reverse direction of the hold. The hold keeps a moment off a cast that
   is already up; this keeps a cast off anything that is already up. fn runs immediately when
   the layer is empty, otherwise the instant the last thing on it has left the DOM -- and it
   runs BEFORE the dequeue does (see _settled), so a caller that arms its hold inside fn
   catches the next queued moment rather than racing it.

   "Empty" is the DOM, not the queue. Treating a parade's receded trail as clear was the
   reverse direction left half-open: those cards keep .ach-m2's z-index 520 over the cast's
   449, and while a hold was armed they could not even time out. Waiting for the whole parade
   instead would delay a cast by every earn still in it, so a waiting cast does not wait for
   presented history -- _flushClear takes it down (_hush). What a cast waits for is the
   moment actually being presented, plus the 500ms that history takes to fade. */
export function whenClear(fn) {
  if (typeof fn !== "function") return;
  if (!_cur && !_live.size) { fn(); return; }
  _whenClear.push(fn);
  _flushClear();                 // nothing presenting, only history? then start taking it down
}

/* The one place waiting casts are fired, reached from every removal (_unmount) and from the
   teardown that clears _cur (_settled). Three states, in order: a moment is presenting, so
   wait; only presented history is left, so take it down and wait for its fade; the screen is
   empty, so fire -- and only then let the dequeue run again. */
function _flushClear() {
  if (!_whenClear.length) return;
  if (_cur) return;
  if (_live.size) {
    // Taking a drained parade's history down for a waiting cast also cancels its linger:
    // with the trail gone, a still-armed timer would keep _paradeUp() claiming Escape for
    // the rest of the 3.2s while only the cast is on screen. The parade record itself stays
    // (its pending moments are flood entries the dequeue would drop as stale otherwise);
    // the linger re-arms after its next moment plays, as it always does.
    _cancelLinger();
    _hush();
    return;
  }
  _whenClear.splice(0).forEach((fn) => { try { fn(); } catch { /* a cast's own problem */ } });
  _resume();
}

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
/* THE ONE QUEUE. Every moment that can reach the screen is an entry here and _drain() is the
   only function that builds one, which is what makes a single hold enough.
   `_cur` -- the element being presented -- is the serialization: _drain refuses while it is
   set, and the teardown that clears it is what re-enters _drain. "At most one moment on
   screen" is therefore the presence of a DOM node, not a boolean somebody has to remember to
   lower; the "a moment is playing" flag this replaced was lowered in four places, and the
   one that lowered it while the moment was still on screen is the bug that got us here. */
const _q = [];                   // pending entries: {a, flood?, replay?, opts?, drive?, built?}
let _cur = null;                 // the .ach-m2 element being presented right now, or null
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

/* THE ONE PLACE THAT DECIDES WHETHER THE FANFARE FIRES. All three moments that can carry
   it -- the parade step, the queue, the Folio replay -- call this and never _fanfare
   directly, because "suppress it for the bespoke feats" written out three times is
   "suppress it for the bespoke feats" forgotten once: a feat earned in a >3 flood would
   still blow confetti over a celebration that is supposed to replace it.

   ONE suppression, where there used to be two. An EARN of a bespoke feat is quiet because
   its own moment is its fanfare, so the standard toast that follows the cast arrives
   without confetti. `opts.replay` is what separates that from the Folio, where the owner
   clicks an already-earned card: replay() builds the standard moment and casts NOTHING, so
   gating it there would make that card's celebration thinner than it was before this rule
   with nothing put in its place.
   The gate that used to stand first here -- "a bespoke moment is on screen, never layer on
   it" -- is gone because it can no longer fire: the dequeue builds nothing at all while one
   owns the screen, so there is no celebration in this function to decorate. It was load-
   bearing only while the Folio replay had an exemption from that gate, and the exemption is
   what went. A guard that cannot run is a guard nobody can check. */
function _flair(built, a, opts) {
  if (BESPOKE_FEATS.has(a.id) && !(opts && opts.replay)) return;   // the earn: its own moment is the fanfare
  const tier = a.tier || "common";
  if (tier === "legendary" || tier === "feat") _fanfare(built.m, tier);
}

/* THE ONE TEARDOWN HOOK. A moment stops being presented in exactly three ways -- _play
   removes it, _playFlood recedes it into the trail, the exit fades it out -- and all three
   land here, each of them only once the element is no longer a moment on screen. Nothing
   else clears _cur, so nothing else can let a second moment be built. */
function _settled(m) {
  if (_cur !== m) return;        // a replay already took the layer over; that one owns it
  _cur = null;
  // The waiting cast goes FIRST and the dequeue second: the cast arms its hold inside its
  // callback, so running it first is exactly what stops the next queued moment from being
  // built over it. Reversed, the two would race and the order would be luck.
  _flushClear();
  _drain();
}

function _play(built, hold) {
  const m = built.m, tw = built.tw;
  _mount(m);
  void m.offsetWidth;
  m.classList.add("go"); tw.classList.add("go");
  const done = () => {
    if (m._d) return;
    m._d = true;
    m.classList.add("out");
    // REMOVED from the DOM before the queue is told the layer is free, so the next moment is
    // built into an empty layer instead of across the .out fade of the one before it.
    setTimeout(() => { _unmount(m); _settled(m); }, 500);
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
    setTimeout(() => _unmount(old), 500);
  }
}

/* The pending "the trail bows out" timer, held so it can be CANCELLED. Without the handle a
   replay that starts while a parade is winding down inherits the parade's 3.2s timer, which
   then rips the replay's own trail and chip out of the DOM mid-moment.

   THE TIMER BELONGS TO WHICHEVER PARADE IS LIVE, and what keeps that true is that every
   place which publishes or drops a parade takes the handle with it -- _floodParade,
   _endParade and the takeover, all through this one function. Left behind, a superseded
   parade's timer reaches _clearParade with a DIFFERENT parade live and nulls it, and
   _drain's stale-flood guard (`!_parade || _parade.ended`) then shifts every one of THAT
   parade's pending entries off the queue and drops them -- first earns whose marks the
   server has already consumed, gone with no toast and no error -- while the same teardown's
   _hush rips the live parade's trail and chips off screen mid-parade. (It is also the handle
   the arm in _drain waits on, so a timer left behind stops the new parade ever arming one of
   its own, and that parade then never bows out at all.)
   Keyed to the parade instead -- a timer that checks it is still the live one before firing
   -- the same hole stays shut, and this module has one rule about the difference: a guard
   that cannot run is a guard nobody can check. Cancelling AT the three places is reachable
   from every one of them, and loom/test/starfall-spec.test.js pins all three. */
let _clearTimer = null;
function _cancelLinger() {
  if (_clearTimer) { clearTimeout(_clearTimer); _clearTimer = null; }
}

/* The LIVE parade, or null when none is on screen: {m, ended}. `m` is the moment currently
   front-and-centre. Its PENDING moments are not here any more -- they are flood-tagged
   entries in the one _q, which is what makes "the parade is a second door onto the screen"
   untrue by construction rather than by a guard in its step loop.
   Holding this at module scope is what lets THE EXIT below reach a parade already in flight;
   the flood's list used to live only inside _floodParade's closure, where nothing outside
   could stop it (not even replay()'s takeover, which cleared _q and the trail but left the
   flood happily stepping on behind the replay's own moment). */
let _parade = null;
let _paradeShown = 0;          // how many of this parade's moments have presented

/* Take the parade's presented HISTORY off the screen -- the receded trail and the two chips
   -- WITHOUT ending the parade: its pending moments are entries in _q and are still its own.
   THE ONE REMOVAL LOOP: natural end, replay()'s takeover, the exit and a waiting cast all
   reach the trail through this function and nothing else, so there is no second path to
   race it. (A second loop removing the same DOM, whichever finished first winning, is
   exactly how the replay/parade overlap bug worked.) */
function _hush() {
  _trail.splice(0).forEach((el) => {
    el.classList.add("out");
    setTimeout(() => _unmount(el), 500);
  });
  [_chip, _skip].forEach((c) => {
    if (!c) return;
    c.classList.add("out");
    setTimeout(() => _unmount(c), 500);
  });
  _chip = null; _skip = null;
}

// THE ONE TEARDOWN. The natural end (through the linger armed above) and the exit both land
// here; nothing else ends a parade with history still on screen, so there is no second path
// to race this one. It always ends whichever parade is LIVE, which is only safe because a
// superseded parade's linger is cancelled the moment it is superseded (see _cancelLinger).
function _clearParade() {
  _clearTimer = null;
  _parade = null;
  _hush();
}

/* ---- THE EXIT (owner ruling 2026-09-04, DECISIONS.md "The achievement parade gets an
   exit"): a long parade is skippable -- Escape, or the skip chip beside the counter.

   PRESENTATION ONLY. The earns were already recorded server-side by the
   /api/achievements?mark=1 load that produced this list (load() -> toastNew()); a moment in
   the step loop below is a chime plus DOM and nothing else -- it marks nothing, posts
   nothing, grants nothing. The reward a badge announces (a skin, a banner) is granted with
   the earn and applied from the same payload by syncSkin(), not by the moment. So an
   achievement whose moment never played is earned exactly like one that was watched.

   The moment on screen fades instead of vanishing mid-frame -- through the same .out class,
   on the same 500ms, as the click-dismiss that has always shipped -- and the queue is told
   the layer is free only once that element has actually LEFT THE DOM, exactly as _play does
   it. Telling it earlier is what put a celebration queued behind the parade on screen
   across the skipped moment's fade: two full-screen .ach-m2 scrims at once, which is the
   one thing this layer must never do. Then _clearParade takes the rest down. No second
   teardown, nothing new for the existing ones to race. */

/* A parade is UP when part of it is ON THE SCREEN: its front moment presenting, its history
   still there, or the linger before it bows out. _parade is published at ENQUEUE time so the
   exit can reach a parade whose moments are still queued -- but a parade with nothing on
   screen yet must not swallow Escape. Held behind a bespoke moment it would otherwise eat
   the key while the owner was looking at a different layer entirely, and the exit would
   discard the whole held flood on the way past. */
function _paradeUp() {
  if (_trail.length || _clearTimer) return true;
  return !!(_parade && _parade.m && _parade.m === _cur);
}

function _endParade() {
  const p = _parade;
  if (p) {
    p.ended = true;                 // this parade is over, whatever timer fires next
    // Its pending moments live in the ONE queue now, so skipping the parade means dropping
    // its entries from there -- and ONLY its entries. A plain celebration waiting behind
    // them is not part of what the owner asked to skip.
    for (let i = _q.length - 1; i >= 0; i--) if (_q[i].flood) _q.splice(i, 1);
    const m = p.m;
    // A false _adv is the tell that the front moment has NOT receded: it is still the moment
    // being presented, so it fades from where it stands and stays _cur until it is gone.
    if (m && !m._adv) {
      clearTimeout(m._t);
      m._adv = true; m._d = true;   // its own dwell and its click can no longer advance it
      m.classList.add("out");
      setTimeout(() => { _unmount(m); _settled(m); }, 500);
    }
  }
  _cancelLinger();
  _clearParade();
  // Re-enter the one dequeue for anything the skip did NOT touch -- a plain celebration
  // queued behind the parade. It refuses while a moment is still on screen (refusal 1), so
  // the skipped moment's own _settled is what actually lets that one build.
  _drain();
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
  _mount(b);
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

function _playFlood(built) {
  const m = built.m, tw = built.tw;
  _mount(m);
  void m.offsetWidth;
  m.classList.add("go"); tw.classList.add("go");
  const advance = () => {
    if (m._adv) return;
    m._adv = true;
    _recede(m);                    // presented history from here on, not a moment presenting
    _settled(m);
  };
  m._t = setTimeout(advance, FLOOD_DWELL_MS);
  m.addEventListener("click", () => { clearTimeout(m._t); advance(); });  // click = next, same gesture as dismiss
}

/* A flood ENQUEUES; it does not run a loop of its own. Every moment it will ever show is an
   entry in the one queue, so the hold that covers a celebration covers the parade -- at its
   start and at every step, because start and step are the same code path. */
function _floodParade(list) {
  // Published before anything is built so the exit can reach a parade whose moments are all
  // still queued. `m` stays null until the dequeue actually presents one, and _paradeUp()
  // reads it: a parade that is only an intention does not own Escape.
  // A new flood SUPERSEDES whatever parade came before it, so that parade's linger goes with
  // it. Left running, the timer fires INSIDE this parade, ends a parade it was never armed
  // for, and takes this one's pending first earns off the queue with it (see _cancelLinger).
  // Cancelling is also what lets this parade arm a linger of its own when its queue runs dry.
  _cancelLinger();
  _parade = { m: null, ended: false };
  _paradeShown = 0;
  list.forEach((a) => _q.push({ a, flood: true }));
  _drain();
}

function celebrate(a) {
  if (!a) return;
  _q.push({ a });
  _drain();
}

/* THE ONE DEQUEUE, and the only place in this module that builds a moment.
   Three refusals, in this order:
     1. a moment is already being presented -> return. Its teardown re-enters through
        _settled; a second entry point is the whole class of bug this replaced.
     2. nothing pending -> if a parade is draining, it lingers and then bows out. This sits
        AHEAD of the gate on purpose: it builds nothing, and a parade whose queue has run dry
        has to be able to bow out while a bespoke moment holds the screen. Behind the gate,
        its trail sat over the cast for the cast's whole life and 3.2s past its release,
        because the only line that arms the linger timer was never reached.
     3. the gate is closed -> record that the queue wants to run and build NOTHING. This is
        THE hold, written once, for every entry and every caller. _resume() calls back into
        this same function, so a release that arrives while something is still presenting is
        caught by refusal 1 rather than by the release having to know about it. */
function _drain() {
  if (_cur) return;
  // A skipped parade splices its own entries out, so this only ever catches a stale one.
  while (_q.length && _q[0].flood && (!_parade || _parade.ended)) _q.shift();
  if (!_q.length) {
    if (_parade && !_parade.ended && !_clearTimer) _clearTimer = setTimeout(_clearParade, 3200);
    return;
  }
  if (_heldOff()) { _pendingDrain = true; return; }
  const e = _q.shift();
  const a = e.a, tier = a.tier || "common";
  _chime(tier);
  const built = e.replay
    ? _mkMoment(a, { eyebrow: "Achievement · Replay", line: (e.opts || {}).line })
    : _mkMoment(a, {});
  // `replay: true` -- see _flair. A replay casts no bespoke moment, so a bespoke feat's Folio
  // card keeps the ordinary feat fanfare.
  _flair(built, a, e.replay ? { replay: true } : undefined);
  if (e.replay) _bind(e, built);   // the handle handed back at click time finds its element
  _cur = built.m;
  if (e.flood) {
    _parade.m = built.m;
    _paradeShown++;
    _playFlood(built);
    if (_paradeShown > 1) {
      if (!_chip) { _chip = document.createElement("div"); _chip.className = "ach-trailchip"; _mount(_chip); }
      _chip.textContent = "×" + _paradeShown + " earned";
      // The skip chip arrives with the counter, i.e. once it is demonstrably a parade and
      // not a single moment, and counts what SKIPPING would cost -- this parade's share of
      // the queue, never a celebration queued behind it that the skip does not touch.
      if (!_skip) _skip = _mkSkipChip();
      const left = _q.reduce((n, x) => n + (x.flood ? 1 : 0), 0);
      _skip.textContent = left ? ("skip ×" + left + " · Esc") : "skip · Esc";
    }
  } else {
    _play(built, HOLD[tier] || 4600);
  }
}

/* The old >3-unlock SUMMARY toast (showToast) is gone -- the trail parade replaced it
   outright (owner ruling 2026-09-03); nothing else consumed it. */

/* check(): the mark-and-toast pass -- fired on install (the old DOMContentLoaded auto-check)
   and after a real action completes (App.jsx onGenDone, submitTask). Exactly load(true). */
export function check() { load(true); }

/* A Folio replay TAKES THE SCREEN OVER on its way into the queue. What that means is exactly
   two things and no more: the moment being PRESENTED is removed OUTRIGHT rather than faded
   (a .out fade is 500ms a click does not have), and the parade's PRESENTED history -- the
   receded trail and its two chips -- goes with it, through _hush, the one removal loop.

   What a takeover must NEVER touch is anything still PENDING. Every entry in _q is a first
   earn whose mark the server has already consumed (the /api/achievements?mark=1 load that
   produced the list), so a toast dropped here is a celebration the owner can never get back
   -- and that includes a parade's remaining steps, which is why this does NOT run THE EXIT.
   _endParade splices the flood's own entries out of the queue, and that is the owner asking
   for it (Escape, the skip chip), not a side effect of clicking a card. The replay goes to
   the FRONT of the queue instead (see replay()) and the rest of the queue plays after it.

   And it finishes through _settled -- the same settle path _play, _playFlood and the exit all
   land on: the element leaves the DOM FIRST, then _cur is nulled, then the casts waiting on
   whenClear are flushed, then the dequeue is re-entered. Nulling _cur after an _unmount that
   ran while it was still set is what stranded a waiting cast: the flush _unmount fired saw a
   moment presenting and returned, nothing ever flushed again, and _heldOff() stayed true for
   the rest of the session -- no starfall, no replay, no celebration, in silence. */
function _takeover() {
  _hush();                        // the presented trail and the parade's chips, one loop
  // A parade whose queue has run dry has nothing left but the history just taken down, so it
  // ends here rather than lingering: the linger still owns Escape (_paradeUp), and while a
  // replay is up Escape belongs to the Folio. A parade with steps still pending keeps both
  // its entries and its identity, and resumes behind the replay.
  if (!_q.some((x) => x.flood)) {
    _cancelLinger();
    _parade = null;
  }
  const m = _cur;
  if (m) {
    clearTimeout(m._t);
    m._d = true; m._adv = true;   // its own dwell and its click can no longer reach _settled
    _unmount(m);                  // out of the DOM BEFORE _cur is nulled, so that...
  }
  // ...the flush inside the one settle path sees a layer this function has already emptied.
  // With nothing presenting (m and _cur both null) it is still that same path: null _cur,
  // flush the casts waiting on whenClear, then re-enter the dequeue.
  _settled(m);
}

/* THE REPLAY DRIVER, bound to the QUEUE ENTRY rather than to an element. useFolio starts
   driving the scramble reveal the instant replay() returns, and the entry it is driving may
   not be on screen yet -- a replay clicked while a bespoke moment owns the screen waits its
   turn like everything else, because an exemption there is a door left ajar (rule 1).
   So the handle records what it was told and _bind replays that onto the moment the dequeue
   eventually builds: the celebration arrives on the line the scramble settled at, instead of
   on a half-scrambled one or on nothing at all. The handle is always a REAL object with all
   four methods -- useFolio spreads it and calls them unguarded -- which is why a queued
   entry may never hand back a bare {}. */
function _driver(e) {
  const r = () => (e.built ? e.built.tw.querySelector(".toast .tbody .r") : null);
  return {
    setText(text) { e.drive.text = text; const x = r(); if (x) x.textContent = text; },
    setGlitching(on) { e.drive.glitch = !!on; const x = r(); if (x) x.classList.toggle("glitch", !!on); },
    setSettledNsfw(on) { e.drive.nsfw = !!on; const x = r(); if (x) x.classList.toggle("settled-nsfw", !!on); },
    dismiss() {
      if (e.built) { if (e.built.m && e.built.m.parentNode) e.built.m.click(); return; }
      const i = _q.indexOf(e);   // never reached the screen: it leaves the queue instead
      if (i >= 0) _q.splice(i, 1);
    },
  };
}
function _bind(e, built) {
  e.built = built;
  const x = built.tw.querySelector(".toast .tbody .r");
  if (!x) return;
  if (e.drive.text != null) x.textContent = e.drive.text;
  x.classList.toggle("glitch", !!e.drive.glitch);
  x.classList.toggle("settled-nsfw", !!e.drive.nsfw);
}

/* replay(a, opts): re-plays the REAL celebration moment for an ALREADY-EARNED achievement, on
   demand. It goes through the ONE queue like every other moment -- serialized by the same
   _cur, held by the same one gate -- and takes the SCREEN over on its way in (see _takeover).
   It goes to the FRONT of that queue rather than the back, which is what "the click is
   immediate" can honestly mean once dropping the queue is off the table: the replay is the
   next thing built, and the earns already waiting keep their turn behind it.
   Held is not the same as immediate. While a bespoke moment owns the screen -- or while a
   cast waits for the screen -- the entry waits with everything else and plays when the gate
   lifts, driven the whole time by the handle above; the exemption this used to carry put a
   .ach-m2 at z-index 520 over a cast at 449, which is the overlap owner ruling 2026-09-10
   rules out in BOTH directions.
   opts.line forces the initial roast text (the Folio's ruby-scramble reveal starts from the
   CLEAN line on its own timing). Returns the driver handle useFolio.js consumes; {} only when
   there is nothing to celebrate at all. */
export function replay(a, opts) {
  if (!a || !a.id) return {};
  const e = { a, opts: opts || {}, replay: true, drive: {} };
  _q.unshift(e);                 // the front of the queue, ahead of the earns already waiting
  _takeover();                   // and it finishes through _settled, which re-enters the one
  return _driver(e);             // dequeue -- so there is no second _drain() here to race it
}
