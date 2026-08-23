import { useCallback, useEffect, useRef, useState } from "react";
import {
  PRICE_DEBOUNCE_MS, PRICE_FETCH_TIMEOUT_MS, PRICE_KEY_SKIP,
  canSubmit as verdictAllows, fired, initialVerdict, priceKey, scheduled,
  settledFor, shouldShortCircuit,
} from "./priceProbeCore.js";

/* usePriceProbe -- the ONE price probe behind every cost line. The React half of
   gen/priceProbeCore.js: it owns the 250ms debounce, the POST /api/price, the sequence guard,
   the abort timeout, and the whole host half of <CostBadge>'s contract (the badge never
   fetches; a host pushes the parsed answer in through setPrice/setChecking/clear, and that
   imperative handle is untouched public API).

   THIS IS THE ONLY FILE UNDER gallery/src THAT MAY FETCH /api/price -- pinned by
   loom/test/price-probe-structure.test.js. Six hosts used to hand-roll this loop
   (gen/useGenerate.js, gen/useEditGenerate.js, components/EditTab.jsx, components/FixTab.jsx,
   components/UpscalePanel.jsx, components/VideoDrawer.jsx) and only ONE of them -- the video
   drawer -- carried the payload-identity spend gate written after issue #15, where a settled
   FREE for a 5s payload let Go submit a 15s one. Five paid surfaces were running without it.
   Deepening the loop into one module is what makes the gate universal instead of per-host.

   INTERFACE (deliberately tiny):
     usePriceProbe({ build, costRef, enabled = true, skipKeys = PRICE_KEY_SKIP })
       -> { refresh(opts?), verdict, canSubmit, response }

   `build()` is the host's payload builder, the SAME one its submit uses (the invariant every
   cost line already keeps: a quote can never describe a different job than the spend). It
   returns { payload, idle }:
     idle absent/null  there is something to price;
     idle === true     nothing to price -- clear the badge to its own `hint`;
     idle === "..."    nothing to price -- clear it to this one-shot hint instead.
   An idle build is a VERDICT, not a gap: the badge is cleared AND the verdict settles on that
   payload's key, so the host's submit control stays live and its own pre-submit refusal message
   ("Pick a source image first") stays reachable. Every host refuses those before any spend.

   `refresh({force})` schedules a re-price; `force` bypasses the short-circuit for the two cases
   where the payload is byte-identical but the verdict is stale anyway -- right after a submit
   debited the tickets, and right after a badge remounted idle.

   `verdict` is React state so hosts re-render on every transition (the video drawer used to
   call its own rerender() by hand beside each verdict write). `canSubmit` is that verdict
   measured against the payload build() would produce NOW -- hosts AND it into their existing
   gate, on the disabled attribute AND inside the click handler, because a keyboard Enter can
   fire against a stale render. `response` is the last parsed /api/price answer (or null), for
   the one host that must quote a number in its own confirm dialog (FixTab). */
