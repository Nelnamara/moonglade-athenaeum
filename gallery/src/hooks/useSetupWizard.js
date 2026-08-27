import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "../api.js";

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
  { mascot: "/branding/mascots/nel_setup2.webp", head: "Your whole collection, kept",
    body: "Browse, search and sort every image and video you've conjured — rated, tagged, and never lost to the scroll." },
  { mascot: "/branding/mascots/nel_setup3.webp", head: "Weave shots into a story",
    body: "The Loom strings your stills into continuous motion — frame handed off to frame, shot to shot, scene to scene." },
  { mascot: "/branding/mascots/nel_setup4.webp", head: "One composer, every craft",
    body: "Image, Edit and Video, side by side — model, LoRAs and cost always in plain sight before you spend a credit." },
];
export const KEY_STEPS = [
  { n: 1, text: "Sign in at pixai.art." },
  { n: 2, text: "Open Profile → Settings → API and generate a key (requires membership)." },
  { n: 3, text: "Copy it, then paste it below." },
];
const POLL_MS = 1500;
const POLL_MISS_LIMIT = 5;
const ASSET_POLL_MS = 400;       // more frequent than sync's -- a download bar reads as
                                  // stalled at 1500ms between updates; a job poll doesn't.
const ASSET_POLL_MISS_LIMIT = 8;
const MB = 1e6;

export default function useSetupWizard(boot) {
  // Asset download runs AHEAD of intro when needed (owner ruling, 2026-08-10,
  // docs/DECISIONS.md: "inside the wizard as phases ahead of the intro
  // carousel"). needs_assets is computed server-side the same cheap way as
  // needs_key (moonglade_gallery.py's next_gallery()); an install that's
  // already dressed (or has no manifest at all -- an old checkout) skips
  // straight to the phase this component always started at before.
  const [phase, setPhase] = useState(
    boot.needs_assets ? "checking" : (boot.needs_key ? "intro" : "sync"));
  const [slide, setSlide] = useState(0);

  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");

  const [progress, setProgress] = useState(null); // {done,total,new,pct} | null while connecting
  const [syncError, setSyncError] = useState("");
  const [finalStats, setFinalStats] = useState(null);

  // dl.received/total in MB (matching the design's own display unit); speed in MB/s;
  // eta in whole seconds or null while unknown.
  const [dl, setDl] = useState({ received: 0, total: 0, speed: 0, eta: null });
  const [dlError, setDlError] = useState("");

  const pollRef = useRef(null);
  const pollMissesRef = useRef(0);
  const assetPollRef = useRef(null);
  const assetMissesRef = useRef(0);
  const assetsReadyTRef = useRef(null);
  const checkingRef = useRef(false);

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (assetPollRef.current) clearInterval(assetPollRef.current);
    if (assetsReadyTRef.current) clearTimeout(assetsReadyTRef.current);
  }, []);

  // Where the wizard goes once the asset question is settled (dressed, or the
  // owner chose to proceed undressed) -- the SAME phase this component always
  // opened at before the download phases existed.
  const afterAssets = () => setPhase(boot.needs_key ? "intro" : "sync");

  // ONE disclosed departure from the DC here, same class as the sync phase's own
  // (see this file's header comment): the design's dlErrText assumes every failure
  // is a dropped connection ("The connection dropped at N of M MB..."). The real
  // engine (moonglade_assets.AssetFetchJob) can fail for reasons that aren't a
  // connection drop at all -- a checksum mismatch, no release published yet ("no
  // download source configured") -- so this composes
  // the same shape and the same true reassurance clause around the REAL reason
  // instead of a canned one that would be false most of the time it actually fires.
  const dlErrorText = (reason) => {
    const where = dl.total ? " (" + dl.received + " of " + dl.total + " MB)" : "";
    return "The delivery was interrupted" + where + " — " + (reason || "something interrupted it") +
      ". Nothing partial was kept — retrying starts clean, and the library is untouched.";
  };

  const assetTick = async () => {
    const d = await apiGet("/api/assets/status");
    if (d.error) {
      assetMissesRef.current += 1;
      if (assetMissesRef.current >= ASSET_POLL_MISS_LIMIT) {
        clearInterval(assetPollRef.current); assetPollRef.current = null;
        setDlError(dlErrorText("lost contact while downloading"));
        setPhase("interrupted");
      }
      return;
    }
    assetMissesRef.current = 0;
    if (d.status === "running") {
      setDl({ received: Math.round((d.downloaded || 0) / MB),
              total: Math.round((d.total || 0) / MB),
              speed: (d.speed_bps || 0) / MB, eta: d.eta_seconds });
      return;
    }
    clearInterval(assetPollRef.current); assetPollRef.current = null;
    if (d.status === "done") {
      setPhase("assetsready");
      assetsReadyTRef.current = setTimeout(afterAssets, 1600);
      return;
    }
    // "failed" (a real error) or "idle" (the job never actually started, or was
    // reset) -- both read as Interrupted; d.error is the honest reason either way.
    setDl((s) => ({ ...s, received: Math.round((d.downloaded || 0) / MB) }));
    setDlError(dlErrorText(d.error));
    setPhase("interrupted");
  };

  const beginDownload = async () => {
    setPhase("downloading");
    setDlError("");
    setDl({ received: 0, total: 0, speed: 0, eta: null });
    assetMissesRef.current = 0;
    const d = await apiPost("/api/assets/fetch");
    // "already running" means someone/something else's fetch is genuinely in
    // flight -- that's not a failure to report, just start polling its real
    // progress. Any OTHER error (no manifest, no urls yet) means
    // the job never started at all, so there's nothing to poll.
    if (d.error && !/already running/i.test(d.error)) {
      setDlError(dlErrorText(d.error));
      setPhase("interrupted");
      return;
    }
    assetPollRef.current = setInterval(assetTick, ASSET_POLL_MS);
    assetTick();
  };

  const beginAssetCheck = async () => {
    if (checkingRef.current) return;
    checkingRef.current = true;
    const d = await apiGet("/api/assets/status");
    checkingRef.current = false;
    if (d.error || !d.needs) { afterAssets(); return; }   // unreachable, already dressed, or nothing to fetch
    beginDownload();
  };

  const retryDownload = () => setPhase("checking");   // the checking-phase effect below re-drives it
  const continueWithoutArtwork = () => {
    if (assetPollRef.current) { clearInterval(assetPollRef.current); assetPollRef.current = null; }
    afterAssets();
  };

  useEffect(() => {
    if (phase !== "checking") return undefined;
    // Same 750ms visual beat the design specifies for Checking, real or retried.
    const t = setTimeout(beginAssetCheck, 750);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

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
    const d = await apiPost("/api/setup/save-key", { api_key: key });
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
    const d = await apiGet("/api/panel/status");
    if (d.error) {
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
    const stats = await apiGet("/api/stats");
    setFinalStats(stats.error ? null : stats);
    setPhase("ready");
  };

  const startSync = async () => {
    setSyncError("");
    setProgress(null);
    pollMissesRef.current = 0;
    const d = await apiPost("/api/panel/run", { action: "sync" });
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
    dl, dlError, retryDownload, continueWithoutArtwork,
    openPixai, nextSlide, prevSlide, skipToKey, authenticate, startSync, enter,
  };
}
