import React, { useEffect, useState } from "react";
import "../styles/account-detail.css";
import { apiGet } from "../api.js";

/* PixAI account detail — cards · coupons · credit ledger. The web UI for the
   card-coupon-ledger branch's backend, built to Control Panel.dc.html's account-detail
   design (drift-report §37, handoff-2026-08-07b). Launched from the Control Panel's
   "PixAI account" tile; clones the Trash/Users sub-overlay chrome (mgcp-sub-scrim/host/
   slab) exactly, per the design's "same Trash/Users pattern" call.

   Everything here is READ-ONLY — three GET routes, no mutation, no spend, no redeem.
   Real data throughout: GET /api/account (balance strip + on-hand cards),
   /api/account/card-history (?all=1 roster, else usage log), /api/account/coupons
   (on-hand default, ?history=1), /api/account/credit-log (newest-first, backward-paged).

   Real-data note vs the design's mock: the on-hand card chips show each held card's
   real category (Model Card / Video Card) as their dim chip — the mock hardcoded a
   task-type word ("image"); category is what the real /api/account cards_by carries. */

const TABS = [["cards", "Cards"], ["coupons", "Coupons"], ["ledger", "Credit ledger"]];
const KNOWN_REASONS = ["task cost", "daily reward", "event gift", "extra package"];
const nfmt = (n) => (typeof n === "number" ? n.toLocaleString() : n);
const day = (s) => (s ? String(s).slice(0, 10) : "");

