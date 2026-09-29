import React from "react";
import useDataSaver from "../hooks/usePhonePrefs.js";
import { SAVER_LABELS, SAVER_MODES } from "../lib/phoneCore.js";
import "../styles/phone-q.css";

/* The Data saver row in the Control tab (Session Q, Q7; Phone Handoff.dc.html, the "Data saver" card):
   a switch, three modes -- Off, Auto on metered (the default) and Always -- and the one sentence of what
   it does. The value is per device (lib/phonePrefs.js, browser storage) and is written by a TAP on this
   row and nowhere else; opening Control writes nothing.

   The switch is the page's own shortcut: on it turns the saver Always, off it turns it Off; while Auto is
   acting (a metered connection) it reads as on, and flipping it then means "stop", i.e. Off.

   The sub line is honest about Auto (lib/phoneCore.js saverSub): where the browser has the Network
   Information API and reports the connection type (Chrome on Android) Auto follows it; where it cannot
   tell -- every iPhone browser -- Auto stays off and the row says so and points at Always. The page's
   "Network in this demo" switch was a stand-in for the connection and is not built. */

export default function DataSaverRow() {
  const s = useDataSaver();
  return (
    <div className="ctm-saver" role="group" aria-label="Data saver">
      <div className="ctm-saver-head">
        <div className="ctm-saver-title">
          <b>Data saver</b>
          <span>{s.sub}</span>
        </div>
        <button type="button" role="switch" aria-checked={s.active} aria-label="Data saver"
          className={"ctm-saver-switch" + (s.active ? " on" : "")}
          onClick={() => s.setMode(s.active ? "off" : "always")}>
          <i />
        </button>
      </div>
      <div className="ctm-saver-modes" role="radiogroup" aria-label="Data saver mode">
        {SAVER_MODES.map((m) => (
          <button key={m} type="button" role="radio" aria-checked={s.mode === m}
            className={s.mode === m ? "on" : ""} onClick={() => s.setMode(m)}>{SAVER_LABELS[m]}</button>
        ))}
      </div>
      <div className="ctm-saver-note">
        While on: thumbnails are 256 px, full size loads only when you open a picture, videos don{"’"}t
        autoplay, and sync waits for Wi-Fi.
      </div>
    </div>
  );
}
