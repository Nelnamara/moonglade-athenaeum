import React, { useRef, useState } from "react";
import useFlavour from "../hooks/useFlavour.js";
import "../styles/login.css";

/* The React sign-in AND first-run account-creation page (design spec:
   Login.dc.html / Login Mobile.dc.html, account-creation toggle added
   2026-08-02 per design_handoff/request-bootstrap-account-creation.md's
   answered brief), wired to the real POST /api/login. Rendered by main.jsx
   in place of <App> whenever boot.authenticated is false; App.jsx itself
   never mounts, so nothing here can accidentally fire an authenticated-only
   fetch.

   MODE is not a toggle here, unlike the DC: `boot.no_accounts` already
   decides server-side which form could ever succeed (see login()'s route --
   the React shell only reaches this zero-accounts state at all when
   bootstrap_mode is genuinely true: local request, no account yet), so
   there is exactly one meaningful mode per visitor. The DC's own note says
   as much ("real visibility is gated server-side... the toggle always shows
   here for review") -- it's demo convenience for reviewing both states in
   one prototype, not a real interaction to ship. Showing a link to a mode
   that would always fail for this visitor isn't a real UI, so the
   "First time? Create an account" / "Back to sign in" toggle links are the
   one thing NOT ported from this pass -- everything else (copy, fields,
   validation, hints, errors) for whichever single mode applies is built in
   full.

   Client-side username/password checks (usernameProblem/passwordProblem/
   isRepeatedOrSequential/passwordWeak below) are ported verbatim from the
   DC's own JS, which itself mirrors the real core.username_problem()/
   password_problem() -- proactive UX only; the server re-validates
   everything regardless.

   THREE other deliberate departures from the DC, all disclosed:
   - Timing: the DC's signIn()/createAccount() are demos -- 2200ms then
     5600ms of hardcoded setTimeouts before "succeeding" and hard-navigating.
     The busy phase here lasts exactly as long as the real fetch takes, and
     the welcome phase navigates the INSTANT it's set -- no artificial hold
     (an earlier pass added one; removed after it broke a real
     login-then-navigate test expectation -- see git history).
   - Sign-in error state: the DC has none for it ("it always succeeds").
     Reuses Setup Wizard.dc.html's already-designed inline error-note
     treatment (login.css's .lgn-error) rather than inventing a new one.
   - The DC distinguishes a calmer, non-red banner style for the rare
     "remote device" refusal vs. red for expired/locked-out, previewable via
     three demo-only "preview:" chips. Not shipped: that refusal can only
     reach a real visitor via an extreme race (is_local flipping between
     page load and submit), not a state the UI needs to rehearse, and the
     chips are explicitly demo tooling. Every real error still surfaces,
     just through the one .lgn-error style already used everywhere else on
     this page. */

const WELCOMES = [
  "The gallery is waking",
  "The void retreats",
  "A light in the Nightmare",
  "The lanterns are lit",
];

// Mirrors core.username_problem() / password_problem() (moonglade_backup.py) --
// one shared policy with the Panel's "Add user" flow, restated here for the
// proactive client-side check. The server is the real authority either way.
const COMMON_PASSWORDS = new Set([
  "password", "12345678", "qwertyui", "password1", "iloveyou", "admin1234", "letmein11",
]);
function usernameProblem(u) {
  if (!u.trim()) return "Username is required.";
  if (u.length > 64) return "Username must be at most 64 characters.";
  if (/[\x00-\x1f\x7f]/.test(u)) return "Username can't contain control characters.";
  return "";
}
function isRepeatedOrSequential(p) {
  if (/^(.)\1+$/.test(p)) return true;
  let asc = true, desc = true;
  for (let i = 1; i < p.length; i++) {
    const d = p.charCodeAt(i) - p.charCodeAt(i - 1);
    if (d !== 1) asc = false;
    if (d !== -1) desc = false;
  }
  return asc || desc;
}
function passwordWeak(p) {
  return p.length >= 8 && (COMMON_PASSWORDS.has(p.toLowerCase()) || isRepeatedOrSequential(p));
}
function passwordProblem(p) {
  if (p.length < 8) return "Password must be at least 8 characters.";
  if (passwordWeak(p)) return "That password is too common to be safe. Pick something less guessable.";
  return "";
}

