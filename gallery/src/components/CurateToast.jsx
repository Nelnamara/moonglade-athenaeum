import React from "react";
import "../styles/curation.css";

/* The toast a bulk change leaves behind: what happened, and -- for ten seconds -- Undo, which
   puts every picture back to its own previous values. One at a time; the next change replaces
   it. A refusal wears peach (never ruby). role=status so a screen reader hears the count. */
export default function CurateToast({ toast, onUndo, onDismiss }) {
  if (!toast) return null;
  return (
    <div className={"mgcu-toast" + (toast.tone === "peach" ? " peach" : "")} role="status">
      <div className="mgcu-toast-t">{toast.text}</div>
      {toast.prev || toast.undoFn ? (
        <button type="button" className="mgcu-toast-undo" onClick={onUndo}>Undo {"·"} {toast.secs}s</button>
      ) : (
        <button type="button" className="mgcu-toast-x" onClick={onDismiss} aria-label="Dismiss">{"✕"}</button>
      )}
    </div>
  );
}
