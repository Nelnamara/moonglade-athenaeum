import React, { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { accountPrefs } from "../hooks/useAccountPrefs.js";
import { readPref } from "../hooks/accountPrefsStore.js";
import {
  ASK_ARM_MS, SPEND_ASK_KEY, askText, askThreshold, pressAction, spendView,
} from "../gen/spendButtonCore.js";
import "../styles/spend-button.css";

/* SpendButton -- a button that spends, with its price on a second line inside it (3.21.x look
   pick round 2, topic 1 option B; moonglade-internal/design/board/LOOK_BOARD_2026-11-19_round2.html
   #price). The words are gen/spendButtonCore.js's; this file only draws them and holds the
   one-time ask's armed state.

   It keeps the HOST's own button: `className` is the class the surface already used
   (.mgdock-gen, .cm-generate, .mgd-go, .lv-go, ...), so the size, the metal and the disabled
   look are the ones the app already has. What it adds is the second line, the emerald ring for
   a free answer and the gold ring of an armed confirm -- the look board's .gbtn .s / .free /
   .armed, nothing else.

   THE SPEND LOGIC IS THE HOST'S. `onPress` is the host's own send (its latch, its probe gate,
   its quote, its hold); this button calls it exactly as the host's old onClick did. What the
   button decides is only whether it may be pressed: `disabled` (the host's own gates) OR not
   priced -- the board's "stays dim until it knows".

   Props:
     quote      <CostBadge>'s onCost detail for this send (null = not priced yet)
     label      the action ("✦ Generate"); `busyLabel` replaces it while the host is busy
     idle       short "not priced yet" words for the second line ("pick a model first")
     sends      how many times the priced request goes out (a Matrix): the total is said
     disabled   the host's own gates
     ask        false where the host already asks before every paid send (the Loom's confirm,
                the Fixer's, a Run's) -- the one-time ask would be a second question
     className, title, offClass ("off": the host's dim class), id, aria-label */

const NOOP_SUB = () => () => {};
const NOOP_SNAP = () => null;

/* The account's ask amount (0 = off). Only a button that may ask reads the store. */
export function useAskThreshold(on = true) {
  const store = on ? accountPrefs() : null;
  const snap = useSyncExternalStore(store ? store.subscribe : NOOP_SUB,
    store ? store.getSnapshot : NOOP_SNAP, store ? store.getSnapshot : NOOP_SNAP);
  useEffect(() => { if (store) store.ensureLoaded(); }, [store]);
  return (on && snap) ? askThreshold(readPref(snap.prefs, SPEND_ASK_KEY, 0)) : 0;
}

export default function SpendButton({
  quote, label, busyLabel, busy, idle, sends, disabled, ask = true, onPress,
  className = "", offClass = "off", title, id, "aria-label": ariaLabel,
}) {
  const view = spendView(quote, { idle, sends });
  const threshold = useAskThreshold(ask);
  const [armed, setArmed] = useState(false);
  const timer = useRef(0);
  const off = !!disabled || !!busy || !view.priced;

  // An armed confirm belongs to the price it named: any change to the quote (or the button
  // going dim) stands it down, and so does the wait running out.
  useEffect(() => { setArmed(false); }, [view.state, view.total, off]);
  useEffect(() => {
    clearTimeout(timer.current);
    if (armed) timer.current = setTimeout(() => setArmed(false), ASK_ARM_MS);
    return () => clearTimeout(timer.current);
  }, [armed]);

  const press = (e) => {
    if (off) return;
    const act = pressAction(view, ask ? threshold : 0, armed);
    if (act === "arm") { setArmed(true); return; }
    if (act !== "send") return;
    setArmed(false);
    if (onPress) onPress(e);
  };

  const cls = (className ? className + " " : "") + "mgspend"
    + (view.free && !off ? " free" : "") + (armed ? " armed" : "") + (off && offClass ? " " + offClass : "");
  const tip = armed ? "Press again to send — this is above the amount you set to be asked about"
    : [title, view.title].filter(Boolean).join(" — ") || undefined;
  return (
    <button type="button" id={id} className={cls} disabled={off} onClick={press}
      onBlur={() => setArmed(false)} title={tip} aria-label={ariaLabel}
      data-priced={view.priced ? "1" : undefined} data-free={view.free ? "1" : undefined}
      data-armed={armed ? "1" : undefined}>
      {armed ? (
        <span className="mgspend-a">{askText(view)}</span>
      ) : (
        <>
          <span className="mgspend-a">{busy && busyLabel ? busyLabel : label}</span>
          <span className="mgspend-s">{view.sub}{view.lane ? <span className="mgspend-inf">∞</span> : null}</span>
        </>
      )}
    </button>
  );
}
