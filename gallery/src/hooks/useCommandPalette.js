import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { groupCommands, pushRecent, readRecent } from "../palette/paletteCore.js";

/* THE KEYBOARD LAYER + the palette's own state (design/command-palette, frames A-H).

   App.jsx builds the command list off its REAL verbs -- every `run` here is the same
   function the mouse UI calls, never a re-implementation (DC frame H, "Behavior locked").
   This hook owns everything else: open/close with the deferred exit, the query, the
   selection, the Recent ledger, the two-stroke G prefix, and the one global key listener.

   THE GLOBAL RULE, from the DC's own header strip: global keys fire ONLY outside text
   fields. That is literal -- Ctrl/Cmd-K included. Once the palette is open its own input
   has focus, so the chord is inert there and Esc is the documented way out (frame A's
   footer, frame G's ladder note). No hidden second binding.

   THE ESCAPE LADDER is innermost-first and joins the app's existing one rather than
   replacing it: this listener runs in the CAPTURE phase and stops propagation when it
   actually closed something, and App.jsx's own overlay-Esc closer carries a matching
   `palette is up` bail -- the same shape it already uses for the Control Panel and the
   shared picker ("a layer on top owns its own Escape ladder"). Both halves, because
   relying on listener registration order alone would be a trap for the next editor. */

const EXIT_MS = 340;      // matches the .closing exit animation in command-palette.css
const G_TIMEOUT_MS = 1800; // DC frame F: the G… chip clears on a 1.8s timeout

const isTyping = (el) =>
  !!(el && el.closest && el.closest("input, textarea, select, [contenteditable=''], [contenteditable='true']"));

