/* The Control Panel's tabs, in order -- ONE list, read by the panel itself
   (ControlPanelOverlay.jsx) and by the key-turn moment's rail, which draws the real tab list
   rather than a stand-in (the handoff's own note: "the build highlights the real tab"). A tab
   added or renamed here reaches both at once.

   `gated`: the tab exists only once an earned achievement unlocks it (useControlPanel's
   brandingUnlocked). The rail draws every ungated tab as a plain row and the gated one as the
   slot that unlocks. */
export const PANEL_TABS = [
  { id: "maint", label: "Maintenance" },
  { id: "brand", label: "✦ Branding", gated: true },
];

export const panelTabLabel = (id) => (PANEL_TABS.find((t) => t.id === id) || { label: id }).label;
