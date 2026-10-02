import React, { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import {
  FADE_OUT_MS, LOAD_CEILING_MS, SCENES, STILL, clipEndOf, clipTime, cuesFrom, fitSafe, fitStage,
  needsSeek, startClock, stepClock,
} from "./momentCore.js";
import { FADE_OUT, keyturnFrame, pieceFade, starfallFrame } from "./scenes.js";
import { attachMoment, finishMoment, setMomentVisible } from "./momentStore.js";
import { carryPanelTab, openPanelHere } from "../notify/panelRequest.js";
import { PANEL_TABS } from "../lib/panelTabs.js";
import "../styles/moments.css";

/* ONE STAGE, ONE CLOCK -- the clip moment (the celebration-videos build).

   A moment is a video clip with a UI ceremony over it, rendered exactly as its locked Design
   Handoff page renders it: a 1920 x 1080 stage, every overlay value a pure function of the
   authored clock T (scenes.js), T taken from the VIDEO while it plays (momentCore.stepClock)
   so the overlay stays registered to the picture. Two layers (review amendment 4): the stage
   -- clip, flares, stars -- scales as one unit (cover in landscape, contain in portrait), and
   the UI -- keycaps, rail, toast, caption, button -- sits in a contain-fitted safe box at the
   same coordinates, with a minimum type size on small screens.

   What a moment does, in order:
     load    the clip is fetched only now (lazy: it is never in a bundle) and nothing shows
             until it can play through; a clip that never can within LOAD_CEILING_MS, or
             errors, falls back instead of just ending.
     play    video.play() with sound; a browser that refuses unmuted autoplay gets the clip
             muted and a small 🔊 chip that unmutes it. The chip is not a skip.
     end     the page's own fade to dark, then a short fade of the whole moment (FADE_OUT_MS)
             and the store is told -- which is what lets the feat's standard toast play.
     skip    Escape (momentStore's guard) or a click anywhere ends it early with the same
             short fade. The button is not a skip: it ends the moment and takes the owner to
             the Control Panel's Branding tab.
   Reduced motion, and a clip that cannot play, draw the overlay at its settled state (no
   flare, no stars, no keycap motion) over one still -- or, with no video at all, over the
   dark ground -- for the moment's own length; the starfall's no-video fallback plays its two
   recorded tracks with it (momentCore STILL, review amendment 11).

   THE HARNESS SEEK (review amendment 14): only when an init script has set
   window.__MG_MOMENT_HARNESS = true before load does a MOUNTED moment expose
   window.__mgMomentSeek(T) -> Promise, resolved once the frame at T is rendered (after the
   video's `seeked`, when its time actually had to change -- the page's own 20 ms rule). It
   freezes the moment on that frame and can never mount one. Under the same flag the
   greeting uses its fallback name, so the parity pass compares the page's own words. */

const FALLBACK_NAME = "Nelnamara";
const STARFALL_TRACKS = [
  { src: "/branding/ee_starfall_cast.ogg", volume: 0.7, loop: false },
  { src: "/branding/ee_starfall_loop.ogg", volume: 0.35, loop: true },
];

function harnessOn() {
  return typeof window !== "undefined" && window.__MG_MOMENT_HARNESS === true;
}

/* "Elune-adore, <name>": the signed-in account's name as the app already carries it
   (window.MG_BOOT.user), with the design's own fallback. */
function greeting() {
  const boot = (typeof window !== "undefined" && window.MG_BOOT) || {};
  const name = harnessOn() ? FALLBACK_NAME : (String(boot.user || "").trim() || FALLBACK_NAME);
  return "✺ Elune-adore, " + name + " ✺";
}

function prefersReducedMotion() {
  try { return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches); }
  catch { return false; }
}

function viewport() {
  if (typeof window === "undefined") return { w: 1920, h: 1080 };
  return { w: window.innerWidth || 1920, h: window.innerHeight || 1080 };
}

function once(el, type, ms) {
  return new Promise((resolve) => {
    let t = 0;
    const done = () => { clearTimeout(t); el.removeEventListener(type, done); resolve(); };
    el.addEventListener(type, done);
    t = setTimeout(done, ms || LOAD_CEILING_MS);
  });
}
const twoFrames = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

/* A <button> that looks like the page's pill and nothing else: the app's own button rules
   (font: inherit, the focus ring) must not reshape it. */
const BUTTON_RESET = {
  border: "none", margin: 0, cursor: "pointer", fontFamily: "inherit", lineHeight: "normal",
  letterSpacing: "normal", textTransform: "none", WebkitAppearance: "none", appearance: "none",
  pointerEvents: "auto",
};

