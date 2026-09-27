import React from "react";
import {
  unlimitedBlock, unlimitedDaysText, unlimitedOffered, unlimitedPatch, unlimitedRules,
} from "../gen/genCore.js";
import "../styles/unlimited.css";

/* Tsubaki.3 Unlimited Mode -- the toggle row and the prompt strip, shared by the desktop dock
   (GenerateDrawer.jsx) and the phone Create screen (CreateMobile.jsx). SCOPE_2026-09-26_
   unlimited-mode C2/C4; pixel source: moonglade-internal/design/notes/tsubaki3-features/
   pixai-unlimited-mode-toggle.png and pixai-unlimited-mode-prompt-strip.png, rebuilt in the
   app's tokens (the lane's hue is the fixed --green token -- every skin redefines --emerald, and Nightfallen's
   is lavender -- the mark is ∞).

   Both read and write useGenerate's own `s` / `set` -- no state of their own. The logic is
   genCore.js's (unlimitedOffered / unlimitedBlock / unlimitedPatch ...), so the node suite pins
   the rules and these two only draw them. */

/* C2: the bordered green card under the model card -- "∞ Tsubaki.3 Unlimited Mode", a help
   mark carrying the rules, the switch on the right, "N days left" under it. Rendered only while
   the applied version offers the lane. Turning it ON is refused while something would make the
   server refuse the run (a reference picture, a size over the lane's limit): the switch reads
   disabled with the reason as its title and the reason on one line under it. Turning it OFF is
   never refused. */
export function UnlimitedRow({ s, set, phone }) {
  const m = s.model;
  if (!unlimitedOffered(m)) return null;
  const on = !!s.unlimited;
  const why = unlimitedBlock(s);
  const blocked = !on && !!why;
  const days = unlimitedDaysText(m);
  return (
    <div className={"mgunl-row" + (phone ? " phone" : "") + (on ? " on" : "")}>
      <div className="mgunl-head">
        <span className="mgunl-mark" aria-hidden="true">∞</span>
        <span className="mgunl-title">Tsubaki.3 Unlimited Mode</span>
        <span className="mgunl-help" title={unlimitedRules(m)} aria-label={unlimitedRules(m)}>?</span>
        <span className="sp" />
        <label className={"mgunl-sw" + (blocked ? " off" : "")}
          title={blocked ? why : on ? "Turn Unlimited Mode off" : "Turn Unlimited Mode on"}>
          <input type="checkbox" checked={on} disabled={blocked}
            aria-label="Tsubaki.3 Unlimited Mode"
            onChange={(e) => set(unlimitedPatch(e.target.checked))} />
          <span className="mgunl-track"><i /></span>
        </label>
      </div>
      {days ? <div className="mgunl-days">{days}</div> : null}
      {why ? <div className="mgunl-why">{why}</div> : null}
    </div>
  );
}

/* C4: the band over the prompt while the lane is on -- "∞ Unlimited Mode is on" in green on
   the left, "Turn off" on the right. It stays up whatever model is applied (§8.1): with the
   switch on over a version that does not offer the lane, this is where it is turned off, and
   the cost badge carries the server's refusal. */
export function UnlimitedStrip({ s, set, phone }) {
  if (!s.unlimited) return null;
  return (
    <div className={"mgunl-strip" + (phone ? " phone" : "")} role="status">
      <span className="mgunl-mark" aria-hidden="true">∞</span>
      <span className="mgunl-on">Unlimited Mode is on</span>
      <span className="sp" />
      <button type="button" className="mgunl-off" onClick={() => set(unlimitedPatch(false))}>
        Turn off
      </button>
    </div>
  );
}
