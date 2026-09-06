import React from "react";
import Icon from "../icons/Icons.jsx";

/* The 3-icon bottom tab bar (design spec: Moonglade Mobile.dc.html navStyle/
   navTabs, lines 275-283 & 1080-1086) -- Gallery/Create/Control, real glyphs
   and order from the DC. This IS the navigation skeleton this increment's
   brief asks for: Create/Control now render their real components (CreateMobile/
   ControlMobile, via AppMobile.jsx); only Edit's Fixer sub-tab stays a disclosed
   placeholder -- this bar itself is fully
   real (a real setTab, a real active state, a real underline dot).

   Control's mark is the drawn laptop-cog since the 2026-09-05 Glyph Ledger (⚙
   before it) -- the Control Panel's own mark, shared with the command palette's
   "Control Panel" row so both of the Panel's doors wear the same thing. */

const TABS = [
  { key: "gallery", icon: "⛰", label: "Gallery" },
  { key: "create", icon: "✦", label: "Create" },
  { key: "control", icon: <Icon name="panel" />, label: "Control" },
];

export default function TabBarMobile({ tab, setTab }) {
  return (
    <nav className="glm-nav" aria-label="Sections">
      {TABS.map((t) => (
        <button
          key={t.key}
          type="button"
          className={"glm-navitem" + (tab === t.key ? " on" : "")}
          aria-current={tab === t.key ? "page" : undefined}
          onClick={() => setTab(t.key)}
        >
          <span className="glm-navicon" aria-hidden="true">{t.icon}</span>
          <span className="glm-navlabel">{t.label}</span>
          {tab === t.key ? <span className="glm-navdot" aria-hidden="true" /> : null}
        </button>
      ))}
    </nav>
  );
}