export default function ClipMoment({ moment }) {
  const { id, kind, a } = moment;
  const achievement = a || {};
  const copy = achievement.moment_copy || {};
  const clip = String(achievement.moment_clip || "");
  const [{ cues, total }] = useState(() => cuesFrom(SCENES[kind]));
  const [reduced] = useState(prefersReducedMotion);
  const [greet] = useState(greeting);

  // loading -> play | still | fallback; frozen once the harness seeks
  const [mode, setMode] = useState(clip ? "loading" : "fallback");
  const [shown, setShown] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [T, setT] = useState(0);
  const [wall, setWall] = useState(0);
  const [needsSound, setNeedsSound] = useState(false);
  const [vp, setVp] = useState(viewport);

  const videoRef = useRef(null);
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const frozenRef = useRef(false);     // the harness has seeked: no clock, no ceiling, no exit of its own
  const clockRef = useRef(null);
  const rafRef = useRef(0);
  const wallAtRef = useRef(0);
  const doneRef = useRef(false);
  const tracksRef = useRef([]);
  const timersRef = useRef([]);

  const later = (fn, ms) => { const t = setTimeout(fn, ms); timersRef.current.push(t); return t; };

  const stopMedia = () => {
    cancelAnimationFrame(rafRef.current);
    const v = videoRef.current;
    if (v) { try { v.pause(); } catch { /* gone */ } }
    tracksRef.current.forEach((au) => { try { au.pause(); } catch { /* gone */ } });
    tracksRef.current = [];
  };

  /* THE ONE EXIT. Every way a moment ends lands here exactly once: the short fade, then the
     store is told (and the hold on the standard toast lifts), then -- for the button on a
     shell with no Control Panel -- whatever has to happen once the moment is gone. */
  const finish = (reason, after) => {
    if (doneRef.current) return;
    doneRef.current = true;
    stopMedia();
    setLeaving(true);
    later(() => {
      finishMoment(id, reason);
      if (after) after();
    }, modeRef.current === "loading" ? 0 : FADE_OUT_MS);
  };
  const finishRef = useRef(finish);
  finishRef.current = finish;

  const playTracks = () => {
    if (kind !== "starfall" || tracksRef.current.length) return;
    STARFALL_TRACKS.forEach((t) => {
      try {
        const au = new Audio(t.src);
        au.volume = t.volume;
        au.loop = t.loop;
        au.play().catch(() => {});
        tracksRef.current.push(au);
      } catch { /* no audio here: the toast still plays */ }
    });
  };

  const settle = (next) => {
    if (doneRef.current || frozenRef.current) return;
    wallAtRef.current = performance.now();
    setMode(next);
    setShown(true);
    playTracks();
  };
  const fallBack = () => {
    if (modeRef.current !== "loading" || frozenRef.current) return;
    settle("fallback");
  };

  // Mount: attach to the store (its skip is this moment's fading exit), follow the
  // viewport, and give the clip its ceiling.
  useEffect(() => {
    attachMoment(id, () => finishRef.current("skipped"));
    const onResize = () => setVp(viewport());
    window.addEventListener("resize", onResize);
    if (!clip) { wallAtRef.current = performance.now(); setShown(true); playTracks(); }
    else later(() => fallBack(), LOAD_CEILING_MS);
    return () => {
      window.removeEventListener("resize", onResize);
      timersRef.current.forEach(clearTimeout);
      stopMedia();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { setMomentVisible(id, shown); }, [id, shown]);

  // THE PAGE UNDER A MOMENT IS NOT DRAWN (owner's walk, 2026-09-26: "laggy on both"). The moment
  // covers the whole viewport on its own dark ground, but the app beneath it -- on the owner's
  // library, thousands of tiles still decoding and painting, and on a reload the gallery's whole
  // boot -- kept the compositor busy under the clip. While the moment is fully up, #root is
  // hidden (moments.css): visibility, not display or content-visibility, so its layout, scroll
  // position and state are untouched and nothing under the owner moves. It comes back the
  // instant the moment starts to leave, so the fade-out shows the page as before.
  useEffect(() => {
    if (typeof document === "undefined") return undefined;
    const up = shown && !leaving;
    document.body.classList.toggle("mg-moment-up", up);
    return () => document.body.classList.remove("mg-moment-up");
  }, [shown, leaving]);

  // The video tells us when it can go.
  const onReady = () => {
    const v = videoRef.current;
    if (!v || modeRef.current !== "loading" || doneRef.current || frozenRef.current) return;
    if (reduced) {
      // One still, no playback. It is seeked once; `seeked` (or no seek needed) settles it.
      const ct = clipTime(STILL[kind].still(cues), clipEndOf(v.duration));
      if (!needsSeek(v.currentTime, ct)) { settle("still"); return; }
      once(v, "seeked").then(() => { if (modeRef.current === "loading") settle("still"); });
      v.currentTime = ct;
      return;
    }
    clockRef.current = startClock(performance.now());
    setMode("play");
    setShown(true);
  };
  const onVideoError = () => {
    if (modeRef.current === "loading") fallBack();
  };

  /* THE CLOCK, live. One rAF loop while the clip plays: the step says what T is and what the
     video must do this frame; the page's clamp holds the last frame through the Hold.
     The video is the clock, so a video that STOPS (it will not play even muted, or it stalls
     for good) would stop the moment -- and the hold on every later toast with it. A clip that
     has not moved for LOAD_CEILING_MS of VISIBLE time falls back instead; frame gaps are
     capped, so a tab sent to the background does not count as a stall. */
  useEffect(() => {
    if (mode !== "play") return undefined;
    const v = videoRef.current;
    let lastNow = performance.now();
    let lastT = -1;
    let stalled = 0;
    const tick = () => {
      if (doneRef.current || frozenRef.current || modeRef.current !== "play") return;
      const now = performance.now();
      const s = stepClock(clockRef.current, {
        now, videoTime: v ? v.currentTime : 0, ended: !!(v && v.ended),
        clipEnd: clipEndOf(v && v.duration), total,
      });
      clockRef.current = s;
      if (v && s.play) {
        v.muted = false;
        const p = v.play();
        if (p && p.catch) {
          p.catch(() => {
            if (doneRef.current || frozenRef.current) return;
            v.muted = true;
            setNeedsSound(true);
            v.play().catch(() => { settle("fallback"); });
          });
        }
      }
      if (v && s.pause && !v.paused) v.pause();
      if (v && s.seekTo != null) v.currentTime = s.seekTo;
      stalled = s.phase === "clip" && s.T <= lastT ? stalled + Math.min(now - lastNow, 100) : 0;
      lastNow = now;
      lastT = s.T;
      if (stalled > LOAD_CEILING_MS) { settle("fallback"); return; }
      setT(s.T);
      if (s.done) { finishRef.current("done"); return; }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [mode, total]);

  // The settled modes' own clock: only the fade in, the fade out and the length move.
  useEffect(() => {
    if (mode !== "still" && mode !== "fallback") return undefined;
    const tick = () => {
      if (doneRef.current || frozenRef.current) return;
      const w = (performance.now() - wallAtRef.current) / 1000;
      setWall(Math.min(w, total));
      if (w >= total) { finishRef.current("done"); return; }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [mode, total]);

  // The harness seek -- see the header. Present only under the harness flag.
  useEffect(() => {
    if (!harnessOn()) return undefined;
    const seek = async (at) => {
      const t = Number(at) || 0;
      frozenRef.current = true;
      cancelAnimationFrame(rafRef.current);
      timersRef.current.forEach(clearTimeout);
      timersRef.current = [];
      tracksRef.current.forEach((au) => { try { au.pause(); } catch { /* gone */ } });
      tracksRef.current = [];
      const v = videoRef.current;
      if (v) {
        if (v.readyState < 2) await once(v, "loadeddata");
        v.pause();
        const ct = clipTime(t, clipEndOf(v.duration));
        if (needsSeek(v.currentTime, ct)) {
          const seeked = once(v, "seeked");
          v.currentTime = ct;
          await seeked;
        }
      }
      flushSync(() => { setMode("frozen"); setShown(true); setT(t); });
      await twoFrames();
    };
    window.__mgMomentSeek = seek;
    return () => { if (window.__mgMomentSeek === seek) delete window.__mgMomentSeek; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const skip = () => finish("skipped");
  const unmute = (e) => {
    e.stopPropagation();
    const v = videoRef.current;
    if (v) v.muted = false;
    setNeedsSound(false);
  };
  const takeMeThere = (e) => {
    e.stopPropagation();
    const opened = openPanelHere("brand");
    finish("button", opened ? null : () => carryPanelTab("brand"));
  };

  // ---- the frame ------------------------------------------------------------------------
  const st = fitStage(vp.w, vp.h);
  const sf = fitSafe(vp.w, vp.h);
  const settled = mode === "still" || mode === "fallback";
  const overlayT = settled ? STILL[kind].overlay(cues) : T;
  const clipT = settled ? STILL[kind].still(cues) : T;
  const f = kind === "starfall"
    ? starfallFrame(overlayT, cues, total, { still: settled, clipT, su: sf.scale, greeting: greet, line: copy.line || achievement.desc || "" })
    : keyturnFrame(overlayT, cues, total, { still: settled, clipT, su: sf.scale, copy });
  const fade = settled ? pieceFade(wall, total, FADE_OUT[kind]) : f.fade;
  const rootOpacity = shown && !leaving ? 1 : 0;
  const rootMotion = mode === "frozen" ? "none" : "opacity " + FADE_OUT_MS + "ms ease";
  const flare = f.castflare || f.doorflare;
  const showVideo = !!clip && mode !== "fallback";

  return (
    <div data-moment={kind} className="mgm-root">
      <div className="mgm-scrim" style={{ width: vp.w, height: vp.h, opacity: rootOpacity, transition: rootMotion }} />
      <div className="mgm-host" onClick={skip}
        style={{ width: vp.w, height: vp.h, opacity: rootOpacity, transition: rootMotion, pointerEvents: shown ? "auto" : "none" }}>
        <div className="mgm-fade" style={{ opacity: fade }}>
          <div data-moment-stage="" className="mgm-stage"
            style={{ transform: "translate(" + st.x + "px, " + st.y + "px) scale(" + st.scale + ")" }}>
            {showVideo ? (
              <video ref={videoRef} data-part="clip" src={clip} style={f.clip}
                playsInline preload="auto" disablePictureInPicture
                onCanPlayThrough={reduced ? undefined : onReady}
                onLoadedData={reduced ? onReady : undefined}
                onError={onVideoError} />
            ) : null}
            {flare ? (
              <div data-part={kind === "starfall" ? "castflare" : "doorflare"} className="mgm-flare">
                <div style={flare.wash} />
                <div style={flare.bloom} />
              </div>
            ) : null}
            <div style={f.gradient} />
            {(f.stars || []).map((s) => <div key={s.i} data-part="star" style={s.style}>✦</div>)}
          </div>
          <div className="mgm-safe"
            style={{ transform: "translate(" + sf.x + "px, " + sf.y + "px) scale(" + sf.scale + ")" }}>
            {f.keys ? (
              <div data-part="keys" style={f.keys.row}>
                {f.keys.caps.map((c, i) => <div key={i} data-part="key" style={c.style}>{c.label}</div>)}
              </div>
            ) : null}
            {f.rail ? <Rail r={f.rail} /> : null}
            <div data-part="toast" style={f.toast.box}>
              <div data-part="toast-title" style={f.toast.title}>{f.toast.titleText}</div>
              <div data-part="toast-line" style={f.toast.line}>{f.toast.lineText}</div>
              {kind === "keyturn" ? (
                <div style={f.toast.offerWrap}>
                  <button type="button" data-part="button" onClick={takeMeThere}
                    tabIndex={f.toast.offer > 0.5 ? 0 : -1}
                    style={{ ...BUTTON_RESET, ...f.toast.button }}>
                    {f.toast.buttonText}<span style={f.toast.arrow}>→</span>
                  </button>
                </div>
              ) : null}
            </div>
            {f.caption ? <div data-part="caption" style={f.caption.style}>{f.caption.text}</div> : null}
          </div>
        </div>
        {needsSound ? (
          <button type="button" className="mgm-sound" data-moment-sound="" onClick={unmute}
            aria-label="Play the sound">🔊</button>
        ) : null}
      </div>
    </div>
  );
}

/* The Control Panel rail, drawn with the panel's REAL tabs (lib/panelTabs.js): every tab the
   owner already has as a plain row, the first one current, and the gated tab as the slot
   whose lock opens and whose row slides in. */
function Rail({ r }) {
  const open = PANEL_TABS.filter((t) => !t.gated);
  const gated = PANEL_TABS.find((t) => t.gated) || { label: "" };
  return (
    <div data-part="rail" style={r.box}>
      <div style={r.heading}>Control Panel</div>
      <div style={r.sub}>Settings for your Athenaeum</div>
      <div style={r.list}>
        {open.map((t, i) => {
          const s = r.tab(i === 0);
          return <div key={t.id} style={s.row}><span style={s.dot} />{t.label}</div>;
        })}
        <div style={r.lockRow}>
          <div data-part="lock" style={r.lock}>
            <div style={r.shackle} />
            <div style={r.body} />
          </div>
          <span style={r.locked}>Locked</span>
          <div data-part="tab-branding" style={r.branding}>
            <span style={r.brandingDot} />{gated.label}
            <span style={r.fresh}>New</span>
          </div>
        </div>
      </div>
    </div>
  );
}
