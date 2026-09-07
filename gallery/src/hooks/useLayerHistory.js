import { useEffect, useRef } from "react";

/* THE BACK GESTURE CLOSES ONE LAYER (2026-09-06).

   THE DEFECT, app-wide on the phone. ◈ Similar was the ONE surface on this shell that
   guarded the Back gesture: AppMobile.jsx pushed a single same-address history entry when
   it opened and consumed it again when the ✕ closed it, standing in for the desktop's
   Escape (which a phone does not have). Every OTHER layer the shell pushes over the
   library -- the full-screen viewer, the picture screen, all six Menu destinations, the
   Control tab's Branding drill-in, the composer's Advanced screen, Collection Health's
   Duplicates drill-in, the Folio, the contact sheet, the contest entry screen -- consumed
   zero history depth. So the hardware/browser Back gesture, the phone's own "go up one",
   walked straight past all of them and out of Moonglade: you were reading a picture, you
   swiped back, and you were on whatever you had been looking at before the app.

   THE RULE, in one sentence: a layer that COVERS the shell owns one same-address history
   entry for as long as it is up, and a Back press closes exactly the topmost one.

   WHAT IS A LAYER, AND WHAT IS NOT. The two shared chrome primitives already answer this
   themselves, in their own files, and the line is drawn where they draw it:
     - MobileScreen.jsx: "there is no scrim and no onClick-outside-to-close; `onClose`
       fires from the chevron alone". A pushed screen, and the full-screen overlays that
       behave like one (the viewer, the picture screen, the Folio, the contact sheet, the
       contest entry screen, the ◈ answer), replaces what you were looking at and offers
       exactly ONE way back. That is the surface a Back gesture is for, and it is why
       Similar needed this in the first place -- it had no second dismiss either.
     - MobileSheet.jsx: a dimmed scrim over a slab, and "the scrim travels with the slab or
       it stops dimming and stops catching the tap-outside". A sheet is a transient chooser
       with the thing behind it still visible, one tap away, through an affordance that is
       already there. Sheets are therefore NOT registered here -- see AppMobile.jsx's own
       header comment for the full account of that call.

   HOW IT WORKS. One module-level ledger, not React state, for two reasons: a popstate can
   arrive between renders and has to be answered from whatever is open at that instant, and
   the layers are spread across four components (AppMobile, ControlMobile, CreateMobile,
   HealthMobile) that share no state at all.
     - `stack` is every open layer, in the order they opened, deepest last.
     - `depth` is how many entries WE have pushed. It is reconciled against `stack.length`,
       never incremented per call site.
     - ONE RECONCILE PER COMMIT, on a microtask. This is the part that has to be right: a
       single tap regularly closes one layer and opens another in the same commit -- the ◈
       verb closes the viewer and opens Similar; a Menu row yanks the sheet and pushes a
       screen; the record's ☁ closes itself and pushes Publish. Those land as two separate
       effects inside one React commit, and reconciling inside each of them would fire a
       history.go(-1) and a pushState against each other over a depth that never actually
       changed (and history.go is asynchronous, so the two would then race). A microtask
       runs after React has flushed every effect in the commit, so the manager sees the
       settled shape once and asks the browser for nothing when a swap leaves it level.
     - The popstate handler drops the ledger BEFORE it closes anything, so the reconcile
       that the close then schedules finds the two already level and stays quiet.
     - `unwinding` counts the entries we asked the browser to drop ourselves (a layer
       closed by its own affordance), so their popstate is recognised as ours and never
       mistaken for the owner's Back. */

const stack = [];        // [{ close, closing }] -- every open layer, deepest last
let depth = 0;           // same-address entries this manager has pushed
let unwinding = 0;       // history.go() steps of our own whose popstate is not the owner's
let bound = false;
let scheduled = false;

function onPop() {
  if (unwinding > 0) { unwinding -= 1; return; }
  if (!depth) return;                       // nothing of ours was consumed: not our Back
  depth -= 1;
  /* The topmost layer that has not already been told to close. The skip matters for two
     Backs inside one frame: the first layer's own state has not committed yet, so without
     it the second press would close the same layer twice and leave the one beneath it
     stranded. */
  for (let i = stack.length - 1; i >= 0; i -= 1) {
    if (!stack[i].closing) { stack[i].closing = true; stack[i].close(); break; }
  }
  /* AND RECONCILE, because being TOLD to close is not being closed.

     Five of the ten layers animate their exit -- the Menu screens, Branding, the composer's
     Advanced screen, Duplicates and the Folio all keep their `open` flag true for another
     200-220ms after close() runs, which is exactly what MobileScreen/MobileSheet need to
     play the layer out. The ledger dropped its entry the instant the FIRST Back was seen,
     so for that whole window `depth` said nothing was open while a full-screen layer was
     still covering the display -- and a second real Back inside it hit `if (!depth) return`
     and was let straight through to the browser. Back left the app with the screen still on
     screen: the exact defect this whole manager exists to fix.

     The entry is therefore owed for as long as the layer is in `stack`, and `stack` only
     shrinks when the layer's own open flag really flips. Scheduling here hands the entry
     back immediately, so a second Back inside the exit window is answered by us (a no-op --
     the layer is already on its way out) rather than by the browser, and the net
     consumption still lands exactly when the layer unmounts. */
  schedule();
}

function sync() {
  const want = stack.length;
  while (depth < want) {
    depth += 1;
    // Same address, always: nothing on this shell is URL-synced, so an entry here is a
    // depth marker and never a place. See AppMobile.jsx's header comment.
    window.history.pushState({ mgLayer: depth }, "");
  }
  if (depth > want) {
    const drop = depth - want;
    depth = want;
    unwinding += drop;
    window.history.go(-drop);
  }
}

function schedule() {
  if (scheduled) return;
  scheduled = true;
  Promise.resolve().then(() => { scheduled = false; sync(); });
}

/** Register one layer. `open` mounts its history entry, `close` is what a Back press calls.
    The listener is bound once and never removed: `unwinding` can still be owed a popstate
    after the last layer closes (history.go is asynchronous), and a handler that unbound
    itself in that window would let the next real Back be swallowed. */
export default function useLayerHistory(open, close) {
  const closeRef = useRef(close);
  useEffect(() => { closeRef.current = close; });
  useEffect(() => {
    if (!open) return undefined;
    if (!bound) { bound = true; window.addEventListener("popstate", onPop); }
    const entry = { close: () => closeRef.current(), closing: false };
    stack.push(entry);
    schedule();
    return () => {
      const i = stack.indexOf(entry);
      if (i >= 0) stack.splice(i, 1);
      schedule();
    };
  }, [open]);
}
