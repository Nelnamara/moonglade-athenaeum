import { useRef, useState } from "react";
import useFlavour from "./useFlavour.js";

/* All of LoginPage.jsx's state/handlers/validation/API-call logic, mechanically
   lifted out (2026-08-02) so LoginPageMobile.jsx can reuse it verbatim instead
   of a second copy drifting from the original -- same motivation useFlavour.js
   already states for itself. LoginPage.jsx (desktop) is untouched by this
   extraction: its own inline useState/handlers still work exactly as before,
   this hook is a byte-for-byte copy of that same logic, not a rewrite of it.
   If desktop is ever migrated onto this hook too, it should behave
   identically -- there is nothing device-specific in here, only presentation
   (JSX/CSS) differs between the two surfaces.

   Mirrors core.username_problem()/password_problem() (moonglade_backup.py) --
   one shared policy with the Panel's "Add user" flow. The server is the real
   authority either way; this is proactive client-side UX only. */

export const WELCOMES = [
  "The gallery is waking",
  "The void retreats",
  "A light in the Nightmare",
  "The lanterns are lit",
];

const COMMON_PASSWORDS = new Set([
  "password", "12345678", "qwertyui", "password1", "iloveyou", "admin1234", "letmein11",
]);

export function usernameProblem(u) {
  if (!u.trim()) return "Username is required.";
  if (u.length > 64) return "Username must be at most 64 characters.";
  if (/[\x00-\x1f\x7f]/.test(u)) return "Username can't contain control characters.";
  return "";
}
export function isRepeatedOrSequential(p) {
  if (/^(.)\1+$/.test(p)) return true;
  let asc = true, desc = true;
  for (let i = 1; i < p.length; i++) {
    const d = p.charCodeAt(i) - p.charCodeAt(i - 1);
    if (d !== 1) asc = false;
    if (d !== -1) desc = false;
  }
  return asc || desc;
}
export function passwordWeak(p) {
  return p.length >= 8 && (COMMON_PASSWORDS.has(p.toLowerCase()) || isRepeatedOrSequential(p));
}
export function passwordProblem(p) {
  if (p.length < 8) return "Password must be at least 8 characters.";
  if (passwordWeak(p)) return "That password is too common to be safe. Pick something less guessable.";
  return "";
}

// Mirrors classic LOGIN_HTML's data-fb ladder exactly (moonglade_gallery.py):
// webp (animated) -> still png -> the mascots/ copies -> the generic narrator.
export const MASCOT_FALLBACKS = [
  "/branding/login_nel.png",
  "/branding/mascots/login_nel.webp",
  "/branding/mascots/login_nel.png",
  "/branding/mascots/gen_nel.png",
];
export function onMascotError(e) {
  const img = e.currentTarget;
  const tried = Number(img.dataset.fb || 0);
  if (tried < MASCOT_FALLBACKS.length) {
    img.dataset.fb = String(tried + 1);
    img.src = MASCOT_FALLBACKS[tried];
  } else {
    img.style.display = "none";
  }
}

export default function useLogin(boot) {
  const mode = boot.no_accounts ? "create" : "signin";
  const createMode = mode === "create";

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

  // Server rotates the CSRF token on every FAILED attempt and returns the fresh
  // one in the error payload -- adopt it or retries after a failure would die
  // with "session expired" (see LoginPage.jsx's identical comment).
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
    // A password problem alone blocks submit with no separate banner -- the
    // hint list right below the field already says why (✓/· marks).
    if (uErr || pErr || mErr) return;
    setPhase("busy");
    submitLogin({
      mode: "create", username: createUser, password: createPass, confirm: createConfirm,
    });
  };

  const onKey = (e) => { if (e.key === "Enter") (createMode ? createAccount() : signIn()); };

  // Live re-validation, matching LoginPage.jsx's inline onChange handlers
  // exactly: only re-checks AFTER the first submit attempt, so a first-time
  // typist never sees a red error appear ahead of a submit.
  const onCreateUserChange = (v) => {
    setCreateUser(v);
    if (createSubmitted) setUsernameErr(usernameProblem(v));
  };
  const onCreatePassChange = (v) => {
    setCreatePass(v);
    if (createSubmitted && createConfirm) {
      setMatchErr(createConfirm !== v ? "Passwords do not match." : "");
    }
  };
  const onCreateConfirmChange = (v) => {
    setCreateConfirm(v);
    if (createSubmitted) setMatchErr(v !== createPass ? "Passwords do not match." : "");
  };

  const lenOk = createPass.length >= 8;
  const guessOk = lenOk && !passwordWeak(createPass);

  return {
    mode, createMode,
    user, setUser, pass, setPass,
    createUser, createPass, createConfirm,
    createSubmitted, usernameErr, matchErr,
    phase, busy, error, welcomeLine, fl,
    signIn, createAccount, onKey,
    onCreateUserChange, onCreatePassChange, onCreateConfirmChange,
    lenOk, guessOk,
  };
}
