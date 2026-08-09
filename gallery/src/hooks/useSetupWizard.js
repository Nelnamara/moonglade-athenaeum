import { useEffect, useRef, useState } from "react";

/* All of SetupWizard.jsx's state/handlers/API-call logic, mechanically lifted out
   (2026-08-02, mobile pass surface 2) so SetupWizardMobile.jsx can reuse it verbatim
   instead of a second copy drifting from the original -- same motivation useLogin.js
   already states for itself, and the same operation its own header comment names as
   the obvious next step. SetupWizard.jsx (desktop) is untouched by this extraction:
   its own inline useState/handlers still work exactly as before, this hook is a
   byte-for-byte copy of that same logic, not a rewrite of it. There is nothing
   device-specific in here, only presentation (JSX/CSS) differs between the two
   surfaces.

   REAL backend the whole way through, same as desktop, NOT re-simulated for mobile:
   /api/setup/save-key (key validation + the config.json write), POST /api/panel/run
   {action:'sync'} + polling /api/panel/status -- the exact endpoints SetupWizard.jsx
   already calls (see that file's own header comment). The design mockup's
   dummy-task-id 401/403 probe, its localStorage'd key, and its fixed-timer
   SYNC_STAGES animation with fabricated per-type counts are NOT ported here --
   those are Setup Wizard Mobile.dc.html's own disclosed stand-ins for a prototype
   that had no server to call, same departure desktop's own header comment already
   made and tested (tests/test_setup_wizard.py). */

export const SLIDES = [
  { mascot: "/branding/login_nel.webp", head: "Welcome to the Athenaeum",
    body: "A library built to hold everything PixAI ever helped you make — every spark, kept against the Void." },
  { mascot: "/branding/mascots/nel_carl.png", head: "Your whole collection, kept",
    body: "Browse, search and sort every image and video you've conjured — rated, tagged, and never lost to the scroll." },
  { mascot: "/branding/mascots/nel_micdrop.png", head: "Weave shots into a story",
    body: "The Loom strings your stills into continuous motion — frame handed off to frame, shot to shot, scene to scene." },
  { mascot: "/branding/mascots/gen_nel.png", head: "One composer, every craft",
    body: "Image, Edit and Video, side by side — model, LoRAs and cost always in plain sight before you spend a credit." },
];
export const KEY_STEPS = [
  { n: 1, text: "Sign in at pixai.art." },
  { n: 2, text: "Open Profile → Settings → API and generate a key (requires membership)." },
  { n: 3, text: "Copy it, then paste it below." },
];
const POLL_MS = 1500;
const POLL_MISS_LIMIT = 5;

export default function useSetupWizard(boot) {
  const [phase, setPhase] = useState(boot.needs_key ? "intro" : "sync");
  const [slide, setSlide] = useState(0);

  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");

  const [progress, setProgress] = useState(null); // {done,total,new,pct} | null while connecting
  const [syncError, setSyncError] = useState("");
  const [finalStats, setFinalStats] = useState(null);

  const pollRef = useRef(null);
  const pollMissesRef = useRef(0);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const openPixai = () => window.open("https://pixai.art/en/profile/edit/api", "_blank", "noopener");

  const nextSlide = () => {
    if (slide >= SLIDES.length - 1) { setPhase("key"); return; }
    setSlide((s) => s + 1);
  };
  const prevSlide = () => setSlide((s) => Math.max(0, s - 1));
  const skipToKey = () => setPhase("key");

  // Matches SetupWizard.jsx's inline key-input onChange exactly: every keystroke
  // both updates the field and clears any standing auth error.
  const onApiKeyChange = (value) => { setApiKey(value); setAuthError(""); };

  const authenticate = async () => {
    const key = apiKey.trim();
    if (!key || authBusy) return;
    setAuthBusy(true);
    setAuthError("");
    let d;
    try {
      const r = await fetch("/api/setup/save-key", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: key }),
      });
      d = await r.json();
    } catch {
      setAuthBusy(false);
      setAuthError("Network error — try again.");
      return;
    }
    if (d.error) {
      setAuthBusy(false);
      setAuthError(d.error);
      return;
    }
    setAuthBusy(false);
    setPhase("sync");
  };

  // "Sync now" is the real /api/panel/run{action:'sync'} + /api/panel/status poll classic's
  // own first-run banner already drives (Setup.firstSync()/tick() in moonglade_gallery.py) --
  // ported here rather than reinvented, including the reason-from-real-log-lines fallback.
  const syncReason = (d) => {
    const lines = d.lines || [];
    const rc = d.rc != null ? " (exit " + d.rc + ")" : "";
    if (lines.length === 1 && String(lines[0]).indexOf("only on the server") !== -1) {
      return "Sync failed" + rc + " — open Moonglade on the server itself to see why.";
    }
    const tail = [];
    for (let i = lines.length - 1; i >= 0 && tail.length < 3; i--) {
      const t = String(lines[i] || "").trim();
      if (t) tail.unshift(t);
    }
    return tail.length ? "Sync failed" + rc + ": " + tail.join(" · ")
                        : "Sync failed" + rc + " — the job ended without printing a reason.";
  };

  const tick = async () => {
    let d;
    try {
      const r = await fetch("/api/panel/status");
      d = await r.json();
    } catch {
      pollMissesRef.current += 1;
      if (pollMissesRef.current >= POLL_MISS_LIMIT) {
        clearInterval(pollRef.current); pollRef.current = null;
        setSyncError("Lost contact with the sync job — check the Panel, then try again.");
      }
      return;
    }
    pollMissesRef.current = 0;
    if (d.status === "running") {
      setProgress(d.progress || null);
      return;
    }
    clearInterval(pollRef.current); pollRef.current = null;
    if (d.status === "failed") {
      setSyncError(syncReason(d));
      return;
    }
    // done / done_with_errors / anything else terminal-non-failed -- same "good enough,
    // move on" line classic's own tick() draws (it doesn't special-case done_with_errors
    // either): a handful of failed downloads doesn't strand a brand-new user on this screen.
    try {
      const r = await fetch("/api/stats");
      setFinalStats(await r.json());
    } catch {
      setFinalStats(null);
    }
    setPhase("ready");
  };

  const startSync = async () => {
    setSyncError("");
    setProgress(null);
    pollMissesRef.current = 0;
    let d;
    try {
      const r = await fetch("/api/panel/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "sync" }),
      });
      d = await r.json();
    } catch {
      setSyncError("Network error — try again.");
      return;
    }
    if (d.error) {
      setSyncError(d.error);
      return;
    }
    pollRef.current = setInterval(tick, POLL_MS);
    tick();
  };

  useEffect(() => {
    if (phase === "sync" && !pollRef.current && !syncError) startSync();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  const enter = () => { window.location.href = "/"; };

  return {
    phase, slide,
    apiKey, onApiKeyChange, showKey, setShowKey, authBusy, authError,
    progress, syncError, finalStats,
    openPixai, nextSlide, prevSlide, skipToKey, authenticate, startSync, enter,
  };
}
