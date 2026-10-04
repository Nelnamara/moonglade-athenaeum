import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import {
  BUBBLE_MS, bubbleSide, isStandalone, nudgePlatform, readAndClearSignedIn, shouldNudge,
} from "../lib/installNudge.js";
import { readNudgeOff, writeNudgeOff } from "../lib/phonePrefs.js";

/* The Home Screen nudge's state (Session U, U6c + U7b; the rules are lib/installNudge.js's).

   THE BROWSER'S OWN INSTALL PROMPT is held back from the moment this module runs -- it ships in the
   bundle, so it is listening before the browser decides to offer -- and fired only by a tap on the
   strip. On a device where the nudge was waved off (✕) it is left alone, and the browser keeps its own
   way of offering the app. A prompt can be shown once; after that (accepted or not) the browser no
   longer offers it here and the strip goes. An install anywhere else ends it too.

   THE SIGN-IN MARK is read once per page load and taken away (installNudge.readAndClearSignedIn), so the
   strip shows on the visit a sign-in lands on and not again on a reload.

   NOTHING WRITES ON OPEN: the one write is the ✕ (writeNudgeOff). */

let deferred = null;
const subs = new Set();
const emit = () => subs.forEach((f) => { try { f(); } catch { /* a reader threw; the state is set */ } });
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("beforeinstallprompt", (e) => {
    if (readNudgeOff()) return;
    e.preventDefault();
    deferred = e;
    emit();
  });
  window.addEventListener("appinstalled", () => { deferred = null; emit(); });
}
function subscribe(cb) { subs.add(cb); return () => subs.delete(cb); }

/* Fire the held prompt: one prompt, its own answer; never retried. */
async function firePrompt() {
  const e = deferred;
  if (!e) return "unavailable";
  deferred = null;
  emit();
  try {
    await e.prompt();
    const choice = await e.userChoice;
    return (choice && choice.outcome) || "dismissed";
  } catch {
    return "unavailable";
  }
}

let signedIn = null;
function signedInOnce() {
  if (signedIn === null) signedIn = readAndClearSignedIn();
  return signedIn;
}

function standaloneNow() {
  let display = false;
  try { display = !!(window.matchMedia && window.matchMedia("(display-mode: standalone)").matches); } catch { display = false; }
  return isStandalone({ displayStandalone: display, navigatorStandalone: typeof navigator !== "undefined" ? navigator.standalone : undefined });
}

/* {show, platform, open, dismiss, bubble, closeBubble}: `show` is the strip; `open` is its tap (the
   bubble on iOS, the browser's prompt on Android); `bubble` is "" | "bottom" | "top". */
export default function useInstallNudge({ landscape = false } = {}) {
  const canPrompt = useSyncExternalStore(subscribe, () => !!deferred, () => false);
  const [dismissed, setDismissed] = useState(() => readNudgeOff());
  const [justSignedIn] = useState(() => signedInOnce());
  const [env] = useState(() => ({
    ua: typeof navigator !== "undefined" ? navigator.userAgent : "",
    standalone: standaloneNow(),
  }));
  const platform = nudgePlatform({ ua: env.ua, standalone: env.standalone, canPrompt });
  const show = shouldNudge({ signedIn: justSignedIn, dismissed, platform });
  const [bubble, setBubble] = useState("");

  const dismiss = useCallback(() => { writeNudgeOff(); setDismissed(true); setBubble(""); }, []);
  const closeBubble = useCallback(() => setBubble(""), []);
  const open = useCallback(() => {
    if (platform === "ios") { setBubble(bubbleSide(landscape)); return; }
    if (platform === "android") firePrompt();
  }, [platform, landscape]);

  /* The bubble closes on any tap (armed after the tap that opened it), or after 8 s. */
  useEffect(() => {
    if (!bubble) return undefined;
    const t = setTimeout(() => setBubble(""), BUBBLE_MS);
    const close = () => setBubble("");
    const arm = setTimeout(() => document.addEventListener("pointerdown", close, true), 0);
    return () => {
      clearTimeout(t);
      clearTimeout(arm);
      document.removeEventListener("pointerdown", close, true);
    };
  }, [bubble]);

  return { show, platform, open, dismiss, bubble, closeBubble };
}