export default function useCommandPalette(commands) {
  const [open, setOpen] = useState(false);
  const [closing, setClosing] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [sheetClosing, setSheetClosing] = useState(false);
  const [query, setQueryState] = useState("");
  const [sel, setSel] = useState(0);
  // Every keystroke re-ranks, so the highlight goes back to the top of the new list --
  // frame B's "best match pre-selected". Bundled with the setter so no call site can
  // forget the pair (the same reason useControlPanel bundles setTaskId with setTaskState).
  const setQuery = useCallback((v) => { setQueryState(v); setSel(0); }, []);
  const [recent, setRecent] = useState(readRecent);
  const [pending, setPending] = useState(false);   // the two-stroke G… chip

  const exitTimer = useRef(null);
  const sheetTimer = useRef(null);
  const gTimer = useRef(null);
  useEffect(() => () => {
    clearTimeout(exitTimer.current);
    clearTimeout(sheetTimer.current);
    clearTimeout(gTimer.current);
  }, []);

  /* Recent (DC §8.1) is the last three RUN commands, resolved against the LIVE list every
     render: an id whose command isn't currently available -- a deleted collection, an
     on-this-image action with nothing focused, a claim with nothing left to claim -- simply
     isn't offered, which is the same absent-never-disabled rule the rest of the palette
     follows. Frame A's Recent rows carry their shortcut chip but drop the `sub`, so the
     count/hint only ever appears once, on the row's home group. */
  const rows = useMemo(() => {
    const byId = new Map((commands || []).map((c) => [c.id, c]));
    const recentCmds = recent
      .map((id) => byId.get(id))
      .filter(Boolean)
      .map((c) => ({ ...c, group: "Recent", groupExtra: "", sub: "", right: "", rightKind: "", from: c.id }));
    return groupCommands(recentCmds.concat(commands || []), query);
  }, [commands, recent, query]);

  // Selection is clamped, never stranded: a filter that shortens the list snaps the
  // highlight back onto a real row (frame B: "best match pre-selected").
  useEffect(() => { setSel((s) => (s >= rows.count ? 0 : s)); }, [rows.count]);

  const flat = useMemo(() => rows.groups.flatMap((g) => g.rows), [rows]);

  const close = useCallback(() => {
    setClosing(true);
    clearTimeout(exitTimer.current);
    exitTimer.current = setTimeout(() => { setOpen(false); setClosing(false); }, EXIT_MS);
  }, []);
  const openPalette = useCallback(() => {
    clearTimeout(exitTimer.current);
    setQueryState("");
    setSel(0);
    setClosing(false);
    setOpen(true);
  }, []);
  const closeSheet = useCallback(() => {
    setSheetClosing(true);
    clearTimeout(sheetTimer.current);
    sheetTimer.current = setTimeout(() => { setSheetOpen(false); setSheetClosing(false); }, EXIT_MS);
  }, []);
  const openSheet = useCallback(() => {
    clearTimeout(sheetTimer.current);
    setSheetClosing(false);
    setSheetOpen(true);
  }, []);

  /* Run a command: bank it in Recent, close the palette, THEN fire. Closing first is what
     lets an action move focus (Jump to Search) or open its own layer without racing the
     palette's own input for it. A Recent row banks the command it MIRRORS, not itself. */
  const run = useCallback((cmd) => {
    if (!cmd) return;
    setRecent((cur) => pushRecent(cmd.from || cmd.id, cur));
    close();
    try { cmd.run(); } catch { /* an action's own failure is its own to report */ }
  }, [close]);

  const move = useCallback((delta) => {
    setSel((s) => {
      const n = flat.length;
      if (!n) return 0;
      return (s + delta + n) % n;      // ↑↓ wrap (DC frame A's `sel` note)
    });
  }, [flat.length]);

  const runSelected = useCallback(() => {
    const row = flat[sel];
    if (row) run(row.cmd);
  }, [flat, sel, run]);

  // Live refs for the window listener, which mounts once and must never see a stale list.
  const st = useRef({});
  st.current = { open, sheetOpen, commands, openPalette, close, openSheet, closeSheet, run, pending };

  /* THE ONE GLOBAL LISTENER. Capture phase, so the Escape branch can stop the app's other
     Escape handlers before they fire; everything else is plain bubble-safe work done from
     the same place. */
  useEffect(() => {
    const clearPending = () => {
      clearTimeout(gTimer.current);
      gTimer.current = null;
      setPending(false);
    };
    const onKey = (e) => {
      const s = st.current;

      // Escape first, and it is the ONE branch that fires while a field has focus (the
      // palette's own input is a field). Innermost layer first: sheet, then palette.
      if (e.key === "Escape") {
        if (s.pending) { clearPending(); e.stopPropagation(); return; }
        if (s.sheetOpen) { s.closeSheet(); e.stopPropagation(); return; }
        if (s.open) { s.close(); e.stopPropagation(); return; }
        return;                                    // nothing of ours is up: the app's ladder owns it
      }
      if (e.defaultPrevented) return;
      if (isTyping(e.target)) return;              // global keys are dead while typing (DC frame H)

      // Ctrl/Cmd-K. Alt-modified is somebody else's chord.
      if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === "k" || e.key === "K")) {
        if (s.open) return;                        // already up; its input owns the keyboard
        e.preventDefault();
        clearPending();
        s.openPalette();
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (s.open) return;                          // the panel's own handler drives while it is up

      const k = e.key;
      // Second stroke of a G_ combo. Any other key simply cancels the prefix (DC frame F).
      if (s.pending) {
        clearPending();
        const combo = "g " + k.toLowerCase();
        const cmd = (s.commands || []).find((c) => c.hotkey === combo);
        if (cmd) { e.preventDefault(); s.run(cmd); }
        return;
      }
      if (k === "g" || k === "G") {
        e.preventDefault();
        setPending(true);
        clearTimeout(gTimer.current);
        gTimer.current = setTimeout(() => { gTimer.current = null; setPending(false); }, G_TIMEOUT_MS);
        return;
      }
      if (k === "?") { e.preventDefault(); s.openSheet(); return; }
      // A single-key command that isn't currently offered is ABSENT, not dead: R with no
      // focused image finds nothing here because App never built the row (DC frame H).
      const cmd = (s.commands || []).find((c) => c.hotkey === k.toLowerCase());
      if (cmd) { e.preventDefault(); s.run(cmd); }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);

  return {
    open, closing, active: open || closing,
    sheetOpen, sheetClosing, sheetActive: sheetOpen || sheetClosing,
    pending,
    query, setQuery,
    sel, setSel, move,
    groups: rows.groups, count: rows.count,
    openPalette, close, openSheet, closeSheet,
    run, runSelected,
  };
}
