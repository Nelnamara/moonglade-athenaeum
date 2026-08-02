import React, { useState } from "react";
import useFlavour from "../hooks/useFlavour.js";
import "../styles/login.css";

/* The React sign-in page (design spec: Login.dc.html / Login Mobile.dc.html),
   wired to the real POST /api/login (2026-08-02) -- docs/DECISIONS.md's
   2026-07-31 feasibility map called this out by name as real, unfinished work.
   Rendered by main.jsx in place of <App> whenever boot.authenticated is false;
   App.jsx itself never mounts, so nothing here can accidentally fire an
   authenticated-only fetch.

   TWO deliberate departures from the DC, both disclosed:
   - Timing: the DC's signIn() is a demo -- 2200ms then 5600ms of hardcoded
     setTimeouts before it "succeeds" and hard-navigates. The busy phase here
     lasts exactly as long as the real fetch takes, and the welcome phase
     navigates the INSTANT it's set -- no artificial hold. An earlier pass
     added a fixed 900ms "let the welcome line be readable" delay; caught as
     exactly the fabricated-timing pattern this whole project has fought
     against (fake progress bars, fake sync stages) once it broke a real
     login-then-navigate expectation (tests/test_render_harness.py's
     `_login()` helper, which the render-harness's own `networkidle` wait
     doesn't and shouldn't account for a decorative client-side pause).
     Removed rather than accommodated: the welcome overlay still mounts and
     is visible for whatever the browser's real paint/unload timing is, just
     never gated behind a number this app made up.
   - Error state: the DC has none ("it always succeeds", per its own logic
     class). Reuses Setup Wizard.dc.html's already-designed inline error-note
     treatment (see login.css's .lgn-error) rather than inventing a new one.

   Bootstrap/first-run account creation is NOT here -- no design exists for it
   yet (see design_handoff/request-bootstrap-account-creation.md); that flow
   stays on classic /login exactly as before, unreachable from this page. */

const WELCOMES = [
  "The gallery is waking",
  "The void retreats",
  "A light in the Nightmare",
  "The lanterns are lit",
];

export default function LoginPage({ boot }) {
  const [user, setUser] = useState("");
  const [pass, setPass] = useState("");
  const [phase, setPhase] = useState("idle"); // idle | busy | welcome
  const [error, setError] = useState("");
  const [welcomeLine] = useState(() => WELCOMES[Math.floor(Math.random() * WELCOMES.length)]);
  const fl = useFlavour(undefined, boot.build_stamp);

  const busy = phase === "busy";

  const signIn = async () => {
    if (phase !== "idle") return;
    setPhase("busy");
    setError("");
    let d;
    try {
      const r = await fetch("/api/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: user, password: pass,
          csrf: boot.csrf || "", next: boot.next || "",
        }),
      });
      d = await r.json();
    } catch {
      setPhase("idle");
      setError("Couldn't reach the server. Check your connection and try again.");
      return;
    }
    if (d.error) {
      setPhase("idle");
      setError(d.error);
      return;
    }
    setPhase("welcome");
    window.location.href = d.next || "/";
  };

  const onKey = (e) => { if (e.key === "Enter") signIn(); };

  return (
    <div className="lgn-stage">
      <div className="lgn-wash lgn-wash-a" />
      <div className="lgn-wash lgn-wash-b" />
      <div className="lgn-frame">
        <div className={"lgn-mascot" + (phase !== "idle" ? " peeked" : "")}>
          <div className="lgn-mascot-bob">
            <img src="/branding/login_nel.webp" alt=""
              onError={(e) => { e.currentTarget.style.display = "none"; }} />
          </div>
        </div>
        <div className="lgn-card">
          <div className="lgn-mark">
            {boot.mark_url ? <img src={boot.mark_url} alt="" /> : null}
          </div>
          <div className="lgn-titlewrap">
            <div className="lgn-title">Moonglade Athenaeum</div>
            <div className={"lgn-tagline" + (fl.fading ? " fading" : "")}
              onClick={fl.reveal} title="Click for version info">
              {fl.text}
            </div>
          </div>
          <div className="lgn-lbl">USERNAME</div>
          {/* maxLength 64 matches core.MAX_WEB_USERNAME_LEN -- the same client-side
              belt to the server's braces the Panel's "Add user" field and the
              classic bootstrap form both already carry. */}
          <input className="lgn-input" name="username" value={user} autoFocus autoComplete="username"
            maxLength={64}
            onChange={(e) => setUser(e.target.value)} onKeyDown={onKey} disabled={busy} />
          <div className="lgn-lbl" style={{ paddingTop: 14 }}>PASSWORD</div>
          <input className="lgn-input lgn-pass" name="password" type="password" value={pass}
            autoComplete="current-password"
            onChange={(e) => setPass(e.target.value)} onKeyDown={onKey} disabled={busy} />
          {error ? <div className="lgn-error">{error}</div> : null}
          {/* type="submit" with no enclosing <form> -- purely a semantic/
              a11y match for "this is the primary submit control" (and what
              the render-harness's real-browser login helper looks for); the
              click still runs signIn() directly, nothing native to trigger. */}
          <button type="submit" className={"lgn-signbtn" + (busy ? " busy" : "")}
            onClick={signIn} disabled={busy}>
            {busy ? <span className="lgn-spin" /> : null}
            <span>{busy ? "Signing in…" : "Sign in"}</span>
          </button>
          <div className="lgn-foot">single-user library · nothing leaves this machine</div>
        </div>
      </div>
      {phase === "welcome" ? (
        <div className="lgn-welcome">
          <div className="lgn-welcome-inner">
            <div className="lgn-welcome-title">Welcome back{user ? ", " + user : ""}</div>
            <div className="lgn-welcome-line">{welcomeLine}</div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
