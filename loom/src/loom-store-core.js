/* =========================================================================
   loom-store-core.js — the per-key board SAVE QUEUE (Session P, BUILD-w5-p §3.5, review F5).

   Every board write goes through one queue per key: one write in flight at a time, each
   carrying the revision the previous write returned, collapsing to the newest text. That
   is what lets the server's compare-and-swap (POST /api/loom/set with base_rev) catch a
   REAL second tab without a tab ever conflicting with itself: the 600 ms autosave, the
   render lock's flush and a landing that overlap in one tab are serialised here, so each
   sends the rev the one before it produced.

   No React, no DOM, no fetch: the writer is injected --
     write(key, json, baseRev) -> Promise<{ok:true, rev} | {conflict:true, value, rev}>
   and throws on any other failure. A conflict is handed back to the caller (which merges
   and saves the merge with the remote rev); every write queued behind a conflicted one is
   answered with the same conflict and NOT sent, because it was built on the same stale view.
   ========================================================================================= */

export const makeSaveQueue = (write) => {
  const keys = new Map();
  const slot = (k) => {
    if (!keys.has(k)) keys.set(k, { rev: undefined, busy: null, next: null });
    return keys.get(k);
  };
  const settle = (waiters, res) => waiters.forEach((w) => w(res));

  const pump = (k) => {
    const s = slot(k);
    if (s.busy || !s.next) return;
    const job = s.next;
    s.next = null;
    s.busy = (async () => {
      let res;
      try {
        const base = job.baseRev !== undefined ? job.baseRev : s.rev;
        res = await write(k, job.json, base);
        if (!res || (!res.ok && !res.conflict)) res = { failed: true, error: "no answer" };
      } catch (e) {
        res = { failed: true, error: e };
      }
      if (res.ok && res.rev != null) s.rev = res.rev;
      settle(job.waiters, res);
      s.busy = null;
      if (res.conflict && s.next) {
        // Built on the same stale board: answer it with the conflict, never send it.
        const stale = s.next;
        s.next = null;
        settle(stale.waiters, res);
      }
      pump(k);
    })();
  };

  return {
    /** The rev a read returned (or a sentinel for a missing key). */
    setRev(k, rev) { slot(k).rev = rev; },
    getRev(k) { return slot(k).rev; },
    /** Queue `json` for key `k`. Resolves with the write's answer (or the answer of a newer
     *  write this one was collapsed into). opts.baseRev overrides the tracked rev, for the
     *  write of a merge made against the remote board. */
    save(k, json, opts) {
      const s = slot(k);
      const baseRev = opts && Object.prototype.hasOwnProperty.call(opts, "baseRev") ? opts.baseRev : undefined;
      return new Promise((resolve) => {
        if (s.next) {
          s.next.json = json;
          if (baseRev !== undefined) s.next.baseRev = baseRev;
          s.next.waiters.push(resolve);
        } else {
          s.next = { json, baseRev, waiters: [resolve] };
        }
        pump(k);
      });
    },
    /** Resolves once nothing is in flight or queued for `k`. */
    async idle(k) {
      const s = slot(k);
      while (s.busy || s.next) { await s.busy; }
    },
    /** Forget a key (a deleted board). */
    forget(k) { keys.delete(k); },
  };
};
