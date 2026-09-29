import { useEffect, useState } from "react";
import useAccountPrefs from "./useAccountPrefs.js";
import {
  BEAT, BEAT_KEY, beatPlan, holdsOnMaintenance, tabVisible, tileState,
} from "../lib/brandingBeatCore.js";

/* useBrandingBeat -- the Control Panel's one-time arrival of the Branding tab (Session L,
   decision 5). lib/brandingBeatCore.js decides whether and when; this is only the wiring:
   the account's own "seen" flag, the reduced-motion preference, and the two timers.

     const beat = useBrandingBeat(brandingUnlocked);
     beat.holds        -> the panel should stay on Maintenance (it was opened on Branding)
     beat.tabVisible   -> draw the ✦ Branding tab now
     beat.tabArriving  -> the tab is in its slide-and-shimmer half
     beat.tile         -> "hold" | "in" | "rest" for the pointer tile

   The flag is written when the beat ENDS (or at once under reduced motion), never on open: a
   panel closed halfway through has not shown the beat, so it plays again next time. */

function reducedMotion() {
  return !!(typeof window !== "undefined" && window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}

export default function useBrandingBeat(unlocked) {
  const prefs = useAccountPrefs();
  const seen = prefs.get(BEAT_KEY, false) === true;
  const plan = beatPlan({ unlocked, status: prefs.status, seen, reduced: reducedMotion() });
  const [phase, setPhase] = useState("tile");

  useEffect(() => {
    if (plan === "rest") { prefs.set(BEAT_KEY, true); return undefined; }
    if (plan !== "play") return undefined;
    const t1 = setTimeout(() => setPhase("tab"), BEAT.TILE_MS);
    const t2 = setTimeout(() => { setPhase("done"); prefs.set(BEAT_KEY, true); }, BEAT.TOTAL_MS);
    return () => { clearTimeout(t1); clearTimeout(t2); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan]);

  return {
    plan, phase,
    holds: holdsOnMaintenance(plan, phase),
    tabVisible: tabVisible(plan, phase),
    tabArriving: plan === "play" && phase === "tab",
    tile: tileState(plan, phase),
  };
}
