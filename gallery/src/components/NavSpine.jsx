import React, { useEffect, useState } from "react";
import "../styles/shell.css";

/* The glyph-spine nav — the DC separator-bar pills (Frontend Gallery.dc.html
   NAV_ORDER + drift §16): Panel and Log Out are PAGE navigations; the other six
   destinations open floating overlays. The overlays themselves are a parallel
   workstream (overlays/OverlayShell + six surfaces) — this component only
   reports the click via onOverlay(key). Items whose overlay hasn't shipped are
   `soon`-dimmed but STILL wired, so lighting one up is a one-flag change here
   plus mounting the surface at App.jsx's overlay mount point. */

const NAV = [
  // My Art + Contests (2026-08-02): real overlays now (MyArtOverlay.jsx /
  // ContestsOverlay.jsx), ported from the same Frontend Gallery DC these
  // pills always pointed at -- they had real, working backend routes
  // (/api/your-art, /api/contests) sitting unused the whole time.
  { label: "My Art", tip: "How your published art is doing", overlay: "myart" },
  { label: "Publish", tip: "Publish to PixAI", overlay: "publish" },
  { label: "Train", tip: "Train a LoRA on PixAI", overlay: "train" },
  // Import (2026-08-02): ported from classic's real, proven ImportUI
  // (moonglade_gallery.py's Web Import modal) -- same /api/import-local
  // contract, zero backend changes. See ImportOverlay.jsx's header comment.
  { label: "Import", tip: "Bring local files into the catalog — nothing goes to PixAI",
    overlay: "import", localOnly: true },
  { label: "Contests", tip: "Live PixAI contests", overlay: "contests" },
  // The REAL in-app overlay (HealthOverlay.jsx, ported from the Frontend
  // Gallery DC's ovHealth slab) -- the first of the six designed overlays to
  // land. Its two page-bounce stand-ins from earlier today are both dead.
  { label: "Health", tip: "Collection health dashboard", overlay: "health" },
  // Panel (2026-08-02): owner's live correction -- "Control panel is now ALSO
  // modal. no separate pages anymore" -- supersedes the DC's own page-based
  // design and this pill's former href:"/panel" full-page nav. ControlPanelOverlay.jsx.
  { label: "Panel", tip: "Control Panel — maintenance jobs, accounts, branding",
    overlay: "panel", gear: true },
  { label: "Log Out", tip: "End this session", logout: true },
];

/* Panel's 13×13 gear — rotates 90° on hover (CSS drives it via .mgx-nav-mark). */
function Gear() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor"
      strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="8" cy="8" r="2.4" />
      <path d="M8 1.6v1.9M8 12.5v1.9M1.6 8h1.9M12.5 8h1.9M3.5 3.5l1.3 1.3M11.2 11.2l1.3 1.3M12.5 3.5l-1.3 1.3M4.8 11.2L3.5 12.5" />
    </svg>
  );
}

/* Bridge §2 "The reveal" (The Bridge.dc.html 137-190): the destinations row IS the
   floating-overlay row -- every entry opens an overlay via onOverlay(). AI Tools is a
   floating overlay too (AiToolsModal), so it belongs here, not in the Generate/Loom
   launcher cluster (owner call, 2026-08-18). It is armed-gated: NO entry, no hint while
   the mirror is off (§2 "no entry, no hint"); when armed it materialises LEADING the row
   in emerald with a one-time NEW flag. The nav is always mounted while the arming toggle
   lives in the Control Panel overlay, so we can't read that state directly -- we fetch
   /api/mirror/status on mount and refetch on the `mg-mirror-changed` window event the
   MirrorTile fires on every arm/disarm/connect. */
const AITOOLS_SEEN = "mg_bridge_aitools_seen";