export default function AccountSubOverlay({ onClose }) {
  const [acct, setAcct] = useState(null);
  const [tab, setTab] = useState("cards");

  // Cards tab
  const [roster, setRoster] = useState(null);      // {templates:{...}}
  const [log, setLog] = useState([]);
  const [logMore, setLogMore] = useState(false);
  const [logCursor, setLogCursor] = useState(null);
  const [cardsLoaded, setCardsLoaded] = useState(false);

  // Coupons tab
  const [coupons, setCoupons] = useState([]);
  const [coupHist, setCoupHist] = useState(false);
  const [coupCount, setCoupCount] = useState(null);  // on-hand count for the balance strip

  // Ledger tab
  const [ledger, setLedger] = useState([]);
  const [ledgerMore, setLedgerMore] = useState(false);
  const [ledgerCursor, setLedgerCursor] = useState(null);
  const [ledgerLoaded, setLedgerLoaded] = useState(false);

  const [err, setErr] = useState("");

  // Balance strip + on-hand cards + coupon count (for the strip) load on open.
  useEffect(() => {
    apiGet("/api/account").then((d) => { if (d && !d.error) setAcct(d); });
    apiGet("/api/account/coupons").then((d) => { if (d && !d.error) setCoupCount((d.coupons || []).length); });
  }, []);

  // Cards tab: roster (?all=1) + first page of usage log — lazy on first visit.
  useEffect(() => {
    if (tab !== "cards" || cardsLoaded) return;
    setCardsLoaded(true);
    apiGet("/api/account/card-history?all=1").then((d) => { if (d && !d.error) setRoster(d); });
    apiGet("/api/account/card-history?count=8").then((d) => {
      if (d && !d.error) { setLog(d.logs || []); setLogMore(!!d.has_next); setLogCursor(d.end_cursor || null); }
    });
  }, [tab, cardsLoaded]);

  // Coupons tab: reload whenever the on-hand/history toggle flips.
  useEffect(() => {
    if (tab !== "coupons") return;
    apiGet("/api/account/coupons" + (coupHist ? "?history=1" : "")).then((d) => {
      if (d && d.error) { setErr(d.error); return; }
      setCoupons((d && d.coupons) || []);
    });
  }, [tab, coupHist]);

  // Ledger tab: first page, lazy on first visit.
  useEffect(() => {
    if (tab !== "ledger" || ledgerLoaded) return;
    setLedgerLoaded(true);
    apiGet("/api/account/credit-log?count=12").then((d) => {
      if (d && !d.error) { setLedger(d.entries || []); setLedgerMore(!!d.has_more); setLedgerCursor(d.next_cursor || null); }
    });
  }, [tab, ledgerLoaded]);

  const loadMoreLog = async () => {
    if (!logCursor) return;
    const d = await apiGet("/api/account/card-history?count=8&after=" + encodeURIComponent(logCursor));
    if (d && !d.error) { setLog((cur) => cur.concat(d.logs || [])); setLogMore(!!d.has_next); setLogCursor(d.end_cursor || null); }
  };
  const loadOlderLedger = async () => {
    if (!ledgerCursor) return;
    const d = await apiGet("/api/account/credit-log?count=12&before=" + encodeURIComponent(ledgerCursor));
    if (d && !d.error) { setLedger((cur) => cur.concat(d.entries || [])); setLedgerMore(!!d.has_more); setLedgerCursor(d.next_cursor || null); }
  };

  const onHand = (acct && acct.cards_by) ? acct.cards_by.filter((c) => c.count > 0) : [];
  const rosterRows = roster && roster.templates
    ? Object.entries(roster.templates).map(([name, t]) => ({ name, ...t })) : [];

  // Balance strip: split is unknown when the backend returned null (honest, never fake 0).
  const splitUnknown = acct && (acct.credits_paid == null || acct.credits_free == null);

  return (
    <>
      <div className="mgcp-sub-scrim" onClick={onClose} />
      <div className="mgcp-sub-host">
        <div className="mgcp-sub-slab acct-slab" role="dialog" aria-label="PixAI account">
          <div className="mgcp-sub-titlerow">
            <h3>✦ PixAI account</h3>
            <span className="acct-readonly">read-only — the library reports; it never spends, redeems, or purchases</span>
            <button type="button" className="mgv-x" style={{ marginLeft: "auto" }} onClick={onClose} aria-label="Close">×</button>
          </div>

          {/* Balance strip */}
          <div className="acct-balance">
            <div><div className="acct-bignum accent">{acct ? nfmt(acct.credits) : "…"}</div><div className="acct-kick">credits</div></div>
            <div><div className={"acct-splitnum" + (splitUnknown ? " unknown" : "")}>{splitUnknown ? "— unknown" : nfmt(acct && acct.credits_paid)}</div><div className="acct-kick">of which paid</div></div>
            <div><div className={"acct-splitnum" + (splitUnknown ? " unknown" : "")}>{splitUnknown ? "— unknown" : nfmt(acct && acct.credits_free)}</div><div className="acct-kick">of which free</div></div>
            <div><div className="acct-midnum">{acct ? nfmt(acct.cards) : "…"}</div><div className="acct-kick">free cards on hand</div></div>
            <div><div className="acct-midnum">{coupCount == null ? "…" : coupCount}</div><div className="acct-kick">coupons</div></div>
          </div>

          {/* Tabs */}
          <div className="acct-tabs">
            {TABS.map(([k, lbl]) => (
              <button type="button" key={k} className={"acct-tab" + (tab === k ? " on" : "")} onClick={() => setTab(k)}>{lbl}</button>
            ))}
          </div>

          <div className="acct-body">
            {err && <div className="acct-err">⚠ {err}</div>}

            {tab === "cards" && (
              <>
                <div className="acct-grp">On hand now — feeds the rail vital</div>
                <div className="acct-onhandrow">
                  {onHand.length ? onHand.map((c) => (
                    <div className="acct-onhandcard" key={c.name}>
                      <b>{c.count}</b><span>{c.name}</span>
                      {c.category ? <span className="acct-dimchip">{c.category}</span> : null}
                    </div>
                  )) : <div className="acct-empty">No free cards on hand.</div>}
                </div>

                <div className="acct-grp">Lifetime card types</div>
                {rosterRows.length ? rosterRows.map((ct) => (
                  <div className="acct-row" key={ct.name}>
                    <div className="acct-rowmain"><b>{ct.name}</b>
                      <div className="acct-rowmeta">{[ct.task_type, ct.first_seen ? "first seen " + day(ct.first_seen) : "", ct.last_seen ? "last " + day(ct.last_seen) : ""].filter(Boolean).join(" · ")}</div>
                    </div>
                    {ct.category ? <span className="acct-dimchip">{ct.category}</span> : null}
                    <span className="acct-numcell"><b>{ct.consumed}</b> used</span>
                    <span className="acct-numcell"><b>{ct.refunded}</b> refunded</span>
                  </div>
                )) : <div className="acct-empty">{roster ? "No card history yet." : "loading…"}</div>}

                <div className="acct-grp" style={{ marginTop: 16 }}>Usage history</div>
                {log.map((ev, i) => (
                  <div className="acct-row" key={ev.record_id || i}>
                    <span className={"acct-act" + (ev.action === "refunded" ? " refund" : "")}>{ev.action === "refunded" ? "↺ refunded" : "– consumed"}</span>
                    <div className="acct-rowmain" style={{ fontSize: 12 }}>{ev.template_name}
                      <div className="acct-rowmeta">task {ev.task_id}</div>
                    </div>
                    <span className="acct-monodim">{ev.credit_cost != null ? nfmt(ev.credit_cost) : ""}</span>
                    <span className="acct-monodim">{day(ev.created_at)}</span>
                  </div>
                ))}
                {logMore && <div className="acct-load" onClick={loadMoreLog}>Load more ⌄</div>}
              </>
            )}

            {tab === "coupons" && (
              <>
                <div className="acct-couphead">
                  <div className="acct-grp" style={{ margin: 0 }}>{coupHist ? "History — redeemed & expired" : "On hand"}</div>
                  <div style={{ flex: 1 }} />
                  <button type="button" className="acct-histchip" onClick={() => setCoupHist((v) => !v)}>{coupHist ? "← Back to on hand" : "Show history"}</button>
                </div>
                <div className="acct-couphint">Informational only — redeeming happens on pixai.art, not here.</div>
                {coupons.length ? coupons.map((cp, i) => (
                  <div className="acct-row" key={cp.code || i}>
                    <b className={"acct-pct" + (cp.status === "available" ? " avail" : "")}>+{cp.boost_percent}%</b>
                    <div className="acct-rowmain"><span className="acct-mono">{cp.code}</span>
                      <div className="acct-rowmeta">{[cp.note, cp.issued_by ? "issued by " + cp.issued_by : ""].filter(Boolean).join(" · ")}</div>
                    </div>
                    <span className="acct-monodim">{[day(cp.available_since), day(cp.available_until)].filter(Boolean).join(" → ")}</span>
                    <span className={"acct-status " + (cp.status || "")}>{cp.status}</span>
                  </div>
                )) : <div className="acct-empty">{coupHist ? "No past coupons." : "No coupons on hand."}</div>}
              </>
            )}

            {tab === "ledger" && (
              <>
                <div className="acct-grp">Credit movement — newest first</div>
                {ledger.map((le, i) => {
                  const pos = (le.amount || 0) > 0;
                  const known = KNOWN_REASONS.indexOf(le.type) >= 0;
                  return (
                    <div className="acct-row" key={le.ref_id || i}>
                      <b className={"acct-amt" + (pos ? " pos" : "")}>{pos ? "+" : "−"}{nfmt(Math.abs(le.amount || 0))}</b>
                      <span className={"acct-dimchip" + (known ? "" : " raw")}>{le.type}</span>
                      <div className="acct-rowmain acct-ellip" style={{ fontSize: 12 }}>{le.label}</div>
                      <span className="acct-monodim">{day(le.created_at)}</span>
                    </div>
                  );
                })}
                {ledger.length === 0 && <div className="acct-empty">{ledgerLoaded ? "No ledger entries." : "loading…"}</div>}
                {ledgerMore && <div className="acct-load" onClick={loadOlderLedger}>Load older ⌄</div>}
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
