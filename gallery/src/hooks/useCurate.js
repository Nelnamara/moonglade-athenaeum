import { useCallback, useEffect, useRef, useState } from "react";
import { curate, curateRestore } from "../api.js";
import { invalidate } from "./swrCache.js";
import { announceCurated } from "../curation/curationBus.js";
import { applyAfter, curateSummary, undoSecondsLeft, UNDO_MS } from "../curation/curationCore.js";
import { DETAIL_PREFIX } from "../apiRoutes.js";

/* BULK CURATION with an honest count and a 10 second Undo (Session N, N4/N5).

   The server does the counting: POST /api/curate answers how many pictures REALLY changed
   and each one's previous state, so "Rated 3 pictures" never counts a picture that already had
   that rating, and Undo (POST /api/curate/restore) puts every picture back to ITS OWN old
   values rather than resetting them to one. Nothing here reaches PixAI -- ratings, tags,
   marks and notes are the local catalog's.

   `setItems` is useLibrary's: the loaded page is patched in place from the server's answer,
   never re-fetched, so curating leaves the grid standing exactly where it was (the library
   stands still, DECISIONS 2026-09-05). A filtered view whose membership just changed catches
   up the next time the owner opens or refreshes it.

   The toast is one at a time: a new change replaces the previous toast, and with it that
   change's Undo. That is the design page's own behaviour.

   say(text, prev, tone, undoFn) -- `undoFn` (Session U) is an Undo that is not a catalog
   restore: the phone's Continuous list clearing a selection on a filter change hands back
   the selection it cleared. Local state only; nothing is sent. */
export default function useCurate({ csrf, setItems }) {
  const [toast, setToast] = useState(null);   // {text, tone, prev, until, secs}
  const timer = useRef(0);
  const csrfRef = useRef(csrf);
  csrfRef.current = csrf;

  const stop = () => { clearInterval(timer.current); timer.current = 0; };
  useEffect(() => stop, []);

  const show = useCallback((text, prev, tone, undoFn) => {
    stop();
    const until = Date.now() + UNDO_MS;
    setToast({ text, tone: tone || "", prev: prev || null, undoFn: typeof undoFn === "function" ? undoFn : null,
      until, secs: undoSecondsLeft(until, Date.now()) });
    timer.current = setInterval(() => {
      setToast((t) => {
        if (!t) { stop(); return t; }
        const secs = undoSecondsLeft(t.until, Date.now());
        if (secs <= 0) { stop(); return null; }
        return secs === t.secs ? t : { ...t, secs };
      });
    }, 250);
  }, []);
  const dismiss = useCallback(() => { stop(); setToast(null); }, []);

  const land = useCallback((after) => {
    if (!after || !Object.keys(after).length) return;
    setItems((old) => applyAfter(old, after));
    announceCurated(after);
    // what the overlays paint from last-known data: the record, My Art's totals, the roster
    invalidate([DETAIL_PREFIX, "/api/your-art", "/api/myart/items", "/api/achievements", "/api/health"]);
  }, [setItems]);

  /* Apply `op` to `ids`. `say` chooses the toast: true = the summary sentence with an Undo,
     false = quiet (a single rating from the keyboard). A refusal is always said, in peach.
     Resolves to the server's answer ({changed, ...}) or {error}. */
  const apply = useCallback(async (ids, op, say) => {
    const res = await curate(csrfRef.current, ids, op);
    if (res.error) { show(res.error, null, "peach"); return res; }
    land(res.after);
    if (say) show(curateSummary(op, res.changed, res.refused), res.changed ? res.prev : null);
    return res;
  }, [land, show]);

  const undo = useCallback(async () => {
    const t = toast;
    if (!t) return;
    if (t.undoFn) { dismiss(); t.undoFn(); return; }
    if (!t.prev) return;
    dismiss();
    const res = await curateRestore(csrfRef.current, t.prev);
    if (res.error) { show(res.error, null, "peach"); return; }
    land(res.after);
  }, [toast, dismiss, land, show]);

  return { toast, apply, undo, dismiss, say: show };
}
