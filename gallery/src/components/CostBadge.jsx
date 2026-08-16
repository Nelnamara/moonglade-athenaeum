import React, {
  forwardRef, useEffect, useImperativeHandle, useRef, useState,
} from "react";
import "../styles/cost-badge.css";

/* CostBadge — the React port of static/mg-cost-badge.js's <mg-cost-badge> custom element:
   the one place the suite says "this generation costs N credits" or "a free card covers it",
   so the hand-written copies of that sentence (the Generate cost line, the Edit cost line,
   the mobile create cost, the separator's compact chip) collapse onto one honest renderer
   instead of drifting apart.

   IT NEVER FETCHES. The host owns the /api/price call (and its debounce, its sequence guard,
   its abort-on-stale logic) and pushes the parsed result in through the ref — exactly like
   the element it replaces. The imperative handle keeps EVERY existing costRef call site
   (useGenerate / useEditGenerate / EditTab / FixTab, via setPrice/setChecking/clear) working
   verbatim; the only new seam is the `onCost` prop, which fires the old bubbling `mg-cost`
   event's detail on every push (the separator bar listens to reveal its chip).

   The one non-negotiable rule it enforces, inherited verbatim from loom-core.js's
   formatCostEstimate: a displayed "free" or "0 credits" must ONLY ever mean a genuinely
   settled, zero-cost result — never "not priced yet" and never "the price check failed."
   Five states keep those cases visually distinct:
     idle      not priced yet — nothing to price, or the server said so (`note`). Muted.
     checking  a price request is in flight. Muted. (Transient; hosts may skip it.)
     free      a free card (kaisuuken) covers it -> 0 credits spent. Emerald.
     paid      settled credit cost, card or no card. Neutral, or amber via `warn` — and amber
               for the SHORT case (issue #15): a card matched but the account holds fewer
               tickets than this job needs, so NO card is attached and the FULL price is
               charged, exactly like the site. The badge derives that note itself from the
               response's cards_needed/cards_held (data-short="1"); hosts never hand-write
               it, and their single-slot `warn` keeps its own place beside it. Amber, not red:
               short is a SETTLED paid price, not a could-not-verify.
     error     could NOT verify — fetch failed, server errored, or the response carried
               neither a cost nor a note. RED, worded so a host reading it aloud still warns
               the user that generating may spend. Never silently neutral: the fail-closed
               spend gate this exists for.

   VANILLA CAMPAIGN NOTE (2026-08-08): static/mg-cost-badge.js was deleted at the END of the
   no-vanilla campaign (step 7), together with its last embedder, the video drawer. That drawer's
   markup used to hard-embed a <mg-cost-badge> custom element, which kept mg-cost-badge.js
   registered through steps 4-6; step 7 ported the drawer to the React <VideoDrawer>, which embeds
   this same React <CostBadge> instead, so the custom element had no remaining embedder and both
   files went. (mg-upscale-panel.js also embedded it, but was ported to React UpscalePanel +
   deleted in step 5.) This React component is now what EVERY surface uses; static/ holds no
   vanilla JS at all.

   Props (all optional):
     hint       — the idle label. Hosts with a mode-dependent hint just re-set it.
     warn       — a caution clause shown ONLY on the `paid` state, which also turns the badge
                  amber. Empty/absent = no warning.
     compact    — render as the credits chip (value · divider · label, expiry, gold "!" dot,
                  hover billing tooltip) instead of the full-width bar. Purely presentational.
     cardLabel  — fallback name for the covering card when the server didn't send one.
     onCost     — called on every state push with the old mg-cost detail
                  {state, settled, cost, free, cards, card_name, card_expires, text, raw}
                  plus card_short (true only on the paid-because-short case above).
     id / className / style — passed to the root (className is appended after "cost-badge").
   Imperative handle (a host sets data; the badge never goes and gets it):
     setPrice(resp) — feed the PARSED /api/price response. Pass null/undefined when the fetch
                      itself failed — that is the could-not-verify state, NOT the same as clear().
     clear(hint)    — back to not-yet-priced. Optional one-shot label overriding `hint`.
     setChecking()  — "Checking cost…" while the host's request is in flight.
     state / settled / free / cost / text / price — read-only accessors matching the element's. */