export default function usePriceProbe({ build, costRef, enabled = true, skipKeys = PRICE_KEY_SKIP }) {
  const [verdict, setVerdict] = useState(initialVerdict);
  const [response, setResponse] = useState(null);

  // The live verdict, readable synchronously: refresh() must short-circuit against the value it
  // just wrote, and React's batched state is a render behind. Same discipline VideoDrawer's
  // st.current carried, for the same spend-critical reason.
  const live = useRef(verdict);
  // build/skipKeys are re-created by the host on every render; the timer callback that fires
  // 250ms later must use the LATEST pair, never the closure it was scheduled with.
  const buildRef = useRef(build);
  const skipRef = useRef(skipKeys);
  const enabledRef = useRef(enabled);
  buildRef.current = build;
  skipRef.current = skipKeys;
  enabledRef.current = enabled;

  const seq = useRef(0);          // stale-answer guard (every host shipped its own copy)
  const timer = useRef(0);        // the debounce
  const ctrl = useRef(null);      // the in-flight AbortController, for teardown

  const put = useCallback((v) => { live.current = v; setVerdict(v); }, []);

  // Cancel everything outstanding: the armed debounce, the answer already in flight (the seq
  // bump makes it a no-op even where abort is unavailable), and the request itself. This is the
  // #27 fix generalised -- leaving a tab used to leave the armed timer, so one stray /api/price
  // fired ~250ms after the tab was gone.
  const stop = useCallback(() => {
    clearTimeout(timer.current);
    timer.current = 0;
    seq.current++;
    if (ctrl.current) {
      try { ctrl.current.abort(); } catch { /* already settled */ }
      ctrl.current = null;
    }
  }, []);

  /* The fire step. Every exit settles the verdict for the payload it judged. */
  const fire = useCallback(() => {
    // The timer has FIRED: clear pendingTimer before anything can bail, or an early return
    // (no badge mounted) leaves {pendingTimer:true} forever and canSubmit never passes.
    put(fired());
    const badge = costRef.current;
    if (!badge) return;
    const built = buildRef.current() || {};
    const p = built.payload;
    const skip = skipRef.current;
    const key = priceKey(p, skip);
    if (built.idle) {
      // The idle hint rides clear()'s one-shot override (the badge has no setHint -- its idle
      // state shows note||hint, and clear(h) sets that h).
      if (built.idle === true) badge.clear(); else badge.clear(String(built.idle));
      setResponse(null);
      put(settledFor(key));
      return;
    }
    badge.setChecking();
    const mine = ++seq.current;
    // BOUNDED: Go is hard-gated on this fetch settling, and a HUNG request (a transport stall --
    // a LAN tablet dropping Wi-Fi mid-request) fires neither .then nor .catch, so the verdict
    // never settled, the gate stayed shut and the badge sat on a muted "Checking cost…" with no
    // error and no way out short of changing a priced field (review 2026-08-16). Before the
    // identity gate a hung price left Go LIVE (fail-open); the gate made it fail-silent-closed.
    // An abort rejects into the .catch below, which paints the red "couldn't verify — may spend"
    // and settles, so the machine reaches its documented error verdict and Go returns to its
    // pre-gate, fail-closed-but-live behaviour.
    const c = (typeof AbortController !== "undefined") ? new AbortController() : null;
    ctrl.current = c;
    const abortTimer = c ? setTimeout(() => c.abort(), PRICE_FETCH_TIMEOUT_MS) : 0;
    // The identity is recorded ONLY under the seq guard, off the SAME payload that was priced.
    // A failed check settles too: the badge's red could-not-verify IS this payload's verdict,
    // whereas a verdict for a DIFFERENT payload is exactly what canSubmit refuses.
    fetch("/api/price", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p), signal: c ? c.signal : undefined,
    })
      .then((r) => r.json())
      .then((d) => {
        clearTimeout(abortTimer);
        if (mine !== seq.current || !costRef.current) return;
        ctrl.current = null;
        costRef.current.setPrice(d);
        setResponse(d);
        put(settledFor(key));
      })
      .catch(() => {
        clearTimeout(abortTimer);
        if (mine !== seq.current || !costRef.current) return;
        ctrl.current = null;
        costRef.current.setPrice(null);
        setResponse(null);
        put(settledFor(key));
      });
  }, [costRef, put]);

  /* Schedule a re-price. Verbatim in behaviour from the video drawer's debCost(). */
  const refresh = useCallback((opts) => {
    if (!enabledRef.current) return;
    const force = !!(opts && opts.force);
    const built = buildRef.current() || {};
    if (shouldShortCircuit(live.current, built.payload, force, skipRef.current)) return;
    // Blank the number FIRST, synchronously: an old quote next to new settings is the one thing
    // worse than no quote. Before this, setChecking only ran 250ms later inside the fire step,
    // so a settled FREE stayed on the badge -- and Go stayed live -- for the debounce plus one
    // RTT after the user changed a priced field.
    const badge = costRef.current;
    if (badge && badge.setChecking) badge.setChecking();
    put(scheduled());
    seq.current++;   // any answer already in flight was priced off a payload that stopped being true
    clearTimeout(timer.current);
    timer.current = setTimeout(fire, PRICE_DEBOUNCE_MS);
  }, [costRef, fire, put]);

  /* enabled: a host that has left the screen (a hidden sub-tab, a closed panel) must not have a
     timer armed or a request out. Coming BACK forces a re-price rather than trusting the settled
     verdict -- the badge unmounted with the tab and comes back idle, so the verdict is stale on
     screen whatever it says. Runs on mount too: enabled's first value is a transition into it,
     and that is what primes each cost line on entry. */
  useEffect(() => {
    if (!enabled) { stop(); return; }
    refresh({ force: true });
  }, [enabled, refresh, stop]);

  useEffect(() => stop, [stop]);

  const built = build ? (build() || {}) : {};
  return {
    refresh,
    verdict,
    canSubmit: verdictAllows(verdict, built.payload, skipKeys),
    response,
  };
}
