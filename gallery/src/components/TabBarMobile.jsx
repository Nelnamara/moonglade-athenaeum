import React from "react";

/* The 3-icon bottom tab bar (design spec: Moonglade Mobile.dc.html navStyle/
   navTabs, lines 275-283 & 1080-1086) -- Gallery/Create/Control, real glyphs
   and order from the DC. This IS the navigation skeleton this increment's
   brief asks for: Create/Control render honest placeholders (AppMobile.jsx)
   until their own increments build real content -- this bar itself is fully
   real (a real setTab, a real active state, a real underline dot). */

const TABS = [
  { key: "gallery", icon: "⛰", label: "Gallery" },
  { key: "create", icon: "✦", label: "Create" },
  { key: "control", icon: "⚙", label: "Control" },
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