function fmt(n) { return Number(n).toLocaleString(); }

const DEFAULT_HINT = "No cost yet — nothing to price.";
// Deliberately says "may spend credits" rather than going quiet: this is the state where the
// app does NOT know, and the Loom's confirmSpend words its fail-closed dialog the same way.
const ERR_TEXT = "Couldn't verify the cost — generating may spend credits.";
const ERR_TITLE = "Couldn't verify the cost or free-card coverage. Generating may spend credits.";

// A free card's expiresAt is ISO8601, or null for a card that never expires — null/unparseable
// renders nothing rather than "Invalid Date". Epoch numbers tolerated for pre-parsing callers.
function expiryNote(v) {
  if (v == null || v === "") return null;
  let t;
  if (typeof v === "number") t = v < 1e12 ? v * 1000 : v;   // seconds vs milliseconds
  else t = Date.parse(String(v));
  if (!isFinite(t)) return null;
  const days = Math.ceil((t - Date.now()) / 86400000);
  const when = days < 0 ? "expired"
    : days === 0 ? "expires today"
      : days === 1 ? "expires tomorrow"
        : "expires in " + days + " days";
  // `days` rides along so the chip can decide when the gold "!" warning dot earns its spot.
  return { text: when, title: new Date(t).toLocaleString(), days };
}

// A finite non-negative integer from the /api/price card fields, or null when absent/junk.
function cardCount(v) {
  if (v == null || v === "") return null;
  const n = Number(v);
  return (isFinite(n) && n >= 0) ? Math.floor(n) : null;
}

// The SHORT case (issue #15): the server matched a card but the account holds fewer tickets
// than this job costs -> nothing is attached, the FULL price is charged. The server's own
// `card_short` flag is authoritative; the held<needed re-check is a belt against a response
// that carries the counts but predates the flag. Either way this must win over `free`.
function isShort(d) {
  if (!d) return false;
  if (d.card_short) return true;
  const need = cardCount(d.cards_needed), held = cardCount(d.cards_held);
  return need != null && held != null && held < need;
}

// The setPrice branch logic, verbatim: resp === null/undefined means THE CHECK ITSELF FAILED
// (fetch threw, JSON unparseable) — the could-not-verify state on purpose. A host that wants
// "not priced yet" calls clear() instead. Conflating the two is the bug this exists to prevent.
function classify(resp) {
  const d = (resp && typeof resp === "object") ? resp : null;
  if (!d) return { state: "error", note: "", msg: "", raw: null };
  if (d.error) return { state: "error", note: "", msg: String(d.error), raw: d };
  // `free` can NEVER be produced for a short card: even a server that said free:true with
  // held < needed is rendered as paid (falls through to the cost branch, or to error when
  // there is no cost to show). FREE while the submit charges is the exact bug of issue #15.
  if (d.free && !isShort(d)) return { state: "free", note: "", msg: "", raw: d };
  // Checked BEFORE `note` so a response carrying both can never hide a real cost behind a hint.
  if (d.cost != null && isFinite(Number(d.cost))) return { state: "paid", note: "", msg: "", raw: d };
  if (d.note) return { state: "idle", note: String(d.note), msg: "", raw: d };
  // free:false, cost:null, no note, no error — nothing was priced. Honest answer is "we don't
  // know", NOT a neutral silence and certainly not "0 credits".
  return { state: "error", note: "", msg: "", raw: d };
}

