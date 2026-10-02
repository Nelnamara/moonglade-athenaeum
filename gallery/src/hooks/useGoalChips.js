import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet } from "../api.js";
import { peek, put } from "./swrCache.js";
import useAccountPrefs from "./useAccountPrefs.js";
import { lastAchievements, onAchievements, onCelebration, celebrationUp, openFolio } from "../notify/ach.js";
import { setFolioRow, folioHref } from "../folio/folioFocus.js";
import { PIN_KEY, pinnedId, vigilInHeader, pinView, pinEarned, vigilView } from "../folio/goalCore.js";

/* useGoalChips -- the header's two optional chips (Session O): the pinned goal (O4) and the
   Vigil (O5). One hook for every shell that draws them (the gallery and dock's separator bar, the
   Loom's header, the phone's row above the tab bar), so they can never disagree.

   WHERE ITS DATA COMES FROM. The pin and the switch live in the account's own preferences (the
   wave-1 store); the numbers come from /api/achievements, which the notify engine (notify/
   ach.js) already reads at boot and after every generation -- so the chips subscribe to those
   answers and make NO read of their own while that is happening. The one exception is a shell
   the engine has not answered for yet: with a pin or the switch on and nothing in hand, one
   plain read fills it in. A read; it writes nothing.

   WHAT WRITES. Only three things, and only on their own trigger: a click on a pin (in the Folio,
   elsewhere), the x / a swipe (unpin), and the Vigil switch. Opening the app writes nothing. The
   one automatic write is the pin clearing itself when the marking read reports the goal newly
   EARNED -- the earn toast is playing then, and the chip goes with it. An honor found already
   earned on open just draws no chip (pinView is null for it), with nothing written.

   HIDDEN DURING A CELEBRATION. `hidden` is true while anything in the celebration band (z 510-520)
   is on screen (notify/ach.js celebrationUp), so a chip never crowds a toast or a moment. */
export default function useGoalChips() {
  const prefs = useAccountPrefs();
  const pin = pinnedId(prefs.prefs);
  const vigilOn = vigilInHeader(prefs.prefs);
  const [data, setData] = useState(() => lastAchievements() || peek("/api/achievements"));
  const [hidden, setHidden] = useState(() => celebrationUp());

  const pinRef = useRef(pin);
  pinRef.current = pin;
  const unsetRef = useRef(prefs.unset);
  unsetRef.current = prefs.unset;

  useEffect(() => onAchievements((d, marked) => {
    setData(d);
    if (marked && pinEarned(pinRef.current, d.newly)) unsetRef.current(PIN_KEY);
  }), []);
  useEffect(() => onCelebration(setHidden), []);

  const wanted = !!pin || vigilOn;
  const have = !!data;
  useEffect(() => {
    if (!wanted || have) return undefined;
    let dead = false;
    apiGet("/api/achievements").then((d) => {
      if (dead || !d || d.error) return;
      put("/api/achievements", d);
      setData(d);
    });
    return () => { dead = true; };
  }, [wanted, have]);

  const view = pinView(data && data.achievements, pin);
  const vigil = vigilView(data && data.vigil);

  const unpin = useCallback(() => { prefs.unset(PIN_KEY); }, [prefs]);
  const openPinned = useCallback(() => {
    const id = pinRef.current;
    if (!id) return;
    setFolioRow(id);
    if (!openFolio()) window.location.href = folioHref(id);   // the Loom has no Folio
  }, []);

  return { ready: prefs.ready, pin: view, vigil: vigilOn ? vigil : null, vigilOn, hidden, unpin, openPinned };
}
