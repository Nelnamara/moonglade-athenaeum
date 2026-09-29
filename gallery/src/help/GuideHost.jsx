import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import useAccountPrefs from "../hooks/useAccountPrefs.js";
import useIsMobile from "../hooks/useIsMobile.js";
import {
  afterNote, afterTour, afterWelcome, firstPresentNote, guideKey, NOTES_HIDDEN_KEY,
  noteText, placeBeside, readGuide, rectShowing, tourSteps,
} from "./guideCore.js";
import { stepsFor } from "./guideSteps.js";
import {
  claimEscape, isTopSurface, pushSurface, subscribe as subscribeHelp, subscribeAbout,
  subscribeSurfaces,
} from "./helpStore.js";
import { replayCount, subscribeReplay } from "./guideActions.js";
import "../styles/help.css";

/* ONE SURFACE'S FIRST-RUN GUIDE (Session I decision 1; the handoff's section A).

   Rendered by the surface it guides, only while that surface is on screen:
     <GuideHost surface="gallery" />   App.jsx / AppMobile.jsx, the library
     <GuideHost surface="dock" />      App.jsx while the dock is open; the phone's Create tab
     <GuideHost surface="folio" />     the Folio, both layouts
     <GuideHost surface="panel" />     the Control Panel (Branding while its tab is showing)
     <GuideHost surface="loom" />      the Loom's root
   It registers the surface in helpStore's stack while mounted, and draws ONLY when it is
   the top of that stack -- a surface opened over another takes the guide with it -- and
   never while Help, About or the what's-new sheet is up. `paused` lets a host hold it
   while one of its own layers (a sub-overlay, a confirm) covers the surface.

   The three layers and the one key per surface are guideCore.js's; the steps are
   guideSteps.js's. Everything here is placement and events.

   NOTHING WRITES ON OPEN. The welcome card shows off an ABSENT key and writes only when it
   is answered. A tour writes only when it ends; a note only when its control is used or
   waved off. */

const SETTLE_MS = 900;          // a surface's own entrance plays out before the guide appears
const NOTE_POLL_MS = 600;       // how often a waiting note looks for its control
const NEL = "/branding/mascots/gen_nel.png";

function vp() {
  return { w: window.innerWidth || document.documentElement.clientWidth || 0,
           h: window.innerHeight || document.documentElement.clientHeight || 0 };
}

/* The first selector in `at` whose element is on screen, else null. */
export function findAnchor(step) {
  const list = Array.isArray(step.at) ? step.at : [step.at];
  const view = vp();
  for (const sel of list) {
    let el = null;
    try { el = document.querySelector(sel); } catch { el = null; }
    if (el && rectShowing(el.getBoundingClientRect(), view)) return el;
  }
  return null;
}

/* The phone keeps its cards above the tab bar when there is one, and above the home bar
   either way. */
function phoneFloor() {
  const nav = document.querySelector(".glm-nav");
  const r = nav ? nav.getBoundingClientRect() : null;
  return r && r.height ? Math.max(0, (window.innerHeight || 0) - r.top) : 0;
}

/* The desktop dock, when it is open, owns the bottom of the screen: cards sit above it. */
function dockTop() {
  const dock = document.querySelector(".mgx-dock-host.open .mgdock");
  const r = dock ? dock.getBoundingClientRect() : null;
  return r && r.height ? Math.max(0, (window.innerHeight || 0) - r.top) : 0;
}

function useHelpLayersUp() {
  const [up, setUp] = useState(false);
  useEffect(() => {
    let h = false, a = false;
    const u1 = subscribeHelp((s) => { h = s.open || s.closing; setUp(h || a); });
    const u2 = subscribeAbout((ab, sh) => {
      a = ab.open || ab.closing || sh.open || sh.closing;
      setUp(h || a);
    });
    return () => { u1(); u2(); };
  }, []);
  return up;
}

function Nel({ size }) {
  return <span className="mgguide-nel" aria-hidden="true"
    style={{ width: size, height: size, backgroundImage: "url('" + NEL + "')" }} />;
}

