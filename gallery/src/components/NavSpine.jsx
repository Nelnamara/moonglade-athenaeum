import React from "react";
import "../styles/shell.css";

/* The glyph-spine nav — the DC separator-bar pills (Frontend Gallery.dc.html
   NAV_ORDER + drift §16): Panel and Log Out are PAGE navigations; the other six
   destinations open floating overlays. The overlays themselves are a parallel
   workstream (overlays/OverlayShell + six surfaces) — this component only
   reports the click via onOverlay(key). Items whose overlay hasn't shipped are
   `soon`-dimmed but STILL wired, so lighting one up is a one-flag change here
   plus mounting the surface at App.jsx's overlay mount point. */

const NAV = [
  { label: "My Art", tip: "How your published art is doing", overlay: "myart", soon: true },
  { label: "Publish", tip: "Publish to PixAI", overlay: "publish", soon: true },
  { label: "Train", tip: "Train a LoRA on PixAI", overlay: "train", soon: true },
  { label: "Import", tip: "Bring local files into the catalog — nothing goes to PixAI",
    overlay: "import", soon: true, localOnly: true },
  { label: "Contests", tip: "Live PixAI contests", overlay: "contests", soon: true },
  // Health has a live fallback destination (/health) until HealthOverlay lands,
  // wired in App.openOverlay — so it is not `soon`.
  { label: "Health", tip: "Collection health dashboard", overlay: "health" },
  { label: "Panel", tip: "Control Panel — maintenance jobs, scheduler, branding",
    href: "/panel", gear: true },
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

export default function NavSpine({ boot, onOverlay }) {
  /* Log Out is a POST (session mutation), same as the retired rail's form —
     built on click so the pill keeps the spine's button styling. */
  const logout = () => {
    const f = document.createElement("form");
    f.method = "post";
    f.action = "/logout";
    const i = document.createElement("input");
    i.type = "hidden";
    i.name = "csrf";
    i.value = boot.csrf || "";
    f.appendChild(i);
    document.body.appendChild(f);
    f.submit();
  };

  return (
    <nav className="mgx-navspine" aria-label="Destinations">
      {NAV.map((it) => {
        if (it.localOnly && !boot.is_true_local) return null;
        if (it.logout && !boot.user) return null;
        const tip = it.tip + (it.soon ? " — overlay ports next" : "");
        const go = () => {
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
