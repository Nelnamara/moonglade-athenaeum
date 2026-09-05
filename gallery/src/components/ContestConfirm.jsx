import React, { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api.js";
import { invalidate } from "../hooks/swrCache.js";
import { countdown, dayOf } from "../hooks/useContests.js";
import { classifyEntryError, entryCostFace } from "../lib/contestEntry.js";
import { show as toast } from "../notify/toastStore.js";
import "../styles/myart-contests.css";

/* THE CONFIRM — Contest Surface v2.dc.html D2/D3/D4, the one door every direct entry
   goes through (owner ruling F4: always a confirm, no exceptions). The publish path has
   its own D1 face inside PublishOverlay, because that entry rides the publish mutation
   rather than this route.

   Two POSTs, exactly as the server's contract asks: an unconfirmed one to /api/contest/
   enter that touches no account and answers what it WOULD do, then the confirmed one.

   THE COST LINE and the refusal sentences moved to lib/contestEntry.js on 2026-09-04, when
   the phone's entry screen (ContestEntryMobile.jsx) needed to say the same things about
   the same irreversible act -- see that module's own header for why those two in
   particular are shared rather than copied. The DC's "♦ 500 CR" remains a layout stand-in
   (its own annotation says so); the number rendered here is always the server's answer. */

export default function ContestConfirm({ contest, art, onClose, onEntered, onPickDifferent,
                                        csrfToken }) {
  const [csrf, setCsrf] = useState("");
  const [ask, setAsk] = useState(null);        // the server's preview
  const [busy, setBusy] = useState(false);
  const [fail, setFail] = useState(null);
  const [done, setDone] = useState(null);

  // The token comes from the parent when it has one (it usually does -- the publish
  // surfaces already hold it), and is fetched only as a fallback. Either way a MISSING
  // token is surfaced: without this the Confirm button simply never armed, because the
  // preview effect below is gated on `csrf` and silently never ran. A dead button that
  // explains nothing is the worst possible answer on an irreversible action.
  useEffect(() => {
    if (csrfToken) { setCsrf(csrfToken); return; }
    apiGet("/api/myart/items").then((d) => {
      const t = (d && d.csrf) || "";
      if (t) setCsrf(t);
      else setFail({ icon: "⚠", title: "Couldn't verify this session",
                     copy: "Reload the page and try again — nothing was submitted." });
    });
  }, [csrfToken]);

  // The preview: no account is touched, and it carries the cost answer the slot renders.
  useEffect(() => {
    if (!csrf || !contest || !art) return;
    let dead = false;
    apiPost("/api/contest/enter", { slug: contest.slug, artwork_id: art.artwork_id, csrf })
      .then((d) => {
        if (dead) return;
        if (d.error) setFail(classifyEntryError(d.error)); else setAsk(d);
      });
    return () => { dead = true; };
  }, [csrf, contest, art]);

  const confirm = async () => {
    setBusy(true); setFail(null);
    const d = await apiPost("/api/contest/enter",
                            { slug: contest.slug, artwork_id: art.artwork_id, csrf, confirm: true });
    setBusy(false);
    if (d.error) { setFail(classifyEntryError(d.error)); return; }
    // An entry lands in The Arena, which is an achievement metric -- the cached roster the
    // Folio and the Panel share is stale the moment this succeeds. (The entries list itself
    // is refreshed by the caller's onEntered -> reloadMine, which writes through.)
    invalidate("/api/achievements");
    setDone(d);
    toast({ kind: "ok", title: "Entry submitted",
            msg: contest.title + " · counts toward The Arena", thumb: art.thumb || "" });
    if (onEntered) onEntered(contest, art);
  };

  const left = countdown(contest.end_at);
  const official = (contest.type || "") === "official";
  const costFace = entryCostFace(ask ? ask.spends_credits : undefined);

  return (
    <>
      <div className="mgct-subscrim" onClick={onClose} />
      <div className="mgct-subhost">
        <div className="mgct-sub confirm" role="dialog" aria-label="Confirm entry">
          {done ? (
            <div className="mgctc-ok">
              <div className="tick">✓</div>
              <div className="h">Entered</div>
              <div className="c">
                <b>{art.title}</b> is in <b>{contest.title}</b>.
                {contest.result_at ? " Results " + dayOf(contest.result_at) + " — " : " "}
                track it under My entries.
              </div>
              <div className="chip">
                <span className="mgct-entered strong">★ Entered</span>
              </div>
              <div className="a">
                <button type="button" className="mgct-ghost" onClick={onClose}>Done</button>
                <button type="button" className="mgct-ghost lav"
                  onClick={() => onClose("mine")}>My entries →</button>
              </div>
            </div>
          ) : (
            <>
              <div className="mgctc-head">
                <div className="mgctc-title">Confirm entry</div>
                <button type="button" className="mgv-x" onClick={() => onClose()} aria-label="Close">×</button>
              </div>

              {fail ? (
                <>
                  <div className="mgctc-fail">
                    <div className="i">{fail.icon}</div>
                    <div>
                      <div className="t">{fail.title}</div>
                      <div className="c">{fail.copy}</div>
                    </div>
                  </div>
                  <div className="mgctc-acts">
                    {onPickDifferent && (
                      <button type="button" className="mgct-ghost lav"
                        onClick={onPickDifferent}>Pick different art</button>
                    )}
                    <button type="button" className="mgct-ghost" onClick={() => onClose()}>Close</button>
                  </div>
                </>
              ) : (
                <>
                  <div className="mgctc-art">
                    {art.thumb
                      ? <img className="mgctc-artthumb" src={art.thumb} alt="" />
                      : <span className="mgctc-artthumb" />}
                    <div style={{ minWidth: 0 }}>
                      <div className="mgctc-artname" title={art.title}>{art.title}</div>
                      <div className="mgctc-artsub">
                        {art.date ? "made " + dayOf(art.date) : "published"}
                      </div>
                    </div>
                  </div>
                  <div className="mgctc-arrow">enters ↓</div>
                  <div className={"mgctc-ct" + (official ? " official" : "")}>
                    {contest.cover_url
                      ? <img className="mgctc-ctbanner" src={contest.cover_url} alt="" />
                      : <span className="mgctc-ctbanner" />}
                    <div className="mgctch-col">
                      <div className="mgctc-ctname" title={contest.title}>{contest.title}</div>
                      <div className="mgctc-ctsub">
                        closes {dayOf(contest.end_at) || "—"}{left && !left.over ? " · " + left.text : ""}
                      </div>
                    </div>
                    <span className={"mgct-badge " + (official ? "official" : "community")}>
                      {official ? "☀ OFFICIAL" : "🤝 COMMUNITY"}
                    </span>
                  </div>
                  <div className="mgctc-cost">
                    <div className="k">Entry cost</div>
                    <div className={"v " + costFace.cls}>{costFace.text}</div>
                  </div>
                  <div className="mgctc-acts">
                    <button type="button" className="mgct-ghost" onClick={() => onClose()}
                      disabled={busy}>Cancel</button>
                    <button type="button" className="mgctc-go" onClick={confirm}
                      disabled={busy || !ask}>
                      {busy ? "entering…" : "Confirm entry"}
                    </button>
                  </div>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
