import React from "react";
import useLogin, { onMascotError } from "../hooks/useLogin.js";
import "../styles/login-mobile.css";

/* The mobile-viewport presentation of LoginPage.jsx (design spec: Login
   Mobile.dc.html). Rendered by main.jsx in place of LoginPage.jsx whenever
   useIsMobile() is true -- the FIRST mobile surface in gallery/src, so the
   two patterns it establishes (a viewport hook in hooks/useIsMobile.js, and
   sharing state/handlers with a desktop sibling through a hook rather than a
   forked copy) are meant to be reused by whatever mobile surface comes next.

   Every piece of business logic -- the eight bits of form state, submitLogin/
   signIn/createAccount/onKey, the username/password validators, the mascot
   fallback ladder, and every error string -- comes from useLogin (hooks/
   useLogin.js, itself a byte-for-byte lift of LoginPage.jsx's own body) and
   is NOT re-derived here. This file is presentation only: layout, sizing, and
   the mascot peek/bob + blurred "Welcome back" transition specific to the
   mobile design comp (login-mobile.css). Desktop's LoginPage.jsx is untouched.

   Excluded, matching LoginPage.jsx's own documented call ("MODE is not a
   toggle here" -- see that file's header comment) for the identical reason:
   the DC's "First time? Create an account →" / "← Back to sign in" toggle
   links. boot.no_accounts already decides server-side which single form could
   ever succeed for this visitor (login()'s route); a visible toggle to a mode
   that would always fail isn't a real UI to ship on either surface.

   Also excluded, per Login Mobile.dc.html's own QA/design-tool-only
   affordances (build-spec research, section 8) -- a deliberate, documented
   cut, not a silent one:
   - the 3 "preview: expired" / "preview: locked out" / "preview: remote"
     demo chips and the client-only `demoError` state machine behind them --
     never wired to a real server response; every real error already surfaces
     through the one .lgnm-error line below, same as desktop's .lgn-error;
   - the DC's separate calm/red "remote device" banner variant that only
     those chips could ever trigger -- one error treatment for every real
     error, matching desktop's own documented choice.
   Kept (NOT a cut): the tap-to-reveal build version on the sign-in tagline
   (fl.reveal, from useFlavour.js) -- that is real, already-shipped product
   behavior on desktop, not the DC's separate demo-only `versionShown` branch. */

export default function LoginPageMobile({ boot }) {
  const {
    createMode,
    user, setUser, pass, setPass,
    createUser, createPass, createConfirm,
    createSubmitted, usernameErr, matchErr,
    phase, busy, error, welcomeLine, fl,
    signIn, createAccount, onKey,
    onCreateUserChange, onCreatePassChange, onCreateConfirmChange,
    lenOk, guessOk,
  } = useLogin(boot);

  return (
    <div className="lgnm-stage">
      <div className="lgnm-wash lgnm-wash-a" />
      <div className="lgnm-wash lgnm-wash-b" />
      <div className="lgnm-frame">
        <div className={"lgnm-mascot" + (phase !== "idle" ? " peeked" : "")}>
          <div className="lgnm-mascot-bob">
            {/* Same animated-or-still fallback ladder as desktop/classic --
                webp (animated) wins, then still art, then the mascots/
                copies, then the generic gen_nel narrator. */}
            <img src="/branding/login_nel.webp" alt="" onError={onMascotError} />
          </div>
        </div>
        <div className="lgnm-card">
          <div className="lgnm-mark">
            {boot.mark_url ? <img src={boot.mark_url} alt="" /> : null}
          </div>
          <div className="lgnm-titlewrap">
            <div className="lgnm-title">Moonglade Athenaeum</div>
            {createMode ? (
              <div className="lgnm-framing">You're setting up this server — this account will own it.</div>
            ) : (
              <div className={"lgnm-tagline" + (fl.fading ? " fading" : "")}
                onClick={fl.reveal} title="Click for version info">
                {fl.text}
              </div>
            )}
          </div>

          {!createMode && (
            <>
              <div className="lgnm-lbl" style={{ marginTop: 0 }}>USERNAME</div>
              <input className="lgnm-input" name="username" value={user} autoFocus autoComplete="username"
                maxLength={64}
                onChange={(e) => setUser(e.target.value)} onKeyDown={onKey} disabled={busy} />
              <div className="lgnm-lbl">PASSWORD</div>
              <input className="lgnm-input lgnm-pass" name="password" type="password" value={pass}
                autoComplete="current-password"
                onChange={(e) => setPass(e.target.value)} onKeyDown={onKey} disabled={busy} />
              {error ? <div className="lgnm-error">{error}</div> : null}
              <button type="submit" className={"lgnm-signbtn" + (busy ? " busy" : "")}
                onClick={signIn} disabled={busy}>
                {busy ? <span className="lgnm-spin" /> : null}
                <span>{busy ? "Signing in…" : "Sign in"}</span>
              </button>
            </>
          )}

          {createMode && (
            <div className="lgnm-fieldin">
              <div className="lgnm-lbl" style={{ marginTop: 0 }}>USERNAME</div>
              <input className={"lgnm-input" + (createSubmitted && usernameErr ? " err" : "")}
                name="username" value={createUser} autoFocus autoComplete="username" maxLength={64}
                onChange={(e) => onCreateUserChange(e.target.value)}
                onKeyDown={onKey} disabled={busy} />
              {createSubmitted && usernameErr ? <div className="lgnm-fielderr">{usernameErr}</div> : null}

              <div className="lgnm-lbl">PASSWORD</div>
              <input className="lgnm-input lgnm-pass" name="new-password" type="password"
                value={createPass} autoComplete="new-password"
                onChange={(e) => onCreatePassChange(e.target.value)}
                onKeyDown={onKey} disabled={busy} />
              <div className="lgnm-hints">
                <div className={lenOk ? "ok" : ""}>{lenOk ? "✓" : "·"} at least 8 characters</div>
                <div className={guessOk ? "ok" : ""}>{guessOk ? "✓" : "·"} not a common password or a simple pattern (like 12345678)</div>
              </div>

              <div className="lgnm-lbl">CONFIRM PASSWORD</div>
              <input className={"lgnm-input lgnm-pass" + (matchErr ? " err" : "")}
                name="confirm-password" type="password" value={createConfirm}
                autoComplete="new-password"
                onChange={(e) => onCreateConfirmChange(e.target.value)}
                onKeyDown={onKey} disabled={busy} />
              {matchErr ? <div className="lgnm-fielderr">{matchErr}</div> : null}

              {error ? <div className="lgnm-error">{error}</div> : null}

              <button type="submit" className={"lgnm-signbtn" + (busy ? " busy" : "")}
                onClick={createAccount} disabled={busy} style={{ marginTop: 14 }}>
                {busy ? <span className="lgnm-spin" /> : null}
                <span>{busy ? "Creating account…" : "Create account"}</span>
              </button>
            </div>
          )}

          <div className="lgnm-foot">single-user library · nothing leaves this machine</div>
        </div>
      </div>
      {phase === "welcome" ? (
        <div className="lgnm-welcome">
          <div className="lgnm-welcome-inner">
            <div className="lgnm-welcome-title">
              {createMode ? "Welcome, " + createUser : "Welcome back" + (user ? ", " + user : "")}
            </div>
            <div className="lgnm-welcome-line">{welcomeLine}</div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