/* ---------------------------------------------------------------- ① the welcome card */
function Welcome({ guide, phone, onTour, onDone }) {
  const [bottom, setBottom] = useState(16);
  useLayoutEffect(() => {
    const measure = () => setBottom(phone ? phoneFloor() + 12 : Math.max(16, dockTop() + 16));
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [phone]);
  return (
    <div className={"mgguide-welcome" + (phone ? " phone" : "")} style={{ bottom }}
      role="dialog" aria-label={guide.welcome.title}>
      <Nel size={phone ? 44 : 54} />
      <div className="mgguide-wmain">
        <div className="mgguide-wtitle">{guide.welcome.title}</div>
        <div className="mgguide-wtext">{guide.welcome.body}</div>
        <div className="mgguide-wbtns">
          <button type="button" className="mgguide-ghost" onClick={onTour}>
            {phone ? "Show me" : "Show me around"}
          </button>
          <button type="button" className="mgguide-primary" onClick={onDone}>Got it</button>
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- ② the tour */
function Tour({ guide, phone, onEnd, restartKey }) {
  // The marks this tour can show: the list's tour prefix, less any whose control is not on
  // screen right now. `k` is the position in THAT list; `idx` maps it back to the full
  // step list, whose index the note cursor counts in.
  const [marks, setMarks] = useState(null);
  const [k, setK] = useState(0);
  const [rect, setRect] = useState(null);
  const cardRef = useRef(null);
  const [card, setCard] = useState({ w: phone ? 0 : 240, h: 110 });

  useEffect(() => {
    const all = tourSteps(guide.steps);
    const found = [];
    all.forEach((s) => {
      if (findAnchor(s)) found.push({ step: s, idx: guide.steps.indexOf(s) });
    });
    setMarks(found);
    setK(0);
  }, [guide, restartKey]);

  const tourCount = tourSteps(guide.steps).length;
  const end = useCallback((finished) => {
    const cur = marks && marks[k];
    const lastIdx = finished ? tourCount - 1 : (cur ? cur.idx : -1);
    onEnd(afterTour(lastIdx, tourCount));
  }, [marks, k, tourCount, onEnd]);

  useEffect(() => {
    if (marks && !marks.length) onEnd(afterTour(-1, tourCount));
  }, [marks, tourCount, onEnd]);

  // Escape skips the tour (under Help, which would take it first).
  useEffect(() => claimEscape(() => end(false)), [end]);

  // Follow the ringed control: one rect read a frame while the tour is up.
  useEffect(() => {
    if (!marks || !marks[k]) return undefined;
    let raf = 0;
    const tick = () => {
      const el = findAnchor(marks[k].step);
      const r = el ? el.getBoundingClientRect() : null;
      setRect((old) => {
        if (!r) return old;
        if (old && old.left === r.left && old.top === r.top && old.width === r.width && old.height === r.height) return old;
        return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
      });
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [marks, k]);

  useLayoutEffect(() => {
    const el = cardRef.current;
    if (!el) return;
    const b = el.getBoundingClientRect();
    if (Math.abs(b.height - card.h) > 1 || Math.abs(b.width - card.w) > 1) setCard({ w: b.width, h: b.height });
  });

  if (!marks || !marks.length || !marks[k] || !rect) return null;
  const view = vp();
  const pad = 4;
  const ring = { left: rect.left - pad, top: rect.top - pad, width: rect.width + 2 * pad, height: rect.height + 2 * pad };
  const last = k === marks.length - 1;
  const next = () => (last ? end(true) : setK(k + 1));

  let cardStyle;
  let docked = false;
  if (phone) {
    const floor = phoneFloor();
    const h = card.h || 140;
    // Docked as a sheet above the tab bar unless that would cover the ringed control;
    // then it floats just above the control instead.
    if (rect.bottom + 8 < view.h - floor - h) {
      docked = true;
      cardStyle = { left: 12, right: 12, bottom: floor + 8 };
    } else {
      cardStyle = { left: 12, right: 12, top: Math.max(12, rect.top - h - 14) };
    }
  } else {
    const p = placeBeside(rect, { w: 240, h: card.h || 110 }, view, 14);
    cardStyle = { left: p.left, top: p.top, width: 240 };
  }
  return (
    <>
      <div className="mgguide-block" onMouseDown={(e) => e.preventDefault()} />
      <div className="mgguide-ring" style={ring} />
      <div ref={cardRef} className={"mgguide-mark" + (phone ? " phone" : "") + (docked ? " docked" : "")}
        style={cardStyle} role="dialog" aria-label={"Step " + (k + 1) + " of " + marks.length}>
        <div className="mgguide-step">STEP {k + 1} OF {marks.length}</div>
        <div className="mgguide-marktext">{marks[k].step.tour}</div>
        <div className="mgguide-markbtns">
          <button type="button" className="mgguide-skip" onClick={() => end(false)}>
            {phone ? "Skip" : "Skip tour"}
          </button>
          <button type="button" className="mgguide-primary" onClick={next} autoFocus>
            {last ? "Done" : "Next"}
          </button>
        </div>
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- ③ Nel's notes */
function Notes({ guide, phone, n, onAdvance }) {
  const total = guide.steps.length;
  // "note 1 of 3" counts the notes still to come from where this run of them began -- after
  // a tour that is the controls it did not reach; after "Got it", every control.
  const [n0] = useState(n);
  const [j, setJ] = useState(-1);
  const [rect, setRect] = useState(null);
  const cardRef = useRef(null);
  const [cardH, setCardH] = useState(70);

  // Find the note to show, and keep its pin on its control.
  useEffect(() => {
    let live = true;
    const look = () => {
      if (!live) return;
      const at = firstPresentNote(guide.steps, n, (s) => !!findAnchor(s));
      setJ(at);
      const el = at >= 0 ? findAnchor(guide.steps[at]) : null;
      const r = el ? el.getBoundingClientRect() : null;
      setRect(r ? { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height } : null);
    };
    look();
    const t = setInterval(look, NOTE_POLL_MS);
    window.addEventListener("resize", look);
    window.addEventListener("scroll", look, true);
    return () => {
      live = false;
      clearInterval(t);
      window.removeEventListener("resize", look);
      window.removeEventListener("scroll", look, true);
    };
  }, [guide, n]);

  // "The next shows after you've used that control": any press, key or input inside it.
  useEffect(() => {
    if (j < 0) return undefined;
    let fired = false;
    const onUse = (e) => {
      if (fired) return;
      const el = findAnchor(guide.steps[j]);
      if (!el || !e.target || !el.contains(e.target)) return;
      fired = true;
      setTimeout(() => onAdvance(afterNote(j, total)), 500);
    };
    document.addEventListener("pointerdown", onUse, true);
    document.addEventListener("input", onUse, true);
    document.addEventListener("keydown", onUse, true);
    return () => {
      document.removeEventListener("pointerdown", onUse, true);
      document.removeEventListener("input", onUse, true);
      document.removeEventListener("keydown", onUse, true);
    };
  }, [guide, j, total, onAdvance]);

  useLayoutEffect(() => {
    const el = cardRef.current;
    if (!el) return;
    const h = el.getBoundingClientRect().height;
    if (h && Math.abs(h - cardH) > 1) setCardH(h);
  });

  if (j < 0 || !rect) return null;
  const view = vp();
  const dot = { left: Math.round(rect.right - 5), top: Math.round(rect.top - 4) };
  let cardStyle;
  if (phone) {
    cardStyle = { left: 12, right: 12, bottom: phoneFloor() + 12 };
  } else {
    const p = placeBeside(rect, { w: 250, h: cardH }, view, 12);
    cardStyle = { left: p.left, top: p.top, width: 250 };
  }
  return (
    <>
      <span className="mgguide-dot" style={dot} aria-hidden="true" />
      <div ref={cardRef} className={"mgguide-note" + (phone ? " phone" : "")} style={cardStyle} role="note">
        <Nel size={phone ? 32 : 28} />
        <div className="mgguide-nmain">
          <div className="mgguide-ntext">{noteText(guide.steps[j])}</div>
          {phone ? null : (
            <div className="mgguide-nfoot">
              <span>note {j - n0 + 1} of {total - n0}</span>
              <span className="sp" />
              <button type="button" className="mgguide-gotit" onClick={() => onAdvance(afterNote(j, total))}>got it</button>
            </div>
          )}
        </div>
        {phone ? (
          <button type="button" className="mgguide-gotit phone" onClick={() => onAdvance(afterNote(j, total))}>got it</button>
        ) : null}
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- the host */
export default function GuideHost({ surface, phone, paused }) {
  const isMobile = useIsMobile();
  const ph = phone == null ? isMobile : !!phone;
  const guide = stepsFor(surface, ph);
  const { ready, get, set } = useAccountPrefs();
  const [top, setTop] = useState(false);
  const [settled, setSettled] = useState(false);
  const [restart, setRestart] = useState(replayCount());
  const helpUp = useHelpLayersUp();

  useEffect(() => {
    const pop = pushSurface(surface);
    const sync = () => setTop(isTopSurface(surface));
    sync();
    const unsub = subscribeSurfaces(sync);
    return () => { unsub(); pop(); };
  }, [surface]);
  useEffect(() => subscribeReplay((n) => setRestart(n)), []);

  const raw = ready ? get(guideKey(surface)) : null;
  const st = readGuide(raw);
  // Each new layer waits for the surface to settle before it appears.
  const phaseKey = st.phase + ":" + st.n + ":" + restart;
  useEffect(() => {
    setSettled(false);
    const t = setTimeout(() => setSettled(true), SETTLE_MS);
    return () => clearTimeout(t);
  }, [phaseKey]);

  const write = useCallback((v) => { set(guideKey(surface), v); }, [set, surface]);

  if (!guide || !ready || !top || paused || helpUp || !settled) return null;
  let layer = null;
  if (st.phase === "welcome") {
    layer = <Welcome guide={guide} phone={ph} onTour={() => write(afterWelcome("tour"))}
      onDone={() => write(afterWelcome("gotit"))} />;
  } else if (st.phase === "tour") {
    layer = <Tour guide={guide} phone={ph} onEnd={write} restartKey={restart} />;
  } else if (st.phase === "notes" && !get(NOTES_HIDDEN_KEY, false)) {
    layer = <Notes guide={guide} phone={ph} n={st.n} onAdvance={write} />;
  }
  if (!layer) return null;
  return createPortal(<div className="mgguide-root" data-surface={surface}>{layer}</div>, document.body);
}