// Pure: (view, props) -> everything the render and the mg-cost detail both need. Kept out of
// the component so the onCost effect can rebuild the exact text the DOM shows.
function build(view, props) {
  const { state, note, msg, raw } = view;
  const d = raw || {};
  const warn = (props.warn || "").trim();
  const compact = !!props.compact;
  let main = "", sub = null, title = "", val = "", lab = "", tip = "", dot = false, short = false;
  // Ticket accounting from the response: `cards`/`cards_held` = tickets HELD, `cards_needed` =
  // tickets this job COSTS (absent = 1, the one-job-one-ticket case every image is).
  const heldN = cardCount(d.cards_held != null ? d.cards_held : d.cards);
  const needN = cardCount(d.cards_needed);
  if (state === "free") {
    const card = d.card_name || (props.cardLabel || "").trim() || "a free card";
    const leftN = (heldN != null) ? fmt(heldN) + " left" : "";
    // Multi-ticket job (a >5s video): say how many of the held tickets it consumes. A 1-ticket
    // job keeps the original "(N left)" so every image badge reads exactly as before.
    const usesN = (needN != null && needN > 1)
      ? "uses " + fmt(needN) + " of " + (heldN != null ? fmt(heldN) : "your") + " cards" : "";
    const savesN = (d.cost != null && isFinite(Number(d.cost))) ? fmt(d.cost) : "";
    main = "🎫 FREE — " + card + " covers this"
      + (usesN ? " — " + usesN : (leftN ? " (" + leftN + ")" : ""))
      + (savesN ? " · saves ~" + savesN + " credits" : "");
    sub = expiryNote(d.card_expires);
    title = usesN
      ? "A free card is applied automatically at submit — this generation spends 0 credits and "
        + usesN + "."
      : "A free card is applied automatically at submit — this generation spends 0 credits.";
    val = "FREE";
    lab = card + (usesN ? " · " + usesN : (leftN ? " · " + leftN : ""));
    tip = title + (savesN ? " Saves ~" + savesN + " credits." : "");
    if (sub) { tip += " Card " + sub.text + " — " + sub.title + "."; dot = sub.days <= 7; }
  } else if (state === "paid") {
    const n = Number(d.cost);
    // Short (issue #15): a card matched but held < needed. Rendered as PAID at the full
    // price with the amber warn treatment — nothing is attached, so no partial-application
    // wording, ever. The note is derived HERE from the counts (hosts never hand-write it), and
    // the host's single-slot `warn` keeps its prefix beside it. A settled zero can't be short.
    short = (n !== 0) && isShort(d);
    const shortNote = short
      ? "You hold " + (heldN != null ? fmt(heldN) : "?") + " of the "
        + (needN != null ? fmt(needN) : "?") + " cards this needs — not enough, so no card "
        + "is used. Costs the full ~" + fmt(n) + " credits."
      : "";
    // A settled ZERO is real (nothing to spend) but is NOT the free-card state — it must not
    // borrow its wording or its emerald.
    main = (n === 0) ? "0 credits — this spends nothing"
      : (warn ? "⚠ " + warn + " · " : (short ? "⚠ " : "")) + "≈ " + fmt(n) + " credits";
    title = (n === 0) ? "Priced at zero credits. No free card was involved."
      : short ? shortNote
        : "No free card covers this — generating spends credits.";
    // The short sentence takes the note line under the price (block form); the chip has no
    // room for it, so there it rides in the label + billing tooltip instead.
    if (short && !compact) sub = { text: shortNote, title: shortNote, days: null };
    val = (n === 0) ? "0" : (warn || short ? "⚠ " : "") + "≈ " + fmt(n);
    lab = (n === 0) ? "credits — spends nothing" : short ? "credits · card short" : "credits";
    tip = (n !== 0 && warn) ? "⚠ " + warn + ". " + title : title;
  } else if (state === "error") {
    main = "⚠ " + (msg || ERR_TEXT);
    title = ERR_TITLE;
    tip = ERR_TITLE;
  } else if (state === "checking") {
    main = "Checking cost…";
  } else {
    main = note || (props.hint || "").trim() || DEFAULT_HINT;
  }
  const text = main + (sub ? " · " + sub.text : "");
  return { state, warn, compact, short, main, sub, title, val, lab, tip, dot, text, d };
}

function detailOf(m) {
  const d = m.d || {};
  return {
    state: m.state,
    settled: m.state === "free" || m.state === "paid",
    cost: (d.cost != null && isFinite(Number(d.cost))) ? Number(d.cost) : null,
    free: m.state === "free",
    card_short: !!m.short,
    cards: d.cards != null ? d.cards : null,
    card_name: d.card_name != null ? d.card_name : null,
    card_expires: d.card_expires != null ? d.card_expires : null,
    text: m.text,
    raw: m.raw,
  };
}