export default function NavSpine({ boot, onOverlay }) {
  const [armed, setArmed] = useState(false);
  const [isNew, setIsNew] = useState(() => {
    try { return !window.localStorage.getItem(AITOOLS_SEEN); } catch { return true; }
  });
  useEffect(() => {
    let alive = true;
    const read = () => {
      fetch("/api/mirror/status")
        .then((r) => r.json())
        .then((d) => { if (alive) setArmed(!!(d && d.enabled)); })
        .catch(() => {});
    };
    read();
    window.addEventListener("mg-mirror-changed", read);
    return () => { alive = false; window.removeEventListener("mg-mirror-changed", read); };
  }, []);
  const openAiTools = () => {
    setIsNew(false);
    try { window.localStorage.setItem(AITOOLS_SEEN, "1"); } catch { /* private mode -- flag just re-shows */ }
    if (onOverlay) onOverlay("aitools");
  };
  /* Log Out (2026-08-02): the real JSON POST /api/login's sibling, per
     docs/DECISIONS.md's 2026-07-31 feasibility map ("A SPA needs real
     POST /api/login -> JSON and a JSON logout"). Mirrors classic /logout's
     own cache-purge-then-navigate shape (see moonglade_gallery.py's
     _LOGOUT_HTML) via fetch instead of a full-page form POST -- same end
     state, no jarring reload for a session that's still valid up to the
     click. Lands on /login, which now renders LoginPage.jsx for the common
     (non-bootstrap) case. Fire-and-forget on the network: an already-dead
     cookie or a dropped request must still clear local state and navigate,
     never strand the user on a page that thinks it's signed in. */
  const logout = () => {
    fetch("/api/logout", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ csrf: boot.csrf || "" }),
    }).catch(() => {}).then(() => {
      const go = () => { window.location.href = "/login"; };
      if ("caches" in window) {
        caches.keys().then((ks) => Promise.all(ks.map((k) => caches.delete(k)))).catch(() => {}).then(go);
      } else {
        go();
      }
    });
  };

  return (
    <nav className="mgx-navspine" aria-label="Destinations">
      {armed ? (
        <button type="button" className="mgx-nav ai" onClick={openAiTools}>
          <span className="mgx-nav-mark ai" aria-hidden="true">✦</span>
          <span>AI Tools</span>
          {isNew ? <span className="mgx-nav-new">New</span> : null}
          <span className="mgx-nav-underline ai" aria-hidden="true" />
          <span className="mgx-nav-tip" role="tooltip">PixAI tools — browse the 28, run in the drawer</span>
        </button>
      ) : null}
      {NAV.map((it) => {
        if (it.localOnly && !boot.is_true_local) return null;
        if (it.logout && !boot.user) return null;
        const tip = it.tip + (it.soon ? " — overlay ports next" : "");
        // A soon:true click used to call onOverlay() anyway -- if App.jsx's overlay switch
        // has no case for the flagged key, that sets dead state and produces silent nothing.
        // Real, visible feedback instead (same window.Toast every other real toast in this
        // app already uses), before ever touching onOverlay. (As of 2026-08-08 every NAV
        // entry above has shipped -- Publish and Train included, both have real App.jsx
        // cases now -- so no item currently sets soon:true; this branch stays wired for
        // whichever overlay lands next without one.)
        const go = () => {
          if (it.soon) {
            if (window.Toast) window.Toast.show({ kind: "ok", title: it.label, msg: it.label + " — coming soon." });
            return;
          }
          if (it.href) window.location.href = it.href;
          else if (it.logout) logout();
          else if (it.overlay && onOverlay) onOverlay(it.overlay);
        };
        return (
          <button key={it.label} type="button"
            className={"mgx-nav" + (it.soon ? " soon" : "")}
            onClick={go}>
            {it.gear ? <span className="mgx-nav-mark"><Gear /></span> : null}
            <span>{it.label}</span>
            <span className="mgx-nav-underline" aria-hidden="true" />
            <span className="mgx-nav-tip" role="tooltip">{tip}</span>
          </button>
        );
      })}
    </nav>
  );
}
