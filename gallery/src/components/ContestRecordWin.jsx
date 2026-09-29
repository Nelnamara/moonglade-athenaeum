import React, { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api.js";
import { invalidate } from "../hooks/swrCache.js";
import { canCheck, contestOptions, outcomeView, stateLine } from "../lib/contestWinCore.js";
import "../styles/myart-contests.css";

/* RECORD A WIN, as the fallback (L3, "Small Calls Handoff" section L3 + Contest Surface v2 E4).

   Wins the app can see are recorded automatically: at each contest's result date and then
   daily for two weeks, the app reads PixAI's winners list and a win is recorded only when the
   entry is on it with a tier. This is the fallback for the one that "won but isn't shown":
   pick the contest (from your own entries), paste the link to the entry and press Check. The
   app reads that contest's winners once, and a win is recorded ONLY when it matches -- the
   link is then kept as the receipt. Nothing is ever typed in as a claim; only PixAI's own
   pages count.

   THE STATE LINE says where the row stands: "Verified · Tier 2, 200,000 credits" or "Not
   verified yet · the app re-checks daily until <day>". A refusal or a failed check reads in
   peach, never ruby; results-not-out reads quiet, because an empty list is undecided, not lost.

   Placement is a TIER plus the prize (PixAI's `rank` is the prize tier, shared by everyone in
   it) -- see lib/contestWinCore.js. The desktop wraps this in the confirm dialog's own
   scrim + host (same z rungs as ContestConfirm); the phone hands the bare body to a
   MobileSheet (`phone`), which carries the title, so the body drops its own.

   Nothing here reads or writes on open except the CSRF token every POST on this surface
   carries; the only network read that follows is the Check press, and it is one GET of one
   contest's winners on the server. There is no write to PixAI anywhere on this road. */

export default function ContestRecordWin({ rows, initialContestId, csrfToken, onDone, onClose, phone }) {
  const options = contestOptions(rows);
  const [cid, setCid] = useState(initialContestId || (options[0] && options[0].id) || "");
  const [url, setUrl] = useState("");
  const [csrf, setCsrf] = useState(csrfToken || "");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [tokenErr, setTokenErr] = useState(false);

  // The token comes from the parent when it has one, else it is fetched once (the same source
  // the publish and entry dialogs read it from). A missing token is SAID, not left as a dead
  // button.
  useEffect(() => {
    if (csrfToken) { setCsrf(csrfToken); return undefined; }
    let dead = false;
    apiGet("/api/myart/items").then((d) => {
      if (dead) return;
      const t = (d && d.csrf) || "";
      if (t) setCsrf(t); else setTokenErr(true);
    });
    return () => { dead = true; };
  }, [csrfToken]);

  const row = (rows || []).find((r) => String(r.contest_id) === String(cid)) || null;
  const line = result ? outcomeView(result) : stateLine(row);

  const check = async () => {
    if (!canCheck(url, busy) || !csrf) return;
    setBusy(true);
    const d = await apiPost("/api/contest/check", { csrf, url: url.trim(), contest_id: cid });
    setBusy(false);
    setResult(d);
    if (d && d.verified) {
      // A verified win is an achievement input: the cached roster the Folio and Panel share
      // is stale the moment this lands, and the entries list re-reads through onDone.
      invalidate("/api/achievements");
      if (onDone) onDone(d);
    }
  };

  const body = (
    <div className={"mgcrw" + (phone ? " phone" : "")}>
      {phone ? null : (
        <div className="mgctc-head">
          <div className="mgctc-title">Record a win</div>
          <button type="button" className="mgv-x" onClick={() => onClose && onClose()}
            aria-label="Close">×</button>
        </div>
      )}
      <div className="mgcrw-blurb">
        For a placement the app can't see on its own. Wins it can see are recorded
        automatically — this is the fallback. Only PixAI's own pages count.
      </div>

      <label className="mgcrw-lab" htmlFor="mgcrw-contest">CONTEST</label>
      {options.length ? (
        <select id="mgcrw-contest" className="mgcrw-input sel" value={cid}
          onChange={(e) => { setCid(e.target.value); setResult(null); }}>
          {options.map((o) => (
            <option key={o.id} value={o.id}>{o.title}{o.won ? " · verified" : ""}</option>
          ))}
        </select>
      ) : (
        <div className="mgcrw-input sel dim">No entries yet</div>
      )}

      <label className="mgcrw-lab" htmlFor="mgcrw-url">EVIDENCE URL</label>
      <div className="mgcrw-row">
        <input id="mgcrw-url" className="mgcrw-input url" type="text" inputMode="url"
          autoComplete="off" autoCapitalize="off" spellCheck={false}
          placeholder="pixai.art/en/artwork/…" value={url}
          onChange={(e) => { setUrl(e.target.value); setResult(null); }}
          onKeyDown={(e) => { if (e.key === "Enter") check(); }} />
        <button type="button" className="mgcrw-check" disabled={!canCheck(url, busy) || !csrf}
          onClick={check}>{busy ? "Checking…" : "Check"}</button>
      </div>

      <div className={"mgcrw-msg " + line.tone} role="status" aria-live="polite">
        {line.text}
        {line.receipt ? (
          <>
            {" · "}
            <a href={line.receipt} target="_blank" rel="noopener noreferrer">receipt ↗</a>
          </>
        ) : null}
      </div>
      {tokenErr && (
        <div className="mgcrw-msg warn">
          Couldn't verify this session — reload the page and try again.
        </div>
      )}
      <div className="mgcrw-foot">
        The app re-checks every contest daily for two weeks after its results.
      </div>
      <div className="mgctc-acts">
        <button type="button" className="mgct-ghost" onClick={() => onClose && onClose()}>
          Close
        </button>
      </div>
    </div>
  );

  if (phone) return body;
  return (
    <>
      <div className="mgct-subscrim" onClick={() => onClose && onClose()} />
      <div className="mgct-subhost">
        <div className="mgct-sub confirm" role="dialog" aria-label="Record a win">{body}</div>
      </div>
    </>
  );
}