const IDLE = { state: "idle", note: "", msg: "", raw: null };

const CostBadge = forwardRef(function CostBadge(props, ref) {
  const { hint, warn, compact, cardLabel, onCost, id, className, style } = props;
  const [view, setView] = useState(IDLE);

  // Latest view/props/text for the imperative getters and the onCost effect (which fire
  // outside render and must read current values, never a stale closure).
  const viewRef = useRef(view);
  const propsRef = useRef(props);
  const mRef = useRef(null);
  viewRef.current = view;
  propsRef.current = props;

  useImperativeHandle(ref, () => ({
    setPrice(resp) { setView(classify(resp)); },
    clear(h) { setView({ state: "idle", note: h ? String(h) : "", msg: "", raw: null }); },
    setChecking() { setView((v) => ({ ...v, state: "checking", msg: "" })); },
    get state() { return viewRef.current.state || "idle"; },
    get settled() { return viewRef.current.state === "free" || viewRef.current.state === "paid"; },
    get free() { return viewRef.current.state === "free"; },
    get cost() {
      const c = viewRef.current.raw && viewRef.current.raw.cost;
      return (c != null && isFinite(Number(c))) ? Number(c) : null;
    },
    get text() { return mRef.current ? mRef.current.text : ""; },
    get price() { return viewRef.current.raw; },
    set price(v) { setView(classify(v)); },
  }), []);

  // The old element emitted mg-cost from _emit() on every public push (setPrice/clear/
  // setChecking) but NOT on its initial connectedCallback render — mirror that: skip the
  // first effect run (initial idle), fire onCost on each subsequent view change.
  const mounted = useRef(false);
  useEffect(() => {
    if (!mounted.current) { mounted.current = true; return; }
    if (typeof propsRef.current.onCost === "function") {
      propsRef.current.onCost(detailOf(build(viewRef.current, propsRef.current)));
    }
  }, [view]);

  const m = build(view, { hint, warn, compact, cardLabel });
  mRef.current = m;
  // Short borrows the amber warn treatment (settled paid, flagged) and adds its own attribute so
  // a host or test can tell "card short" from "host warned" without parsing the sentence.
  const dataWarn = (m.state === "paid" && (m.warn || m.short)) ? "1" : undefined;
  const dataShort = (m.state === "paid" && m.short) ? "1" : undefined;
  // The chip's billing tooltip REPLACES the native title (two tooltips on one hover
  // otherwise); the block form keeps the native title exactly as before.
  const nativeTitle = (m.title && !(m.compact && m.tip)) ? m.title : undefined;
  const showChip = m.compact && m.val;

  return (
    <div
      id={id}
      className={"cost-badge" + (m.compact ? " compact" : "") + (className ? " " + className : "")}
      data-state={m.state}
      data-warn={dataWarn}
      data-short={dataShort}
      role="status"
      aria-live="polite"
      title={nativeTitle}
      style={style}
    >
      {showChip ? (
        <>
          <span className="mgc-val">{m.val}</span>
          <span className="mgc-div" />
          <span className="mgc-lab">{m.lab}</span>
          {m.sub ? <span className="mgc-sub">{m.sub.text}</span> : null}
          {m.dot ? <span className="mgc-dot" aria-hidden="true">!</span> : null}
        </>
      ) : m.state === "checking" ? (
        <><span className="mgc-pip" />Checking cost…</>
      ) : (
        <>
          {m.main}
          {m.sub ? <span className="mgc-sub" title={m.sub.title}>{m.sub.text}</span> : null}
        </>
      )}
      {/* aria-hidden: the tip duplicates the chip/text and this is an aria-live region — it
          must not re-announce on every push. */}
      {m.compact && m.tip ? <span className="mgc-tip" aria-hidden="true">{m.tip}</span> : null}
    </div>
  );
});

export default CostBadge;