// Mirrors classic LOGIN_HTML's data-fb ladder exactly (moonglade_gallery.py):
// webp (animated) -> still png -> the mascots/ copies -> the generic narrator.
const MASCOT_FALLBACKS = [
  "/branding/login_nel.png",
  "/branding/mascots/login_nel.webp",
  "/branding/mascots/login_nel.png",
  "/branding/mascots/gen_nel.png",
];
function onMascotError(e) {
  const img = e.currentTarget;
  const tried = Number(img.dataset.fb || 0);
  if (tried < MASCOT_FALLBACKS.length) {
    img.dataset.fb = String(tried + 1);
    img.src = MASCOT_FALLBACKS[tried];
  } else {
    img.style.display = "none";
  }
}

export default function LoginPage({ boot }) {
  // Three states, decided server-side and read from boot:
  //  - signin: an account exists.
  //  - create: no account yet AND this IS the machine running the server (bootstrap).
  //  - lanFirstRun: no account yet AND a REMOTE/LAN device -- it can't create the first
  //    account (server-only, enforced), so show a message instead of a form it can't use.
  //    This is the state that used to fall back to the classic LOGIN_HTML page (2026-08-07).
  const lanFirstRun = boot.no_accounts && boot.is_local === false;
  const createMode = boot.no_accounts && !lanFirstRun;

  const [user, setUser] = useState("");
  const [pass, setPass] = useState("");
  const [createUser, setCreateUser] = useState("");
  const [createPass, setCreatePass] = useState("");
  const [createConfirm, setCreateConfirm] = useState("");
  const [createSubmitted, setCreateSubmitted] = useState(false);
  const [usernameErr, setUsernameErr] = useState("");
  const [matchErr, setMatchErr] = useState("");

  const [phase, setPhase] = useState("idle"); // idle | busy | welcome
  const [error, setError] = useState("");
  const [welcomeLine] = useState(() => WELCOMES[Math.floor(Math.random() * WELCOMES.length)]);
  const fl = useFlavour(undefined, boot.build_stamp);

  const busy = phase === "busy";

  // The server rotates the CSRF token on every FAILED attempt (same contract as
  // the classic form, which re-rendered with a fresh token) and hands the new
  // one back in the error payload -- adopt it or every retry after one failure
  // would die with "session expired".
  const csrfRef = useRef(boot.csrf || "");
  const submitLogin = async (payload) => {
    let d;
    try {
      const r = await fetch("/api/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, csrf: csrfRef.current, next: boot.next || "" }),
      });
      d = await r.json();
    } catch {
      setPhase("idle");
      setError("Couldn't reach the server. Check your connection and try again.");
      return;
    }
    if (d.csrf) csrfRef.current = d.csrf;
    if (d.error) {
      setPhase("idle");
      setError(d.error);
      return;
    }
    setPhase("welcome");
    window.location.href = d.next || "/";
  };

  const signIn = () => {
    if (phase !== "idle") return;
    setPhase("busy");
    setError("");
    submitLogin({ username: user, password: pass });
  };

  const createAccount = () => {
    if (phase !== "idle") return;
    const uErr = usernameProblem(createUser);
    const pErr = passwordProblem(createPass);
    const mErr = createConfirm !== createPass ? "Passwords do not match." : "";
    setCreateSubmitted(true);
    setUsernameErr(uErr);
    setMatchErr(mErr);
    setError("");
    // A password problem alone blocks submit with no separate banner --
    // the hint list right below the field already says why (✓/· marks),
    // matching the DC's own choice not to duplicate that as red text too.
    if (uErr || pErr || mErr) return;
    setPhase("busy");
    submitLogin({
      mode: "create", username: createUser, password: createPass, confirm: createConfirm,
    });
  };

  const onKey = (e) => { if (e.key === "Enter") (createMode ? createAccount() : signIn()); };

  const lenOk = createPass.length >= 8;
  const guessOk = lenOk && !passwordWeak(createPass);

  return (
    <div className="lgn-stage">
      <div className="lgn-wash lgn-wash-a" />
      <div className="lgn-wash lgn-wash-b" />
      <div className="lgn-frame">
        <div className={"lgn-mascot" + (phase !== "idle" ? " peeked" : "")}>
          <div className="lgn-mascot-bob">
            {/* Same animated-or-still fallback ladder classic /login's inline
                <img data-fb=...> carries (moonglade_gallery.py, LOGIN_HTML) --
                webp (animated) wins, then still art, then the mascots/ copies,
                then the generic gen_nel narrator, before finally giving up.
                A real regression fixed once already (owner: real login_nel.webp
                art rendered nothing because the login screen was built later
                and never carried that context) -- ported here rather than
                left at "just hide on error". */}
            <img src="/branding/login_nel.webp" alt="" onError={onMascotError} />
          </div>
        </div>
        <div className="lgn-card">
          <div className="lgn-mark">
            {boot.mark_url ? <img src={boot.mark_url} alt="" /> : null}
          </div>
          <div className="lgn-titlewrap">
            <div className="lgn-title">Moonglade Athenaeum</div>
            {createMode ? (
              <div className="lgn-framing">You're setting up this server — this account will own it.</div>
            ) : lanFirstRun ? (
              <div className="lgn-framing">Not set up yet</div>
            ) : (
              <div className={"lgn-tagline" + (fl.fading ? " fading" : "")}
                onClick={fl.reveal} title="Click for version info">
                {fl.text}
              </div>
            )}
          </div>

          {lanFirstRun && (
            <div className="lgn-fieldin">
              <div className="lgn-error" style={{ marginTop: 0 }}>
                No account has been set up yet. Whoever runs this server needs to sign in
                from the machine itself first — the first account can only be created there,
                not from another device.
              </div>
            </div>
          )}

          {!createMode && !lanFirstRun && (
            <>
              <div className="lgn-lbl">USERNAME</div>
              <input className="lgn-input" name="username" value={user} autoFocus autoComplete="username"
                maxLength={64}
                onChange={(e) => setUser(e.target.value)} onKeyDown={onKey} disabled={busy} />
              <div className="lgn-lbl" style={{ paddingTop: 14 }}>PASSWORD</div>
              <input className="lgn-input lgn-pass" name="password" type="password" value={pass}
                autoComplete="current-password"
                onChange={(e) => setPass(e.target.value)} onKeyDown={onKey} disabled={busy} />
              {error ? <div className="lgn-error">{error}</div> : null}
              <button type="submit" className={"lgn-signbtn" + (busy ? " busy" : "")}
                onClick={signIn} disabled={busy}>
                {busy ? <span className="lgn-spin" /> : null}
                <span>{busy ? "Signing in…" : "Sign in"}</span>
              </button>
            </>
          )}

          {createMode && (
            <div className="lgn-fieldin">
              <div className="lgn-lbl">USERNAME</div>
              <input className={"lgn-input" + (createSubmitted && usernameErr ? " err" : "")}
                name="username" value={createUser} autoFocus autoComplete="username" maxLength={64}
                onChange={(e) => {
                  setCreateUser(e.target.value);
                  if (createSubmitted) setUsernameErr(usernameProblem(e.target.value));
                }}
                onKeyDown={onKey} disabled={busy} />
              {createSubmitted && usernameErr ? <div className="lgn-fielderr">{usernameErr}</div> : null}

              <div className="lgn-lbl" style={{ paddingTop: 14 }}>PASSWORD</div>
              <input className="lgn-input lgn-pass" name="new-password" type="password"
                value={createPass} autoComplete="new-password"
                onChange={(e) => {
                  const v = e.target.value;
                  setCreatePass(v);
                  if (createSubmitted && createConfirm) {
                    setMatchErr(createConfirm !== v ? "Passwords do not match." : "");
                  }
                }}
                onKeyDown={onKey} disabled={busy} />
              <div className="lgn-hints">
                <div className={lenOk ? "ok" : ""}>{lenOk ? "✓" : "·"} at least 8 characters</div>
                <div className={guessOk ? "ok" : ""}>{guessOk ? "✓" : "·"} not a common password or a simple pattern (like 12345678)</div>
              </div>

              <div className="lgn-lbl" style={{ paddingTop: 14 }}>CONFIRM PASSWORD</div>
              <input className={"lgn-input lgn-pass" + (matchErr ? " err" : "")}
                name="confirm-password" type="password" value={createConfirm}
                autoComplete="new-password"
                onChange={(e) => {
                  const v = e.target.value;
                  setCreateConfirm(v);
                  if (createSubmitted) setMatchErr(v !== createPass ? "Passwords do not match." : "");
                }}
                onKeyDown={onKey} disabled={busy} />
              {matchErr ? <div className="lgn-fielderr">{matchErr}</div> : null}

              {error ? <div className="lgn-error">{error}</div> : null}

              <button type="submit" className={"lgn-signbtn" + (busy ? " busy" : "")}
                onClick={createAccount} disabled={busy} style={{ marginTop: 16 }}>
                {busy ? <span className="lgn-spin" /> : null}
                <span>{busy ? "Creating account…" : "Create account"}</span>
              </button>
            </div>
          )}

          <div className="lgn-foot">single-user library · nothing leaves this machine</div>
        </div>
      </div>
      {phase === "welcome" ? (
        <div className="lgn-welcome">
          <div className="lgn-welcome-inner">
            <div className="lgn-welcome-title">
              {createMode ? "Welcome, " + createUser : "Welcome back" + (user ? ", " + user : "")}
            </div>
            <div className="lgn-welcome-line">{welcomeLine}</div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
