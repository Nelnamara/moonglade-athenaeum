import React from "react";
import useSetupWizard, { SLIDES, KEY_STEPS } from "../hooks/useSetupWizard.js";
import "../styles/setup-wizard-mobile.css";

/* The mobile-viewport presentation of SetupWizard.jsx (design spec: Setup Wizard
   Mobile.dc.html). Rendered by main.jsx in place of SetupWizard.jsx whenever
   useIsMobile() is true -- the SECOND mobile surface in gallery/src, following the
   exact pattern Login Mobile established (commit 8d90ff8): a viewport hook
   (hooks/useIsMobile.js) switches the presentation, and business logic lives in a
   shared hook rather than a forked copy.

   Every piece of state/logic -- the 4-phase machine, the intro carousel, the
   authenticate() call, the sync poll loop, all error handling -- comes from
   useSetupWizard (hooks/useSetupWizard.js, itself a byte-for-byte lift of
   SetupWizard.jsx's own body) and is NOT re-derived here. This file is presentation
   only: layout and sizing specific to the mobile design comp
   (setup-wizard-mobile.css). Desktop's SetupWizard.jsx is untouched.

   REAL backend the whole way through, same as desktop -- NOT the design mockup's
   stand-ins. Setup Wizard Mobile.dc.html's own script (read in full before this file
   was written) simulates the sync phase with a hardcoded SYNC_STAGES setTimeout chain
   revealing fabricated numbers (35,029 images / 311 videos / 14 collections) and
   validates the key with a dummy-task-id 401/403 probe against the live PixAI API
   followed by a raw `localStorage.setItem('mg_pixai_key', key)` -- all of that is the
   DC's own disclosed prototype stand-in for a build that had no server to call (see
   that file's own build-spec research). SetupWizard.jsx already replaced both with
   the real endpoints (/api/setup/save-key, /api/panel/run + /api/panel/status polling)
   well before this mobile pass, tested by tests/test_setup_wizard.py -- useSetupWizard
   just carries that same real logic over, so neither stand-in was ported here.

   Excluded, matching Setup Wizard Mobile.dc.html's own build-spec research (section 8):
   nothing QA/demo-only was found in the design itself -- the mockup's ONLY non-
   shippable material is its DesignSync viewer harness (<x-dc>, support.js, skins.js,
   the IOSDevice frame), which never reaches this file. Dot pagination stays
   tap-only/non-interactive (no onClick anywhere on a dot), matching every other
   mobile surface's confirmed pattern -- navigation is Back/Next only, same as desktop.

   TWO disclosed, deliberate departures from the literal Mobile mockup markup:
   - Copy is reused verbatim from the REAL desktop SetupWizard.jsx, not re-derived
     from the mockup's own placeholder strings, per this pass's brief. The mockup's
     JS uses "Skip →" / "Set up my key →"; the shipped desktop wizard's real copy is
     "Skip to setup →" / "Let's set up my key →" -- this file uses the latter, so the
     two surfaces never drift into showing different words for the same action.
   - The mockup's Ready phase renders only a mark/head/body/button -- no extra
     decorative glow layer behind the mark (unlike desktop's separate .wz-readyglow
     blob). That is the Mobile design's own markup, not an omission on this file's
     part, so no readyglow element was added here.

   Sizing note: this file follows Setup Wizard Mobile.dc.html's OWN numbers (320px
   card, 96px mascot box, 18/16/15/20px phase headlines, 18px step-number circle),
   fluid-capped the same way LoginPageMobile.jsx's card is (min(Npx, 100vw - 40px))
   rather than reusing the larger fluid scale SetupWizard.jsx's shipped desktop card
   settled on (560px cap, 120px mascot, 22/19/17/23px headlines) -- Login's own two
   sibling files are the direct precedent: Login Mobile.dc.html's smaller numbers were
   kept as its own scale (login-mobile.css) rather than following Login.dc.html's
   larger desktop numbers, and that shipped pass is the one already merged, so this
   file matches the same precedent instead of re-opening it. Worth a quick confirm
   alongside the same discrepancy the desktop build-spec research already flagged. */

