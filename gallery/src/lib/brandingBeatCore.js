/* THE BRANDING BEAT (Session L, decision 5) -- pure, and it imports NOTHING on purpose.

   The first time the Control Panel opens after the Branding tab is unlocked, the panel does
   one small thing: the old Branding tile cross-fades into "Branding & skins" (0.4 s), and then
   the ✦ Branding tab slides in beside Maintenance with one gold shimmer across its border
   (0.8 s, ease-out). Total 1.2 s. With reduced motion both are simply present -- the pointer
   tile and the tab, as they ship -- and the seen flag is still set. The flag is per account,
   in the account's preferences, so a second browser or the phone does not play it again.

   When the unlock celebration's button opened the panel, the beat plays on
   that open, BEFORE the panel switches to ✦ Branding: the panel holds on Maintenance for the
   1.2 s and then goes.

   This module decides only WHETHER and WHEN. The motion itself is CSS (styles/
   control-panel.css, "THE BRANDING BEAT"), whose durations loom/test/branding-beat.test.js
   pins against the numbers below. */

export const BEAT_KEY = "seen.branding-beat";

/* The two beats, in milliseconds. CSS carries the same numbers; the test holds them together. */
export const BEAT = { TILE_MS: 400, TAB_MS: 800, TOTAL_MS: 1200 };

/* What the panel does about the beat right now.
     off    nothing to do: the tab is not unlocked
     wait   unlocked, but the account's document has not arrived: hold the new pieces back
            for a moment rather than flash them and take them away
     seen   nothing to play -- the account has seen it, or has no store to ask (the beat is
            skipped, never allowed to hold the tab hostage): the tile and the tab are there
     play   first open, motion allowed: the cross-fade, then the tab
     rest   first open, reduced motion: both present at once; the flag is still set  */
export function beatPlan({ unlocked, status, seen, reduced }) {
  if (!unlocked) return "off";
  if (status === "error") return "seen";
  if (status !== "ready") return "wait";
  if (seen === true) return "seen";
  return reduced ? "rest" : "play";
}

/* Which half of the beat a moment falls in. */
export function beatPhase(elapsedMs) {
  if (!(elapsedMs >= 0)) return "tile";
  if (elapsedMs < BEAT.TILE_MS) return "tile";
  if (elapsedMs < BEAT.TOTAL_MS) return "tab";
  return "done";
}

/* Does the panel hold on Maintenance while the beat runs? Only when the panel was opened ON
   the Branding tab (the celebration's button), and only until the beat is over. */
export function holdsOnMaintenance(plan, phase) {
  return plan === "wait" || (plan === "play" && phase !== "done");
}

/* Is the ✦ Branding tab's button drawn yet? It is not while the account is still being
   asked, nor during the tile's half of the beat. */
export function tabVisible(plan, phase) {
  if (plan === "off") return false;
  if (plan === "wait") return false;
  if (plan === "play") return phase === "tab" || phase === "done";
  return true;
}

/* How the pointer tile stands: "hold" (drawn, invisible), "in" (fading in over the old one),
   or "rest". */
export function tileState(plan, phase) {
  if (plan === "wait") return "hold";
  if (plan === "play" && phase === "tile") return "in";
  return "rest";
}
