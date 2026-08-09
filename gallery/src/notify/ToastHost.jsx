import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { subscribe, dismiss } from "./toastStore.js";

/* ToastHost -- the React face of notify/toastStore.js (no-vanilla campaign, component 6):
   renders the #mg-toasts corner stack from the store's state, portaled to document.body so it
   stays a body-level sibling of #root (the z-index contract and contact-sheet-overlay.css's
   hide rule both depend on that). The store owns every timer; this component only paints.
   React's own escaping replaces the vanilla's esc() -- no innerHTML anywhere. */

export default function ToastHost() {
  const [toasts, setToasts] = useState([]);
  useEffect(() => subscribe(setToasts), []);

  return createPortal(
    <div id="mg-toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={"mg-toast" + (t.kind ? " " + t.kind : "") + (t.out ? " out" : "")}>
          <span className="mt-ic">{t.icon}</span>
          <div className="mt-main">
            <div className="mt-title">{t.title}</div>
            {t.msg ? <div className="mt-msg">{t.msg}</div> : null}
          </div>
          {t.thumb ? (
            <span className="mt-thumb" style={{ backgroundImage: "url('" + t.thumb.replace(/'/g, "%27") + "')" }} />
          ) : null}
          <button className="mt-x" aria-label="Dismiss" onClick={() => dismiss(t.id)}>×</button>
        </div>
      ))}
    </div>,
    document.body,
  );
}