export default function SetupWizardMobile({ boot }) {
  const {
    phase, slide,
    apiKey, onApiKeyChange, showKey, setShowKey, authBusy, authError,
    progress, syncError, finalStats,
    openPixai, nextSlide, prevSlide, skipToKey, authenticate, startSync, enter,
  } = useSetupWizard(boot);

  if (phase === "intro") {
    const s = SLIDES[slide];
    return (
      <div className="wzm-stage">
        <div className="wzm-wash wzm-wash-a" />
        <div className="wzm-wash wzm-wash-b" />
        <div className="wzm-card">
          <div className="wzm-toprow">
            <div className="wzm-kicker">FIRST-TIME SETUP</div>
            <button type="button" className="wzm-skip" onClick={skipToKey}>Skip to setup →</button>
          </div>
          <div className="wzm-dots">
            {SLIDES.map((_, i) => <div key={i} className={"wzm-dot" + (i === slide ? " on" : "")} style={{ width: i === slide ? 16 : 6 }} />)}
          </div>
          <div className="wzm-slidewrap" key={slide}>
            <div className="wzm-mascotbox" style={{ backgroundImage: "url('" + s.mascot + "')" }} />
            <div className="wzm-slidehead">{s.head}</div>
            <div className="wzm-slidebody">{s.body}</div>
          </div>
          <div className="wzm-navrow">
            {slide > 0 ? <button type="button" className="wzm-back" onClick={prevSlide}>Back</button>
                       : <div className="wzm-backghost" />}
            <div className="wzm-fill" />
            <button type="button" className="wzm-next wzm-metal" onClick={nextSlide}>
              {slide >= SLIDES.length - 1 ? "Let's set up my key →" : "Next"}
            </button>
          </div>
          <div className="wzm-lore">a library against the Void</div>
        </div>
      </div>
    );
  }

  if (phase === "key") {
    const canAuth = !!apiKey.trim() && !authBusy;
    return (
      <div className="wzm-stage">
        <div className="wzm-wash wzm-wash-a" />
        <div className="wzm-wash wzm-wash-b" />
        <div className="wzm-card">
          <div className="wzm-toprow"><div className="wzm-kicker">FIRST-TIME SETUP</div></div>
          <div className="wzm-stepkicker">Link your PixAI account</div>
          <div className="wzm-stephead">One key. Nothing else to configure.</div>
          <div className="wzm-stepslist">
            {KEY_STEPS.map((ks) => (
              <div className="wzm-steprow" key={ks.n}>
                <div className="wzm-stepnum">{ks.n}</div>
                <div className="wzm-steptext">{ks.text}</div>
              </div>
            ))}
          </div>
          <button type="button" className="wzm-openbtn" onClick={openPixai}>Open pixai.art/profile/edit/api ↗</button>
          <div className="wzm-divider" />
          <div className="wzm-fieldlbl">YOUR API KEY</div>
          <div className="wzm-keyrow">
            <input className="wzm-keyinput" type={showKey ? "text" : "password"} value={apiKey}
              placeholder="paste your PixAI API key" autoFocus
              onChange={(e) => onApiKeyChange(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") authenticate(); }} disabled={authBusy} />
            <button type="button" className="wzm-eyebtn" onClick={() => setShowKey((v) => !v)}>
              {showKey ? "Hide" : "Show"}
            </button>
          </div>
          {authError ? <div className="wzm-errnote">{authError}</div> : null}
          <button type="button" className={"wzm-authbtn wzm-metal" + (!canAuth ? " disabled" : "")}
            onClick={authenticate} disabled={!canAuth}>
            {authBusy ? <span className="wzm-spin" /> : null}
            <span>{authBusy ? "Authenticating…" : "Authenticate"}</span>
          </button>
          <div className="wzm-footnote">Stored locally — nothing else leaves this machine.</div>
          <div className="wzm-lore">a library against the Void</div>
        </div>
      </div>
    );
  }

  if (phase === "sync") {
    const label = syncError ? "Sync interrupted" : progress ? "Syncing your library…" : "Connecting to PixAI…";
    return (
      <div className="wzm-stage">
        <div className="wzm-wash wzm-wash-a" />
        <div className="wzm-wash wzm-wash-b" />
        <div className="wzm-card">
          <div className="wzm-toprow"><div className="wzm-kicker">FIRST-TIME SETUP</div></div>
          <div className="wzm-syncwrap">
            <div className="wzm-syncmascotbox">
              <div className="wzm-synchalo" />
              <img className="wzm-syncmascotimg" src="/branding/mascots/nel_narrator.png" alt="" />
            </div>
            <div className="wzm-synchead">{label}</div>
            <div className="wzm-synctrack">
              <i className={"wzm-syncbar" + (progress ? "" : " indeterminate")}
                style={progress ? { width: (progress.pct != null ? progress.pct : 0) + "%" } : undefined} />
            </div>
            {progress ? (
              <div className="wzm-revealrow">
                <div className="wzm-reveal">
                  <b className="wzm-reveal-v">{progress.done}{progress.total ? " / " + progress.total : ""}</b>
                  <span className="wzm-reveal-k">Synced</span>
                </div>
                <div className="wzm-reveal">
                  <b className="wzm-reveal-v">{progress.new || 0}</b>
                  <span className="wzm-reveal-k">New</span>
                </div>
              </div>
            ) : <div className="wzm-revealrow" />}
            {syncError ? (
              <>
                <div className="wzm-syncerr">{syncError}</div>
                <button type="button" className="wzm-retrybtn wzm-metal" onClick={startSync}>Try again</button>
              </>
            ) : null}
          </div>
          <div className="wzm-lore">a library against the Void</div>
        </div>
      </div>
    );
  }

  // phase === "ready"
  const images = finalStats ? Number(finalStats.images || 0).toLocaleString() : "—";
  const videos = finalStats ? Number(finalStats.videos || 0).toLocaleString() : "—";
  const collections = finalStats ? Number(finalStats.collections || 0).toLocaleString() : "—";
  return (
    <div className="wzm-stage">
      <div className="wzm-wash wzm-wash-a" />
      <div className="wzm-wash wzm-wash-b" />
      <div className="wzm-card">
        <div className="wzm-toprow"><div className="wzm-kicker">FIRST-TIME SETUP</div></div>
        <div className="wzm-readywrap">
          <div className="wzm-readymark">✦</div>
          <div className="wzm-readyhead">Welcome home.</div>
          <div className="wzm-readybody">{images} images · {videos} videos · {collections} collections — every spark, kept.</div>
          <button type="button" className="wzm-enterbtn wzm-metal" onClick={enter}>Enter the Athenaeum →</button>
        </div>
        <div className="wzm-lore">a library against the Void</div>
      </div>
    </div>
  );
}
