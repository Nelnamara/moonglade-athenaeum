import React, { useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "../api.js";
import { NEL_WIZARD } from "../art/nelWizard.js";
import "../styles/setup-wizard.css";

/* First-run Setup Wizard -- design spec: Setup Wizard.dc.html / Setup Wizard Mobile.dc.html.
   Rendered by main.jsx in place of <App> whenever boot.needs_key or boot.catalog_empty is
   true (see moonglade_gallery.py's next_gallery(), which computes both the SAME way
   classic's index() always has). App never mounts in that case, matching LoginPage's own
   pattern -- nothing here can race an authenticated-only fetch that assumes a real catalog.

   Real backend the whole way through, NOT new: /api/setup/save-key (key validation + the
   config.json write), POST /api/panel/run {action:'sync'} + polling /api/panel/status --
   all three already shipped and tested by classic's own "paste a key, run first sync"
   banner (see moonglade_gallery.py's Setup JS object and tests/test_setup_wizard.py).
   This is a full-fidelity port of the theatrical 4-phase experience (intro carousel -> key
   entry -> sync -> ready) the DC designs, driven by those same real endpoints instead of
   classic's plainer two-banner version -- the owner's own call on seeing it live: "a bit
   more theatric now but still gets the job done quickly."

   ONE disclosed departure from the DC, forced by what the real backend actually reports:
   the DC's sync phase is 5 fake, individually-timed stages ("Counting your images...",
   900ms/1100ms/900ms/800ms/700ms hardcoded) that reveal 3 made-up per-media-type numbers
   one at a time. The real --sync job reports a single combined done/total/new counter
   (api_panel_status's `progress`), not a per-type breakdown, and finishes whenever it
   actually finishes -- never a fixed duration. So: one real, continuously live-updating
   progress bar and two real reveal chips (tasks synced, how many were new) drive the SAME
   halo-mascot/progress-bar/reveal-row visual language the DC specifies, and the DC's real
   per-type numbers (images/videos/collections) appear for real on the READY phase instead,
   sourced from the same /api/stats every other header/banner in the app already trusts --
   relocated to where the app actually HAS that breakdown, not fabricated to fit a timer.

   ASSET DOWNLOAD PHASES (2026-08-10, handoff-2026-08-10-first-run-download.md, owner-ruled
   placement -- docs/DECISIONS.md): checking -> downloading -> (interrupted) -> assetsready,
   ahead of the intro carousel, driven by real /api/assets/status polling + POST
   /api/assets/fetch against moonglade_assets.AssetFetchJob -- NOT the DC's fixed-timer
   simulated 391MB. Skipped entirely (falls straight to intro/sync, unchanged) when
   boot.needs_assets is false: already dressed, or an old checkout with no manifest. One
   disclosed departure, same class as the sync-phase one above: the DC's Interrupted copy
   assumes every failure is a dropped connection; the real engine can fail for reasons that
   aren't (a checksum mismatch, no release published yet, the localhost gate), so
   dlErrorText() composes the DC's own shape and reassurance clause around the REAL reason. */

const SLIDES = [
  { mascot: "/branding/login_nel.webp", head: "Welcome to the Athenaeum",
    body: "A library built to hold everything PixAI ever helped you make — every spark, kept against the Void." },
  { mascot: "/branding/mascots/nel_setup2.webp", head: "Your whole collection, kept",
    body: "Browse, search and sort every image and video you've conjured — rated, tagged, and never lost to the scroll." },
  { mascot: "/branding/mascots/nel_setup3.webp", head: "Weave shots into a story",
    body: "The Loom strings your stills into continuous motion — frame handed off to frame, shot to shot, scene to scene." },
  { mascot: "/branding/mascots/nel_setup4.webp", head: "One composer, every craft",
    body: "Image, Edit and Video, side by side — model, LoRAs and cost always in plain sight before you spend a credit." },
];
const KEY_STEPS = [
  { n: 1, text: "Sign in at pixai.art." },
  { n: 2, text: "Open Profile → Settings → API and generate a key (requires membership)." },
  { n: 3, text: "Copy it, then paste it below." },
];
const POLL_MS = 1500;
const POLL_MISS_LIMIT = 5;
const ASSET_POLL_MS = 400;
const ASSET_POLL_MISS_LIMIT = 8;
const MB = 1e6;

export default function SetupWizard({ boot }) {
  // Asset download runs AHEAD of intro when needed (owner ruling, 2026-08-10,
  // docs/DECISIONS.md: "inside the wizard as phases ahead of the intro
  // carousel"). An install that's already dressed (or has no manifest at all --
  // an old checkout) skips straight to the phase this component always started
  // at before -- needs_assets computed server-side the same cheap way as needs_key.
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

  // dl.received/total in MB (the design's own display unit); speed in MB/s; eta
  // in whole seconds or null while unknown.
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
  // (see this file's header comment): the design's dlErrText assumes every
  // failure is a dropped connection. The real engine (moonglade_assets.
  // AssetFetchJob) can fail for reasons that aren't a connection drop at all --
  // a checksum mismatch, no release published yet, the localhost-only gate --
  // so this composes the same shape and the same true reassurance clause around
  // the REAL reason instead of a canned one that would be false most of the
  // time it actually fires.
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
    // progress. Any OTHER error (no manifest, no urls yet, localhost-only) means
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

  if (phase === "checking" || phase === "downloading") {
    const checking = phase === "checking";
    return (
      <div className="wz-stage">
        <div className="wz-wash wz-wash-a" />
        <div className="wz-wash wz-wash-b" />
        <div className="wz-card">
          <div className="wz-toprow"><div className="wz-kicker">FIRST-TIME SETUP</div></div>
          <div className="wz-syncwrap">
            <div className="wz-stepkicker">{checking ? "Preparing the Athenaeum" : "One-time download"}</div>
            <div className="wz-syncmascotbox">
              <div className="wz-synchalo wz-synchalo-steam" />
              <div className="wz-syncmascotart" style={{ backgroundImage: `url(${NEL_WIZARD})` }} aria-hidden="true" />
            </div>
            <div className="wz-synchead">{checking ? "Taking stock of the shelves…" : "Furnishing the Athenaeum"}</div>
            {checking ? null : (
              <div className="wz-dlbody">The library's art and trappings are on their way — this happens once, and never again unless the collection itself is updated.</div>
            )}
            <div className="wz-synctrack">
              <i className={"wz-syncbar" + (checking ? " indeterminate" : "")}
                style={checking ? undefined : { width: (dl.total ? (dl.received / dl.total) * 100 : 0) + "%" }} />
            </div>
            {checking ? <div className="wz-revealrow" /> : (
              <div className="wz-revealrow">
                <div className="wz-reveal">
                  <b className="wz-reveal-v">{dl.received} / {dl.total} MB</b>
                  <span className="wz-reveal-k">received</span>
                </div>
                <div className="wz-reveal">
                  <b className="wz-reveal-v">{dl.speed ? dl.speed.toFixed(1) + " MB/s" : "—"}</b>
                  <span className="wz-reveal-k">speed</span>
                </div>
                <div className="wz-reveal">
                  <b className="wz-reveal-v">{dl.eta == null ? "—" : dl.eta < 1 ? "<1 s" : "~" + Math.ceil(dl.eta) + " s"}</b>
                  <span className="wz-reveal-k">remaining</span>
                </div>
              </div>
            )}
            <div className="wz-footnote">
              {checking ? "One moment — checking what this library already holds."
                        : "Verified against its fingerprint on arrival — a bad download can never be mistaken for a good one."}
            </div>
          </div>
          <div className="wz-lore">a library against the Void</div>
        </div>
      </div>
    );
  }

  if (phase === "interrupted" || phase === "assetsready") {
    const interrupted = phase === "interrupted";
    return (
      <div className="wz-stage">
        <div className="wz-wash wz-wash-a" />
        <div className="wz-wash wz-wash-b" />
        <div className="wz-card">
          <div className="wz-toprow"><div className="wz-kicker">FIRST-TIME SETUP</div></div>
          <div className="wz-syncwrap">
            <div className="wz-stepkicker">One-time download</div>
            <div className="wz-syncmascotbox">
              <div className={interrupted ? "wz-dlhalo-off" : "wz-dlhalo-good"} />
              <img className="wz-dlstatic"
                src={interrupted ? "/branding/mascots/trk_fail.png" : "/branding/mascots/trk_done.png"} alt="" />
            </div>
            <div className="wz-synchead">{interrupted ? "The delivery was interrupted" : "The shelves are dressed"}</div>
            {interrupted ? (
              <>
                <div className="wz-syncerr">{dlError}</div>
                <button type="button" className="wz-retrybtn wz-metal" onClick={retryDownload}>↻ Try again</button>
                <button type="button" className="wz-quietbtn" onClick={continueWithoutArtwork}>
                  Continue without the default artwork — it can finish later
                </button>
                <div className="wz-footnote">The app works fully without it; things simply arrive undecorated until the download completes.</div>
              </>
            ) : (
              <div className="wz-dlbody">{dl.total || 391} MB verified — now let's get you set up.</div>
            )}
          </div>
          <div className="wz-lore">a library against the Void</div>
        </div>
      </div>
    );
  }

  if (phase === "intro") {
    const s = SLIDES[slide];
    return (
      <div className="wz-stage">
        <div className="wz-wash wz-wash-a" />
        <div className="wz-wash wz-wash-b" />
        <div className="wz-card">
          <div className="wz-toprow">
            <div className="wz-kicker">FIRST-TIME SETUP</div>
            <button type="button" className="wz-skip" onClick={skipToKey}>Skip to setup →</button>
          </div>
          <div className="wz-dots">
            {SLIDES.map((_, i) => <div key={i} className={"wz-dot" + (i === slide ? " on" : "")} style={{ width: i === slide ? 18 : 6 }} />)}
          </div>
          <div className="wz-slidewrap" key={slide}>
            <div className="wz-mascotbox" style={{ backgroundImage: "url('" + s.mascot + "')" }} />
            <div className="wz-slidehead">{s.head}</div>
            <div className="wz-slidebody">{s.body}</div>
          </div>
          <div className="wz-navrow">
            {slide > 0 ? <button type="button" className="wz-back" onClick={prevSlide}>Back</button>
                       : <div className="wz-backghost" />}
            <div className="wz-fill" />
            <button type="button" className="wz-next wz-metal" onClick={nextSlide}>
              {slide >= SLIDES.length - 1 ? "Let's set up my key →" : "Next"}
            </button>
          </div>
          <div className="wz-lore">a library against the Void</div>
        </div>
      </div>
    );
  }

  if (phase === "key") {
    const canAuth = !!apiKey.trim() && !authBusy;
    return (
      <div className="wz-stage">
        <div className="wz-wash wz-wash-a" />
        <div className="wz-wash wz-wash-b" />
        <div className="wz-card">
          <div className="wz-toprow"><div className="wz-kicker">FIRST-TIME SETUP</div></div>
          <div className="wz-stepkicker">Link your PixAI account</div>
          <div className="wz-stephead">One key. Nothing else to configure.</div>
          <div className="wz-stepslist">
            {KEY_STEPS.map((ks) => (
              <div className="wz-steprow" key={ks.n}>
                <div className="wz-stepnum">{ks.n}</div>
                <div className="wz-steptext">{ks.text}</div>
              </div>
            ))}
          </div>
          <button type="button" className="wz-openbtn" onClick={openPixai}>Open pixai.art/profile/edit/api ↗</button>
          <div className="wz-divider" />
          <div className="wz-fieldlbl">YOUR API KEY</div>
          <div className="wz-keyrow">
            <input className="wz-keyinput" type={showKey ? "text" : "password"} value={apiKey}
              placeholder="paste your PixAI API key" autoFocus
              onChange={(e) => { setApiKey(e.target.value); setAuthError(""); }}
              onKeyDown={(e) => { if (e.key === "Enter") authenticate(); }} disabled={authBusy} />
            <button type="button" className="wz-eyebtn" onClick={() => setShowKey((v) => !v)}>
              {showKey ? "Hide" : "Show"}
            </button>
          </div>
          {authError ? <div className="wz-errnote">{authError}</div> : null}
          <button type="button" className={"wz-authbtn wz-metal" + (!canAuth ? " disabled" : "")}
            onClick={authenticate} disabled={!canAuth}>
            {authBusy ? <span className="wz-spin" /> : null}
            <span>{authBusy ? "Authenticating…" : "Authenticate"}</span>
          </button>
          <div className="wz-footnote">Stored locally — nothing else leaves this machine.</div>
          <div className="wz-lore">a library against the Void</div>
        </div>
      </div>
    );
  }

  if (phase === "sync") {
    const label = syncError ? "Sync interrupted" : progress ? "Syncing your library…" : "Connecting to PixAI…";
    return (
      <div className="wz-stage">
        <div className="wz-wash wz-wash-a" />
        <div className="wz-wash wz-wash-b" />
        <div className="wz-card">
          <div className="wz-toprow"><div className="wz-kicker">FIRST-TIME SETUP</div></div>
          <div className="wz-syncwrap">
            <div className="wz-syncmascotbox">
              <div className="wz-synchalo" />
              <img className="wz-syncmascotimg" src="/branding/mascots/nel_narrator.png" alt="" />
            </div>
            <div className="wz-synchead">{label}</div>
            <div className="wz-synctrack">
              <i className={"wz-syncbar" + (progress ? "" : " indeterminate")}
                style={progress ? { width: (progress.pct != null ? progress.pct : 0) + "%" } : undefined} />
            </div>
            {progress ? (
              <div className="wz-revealrow">
                <div className="wz-reveal">
                  <b className="wz-reveal-v">{progress.done}{progress.total ? " / " + progress.total : ""}</b>
                  <span className="wz-reveal-k">Synced</span>
                </div>
                <div className="wz-reveal">
                  <b className="wz-reveal-v">{progress.new || 0}</b>
                  <span className="wz-reveal-k">New</span>
                </div>
              </div>
            ) : <div className="wz-revealrow" />}
            {syncError ? (
              <>
                <div className="wz-syncerr">{syncError}</div>
                <button type="button" className="wz-retrybtn wz-metal" onClick={startSync}>Try again</button>
              </>
            ) : null}
            {!syncError && progress && (progress.done || 0) >= 50 ? (
              <button type="button" className="wz-quietbtn wz-syncexit" onClick={enter}>
                Browse the gallery — this keeps going in the background →
              </button>
            ) : null}
          </div>
          <div className="wz-lore">a library against the Void</div>
        </div>
      </div>
    );
  }

  // phase === "ready"
  const images = finalStats ? Number(finalStats.images || 0).toLocaleString() : "—";
  const videos = finalStats ? Number(finalStats.videos || 0).toLocaleString() : "—";
  const collections = finalStats ? Number(finalStats.collections || 0).toLocaleString() : "—";
  return (
    <div className="wz-stage">
      <div className="wz-wash wz-wash-a" />
      <div className="wz-wash wz-wash-b" />
      <div className="wz-card">
        <div className="wz-toprow"><div className="wz-kicker">FIRST-TIME SETUP</div></div>
        <div className="wz-readywrap">
          <div className="wz-readyglow" />
          <div className="wz-readymark">✦</div>
          <div className="wz-readyhead">Welcome home.</div>
          <div className="wz-readybody">{images} images · {videos} videos · {collections} collections — every spark, kept.</div>
          <button type="button" className="wz-enterbtn wz-metal" onClick={enter}>Enter the Athenaeum →</button>
        </div>
        <div className="wz-lore">a library against the Void</div>
      </div>
    </div>
  );
}
