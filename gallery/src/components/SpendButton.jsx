import React from "react";
import { spendView } from "../gen/spendButtonCore.js";
import "../styles/spend-button.css";

/* SpendButton -- a button that spends, with its price on a second line inside it (3.21.x look
   pick round 2, topic 1 option B; moonglade-internal/design/board/LOOK_BOARD_2026-11-19_round2.html
   #price). The words are gen/spendButtonCore.js's; this file only draws them.

   It keeps the HOST's own button: `className` is the class the surface already used
   (.mgdock-gen, .cm-generate, .mgd-go, .lv-go, ...), so the size, the metal and the disabled
   look are the ones the app already has. What it adds is the second line and the emerald ring
   for a free answer -- the look board's .gbtn .s / .free, nothing else.

   THE SPEND LOGIC IS THE HOST'S. `onPress` is the host's own send (its latch, its probe gate,
   its quote, its hold); this button calls it exactly as the host's old onClick did, on the
   first press. What the button decides is only whether it may be pressed: `disabled` (the
   host's own gates) OR not priced -- the board's "stays dim until it knows".

   Props:
     quote      <CostBadge>'s onCost detail for this send (null = not priced yet)
     label      the action ("✦ Generate"); `busyLabel` replaces it while the host is busy
     idle       short "not priced yet" words for the second line ("pick a model first")
     sends      how many times the priced request goes out (a Matrix): the total is said
     disabled   the host's own gates
     className, title, offClass ("off": the host's dim class), id, aria-label */

export default function SpendButton({
  quote, label, busyLabel, busy, idle, sends, disabled, onPress,
  className = "", offClass = "off", title, id, "aria-label": ariaLabel,
}) {
  const view = spendView(quote, { idle, sends });
  const off = !!disabled || !!busy || !view.priced;

  const press = (e) => {
    if (off) return;
    if (onPress) onPress(e);
  };

  const cls = (className ? className + " " : "") + "mgspend"
    + (view.free && !off ? " free" : "") + (off && offClass ? " " + offClass : "");
  const tip = [title, view.title].filter(Boolean).join(" — ") || undefined;
  return (
    <button type="button" id={id} className={cls} disabled={off} onClick={press}
      title={tip} aria-label={ariaLabel}
      data-priced={view.priced ? "1" : undefined} data-free={view.free ? "1" : undefined}>
      <span className="mgspend-a">{busy && busyLabel ? busyLabel : label}</span>
      <span className="mgspend-s">{view.sub}{view.lane ? <span className="mgspend-inf">∞</span> : null}</span>
    </button>
  );
}
