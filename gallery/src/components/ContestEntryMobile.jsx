import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost } from "../api.js";
import { invalidate } from "../hooks/swrCache.js";
import { qualifies } from "../hooks/useContests.js";
import { classifyEntryError, entryCostFace } from "../lib/contestEntry.js";
import { show as toast } from "../notify/toastStore.js";
import "../styles/contest-mobile.css";

/* THE ENTRY SCREEN — pixel source `Contest Mobile Handoff.dc.html` frame D3 ("ENTRY —
   full-screen picker"), Session D pick 1f. A fixed, full-viewport surface (z 70, above
   LightboxMobile's own sheet at 66), because all three entry points the handoff keeps can
   reach it: the board's Enter bar, the lightbox's action row, and Image Details' chip.

   ALWAYS-A-CONFIRM, unchanged (owner ruling F4, 2026-08-31). Nothing enters on one tap:
   picks are made, then the bar at the bottom is pressed, and only then does anything
   POST with `confirm: true`. Desktop reaches that confirm as a second dialog; the handoff
   folds it into this screen's own bar, which is the same contract with one screen fewer —
   the tag line, the fee, the contest and the count of what is about to be entered are all
   in front of you when you press it.

   MULTI-SELECT is what this screen adds over desktop's single-pick ContestPicker.jsx:
   PixAI takes one artwork per entry call, so N picks are N sequential POSTs of the SAME
   /api/contest/enter route desktop already uses. No new backend route, no batching
   endpoint, no change to the data contract.

   THE "/ N max" IS DISCLOSED, NOT INVENTED. The handoff's frame reads "{n} / 3 max" and
   its note says the cap comes from the contest's rules — but there is no such field: the
   board row (`list_contests`, moonglade_backup.py) carries prize/dates/vote/rules/tack and
   nothing that states an entry limit, and the design brief itself only ever hedged at
   "already at a per-contest entry limit IF ONE SURFACES". So the cap renders when the row
   actually carries one (`max_entries`) and the counter reads a plain "{n} selected" when
   it does not, which is every live row today. Quoting a made-up "3 max" on the screen
   before an irreversible act would be a lie about the contest's own rules.

   ELIGIBILITY is the shipped best-effort filter, unchanged: `qualifies()` (published, and
   made after the contest opened). The catalog holds no artwork PUBLISH date, so the date
   behind that filter is when a piece was MADE — a fair proxy, and PixAI's own NOT_ELIGIBLE
   is the real gate, surfaced here through the same words desktop uses.

   PRE-SELECTION. The lightbox and Image Details hand down the media_id they were showing.
   If that piece is in the eligible set it starts ticked; if it is not (unpublished, or
   made before the contest opened) nothing is ticked and the screen says so, rather than
   opening with a silent empty selection the person has to explain to themselves.

   NOT PORTED from desktop's picker: the ☆ SHORTLIST section. The Shortlist button lives on
   the desktop board only — nothing on the phone stages a collection — so a section for it
   here would always be empty. The handoff draws one flat newest-first grid, and that is
   what this is. */

export default function ContestEntryMobile({ contest, preselectMediaId, onClose, onEntered }) {
  const [items, setItems] = useState(null);
  const [csrf, setCsrf] = useState("");
  const [picked, setPicked] = useState([]);          // media_ids, in tap order
  const [ask, setAsk] = useState(null);              // the server's unconfirmed preview
  const [busy, setBusy] = useState(false);
  const [fail, setFail] = useState(null);
  const seeded = useRef(false);

  useEffect(() => {
    let dead = false;
    apiGet("/api/myart/items").then((d) => {
      if (dead) return;
      setItems(d.items || []);
      const t = (d && d.csrf) || "";
      if (t) setCsrf(t);
      else setFail({ title: "Couldn't verify this session",
                     copy: "Reload the page and try again — nothing was submitted." });
    });
    return () => { dead = true; };
  }, []);

  const eligible = useMemo(
    () => (items || []).filter((it) => qualifies(it, contest)), [items, contest]);

  // Seed the pre-selection ONCE, the first time the eligible set is known -- not on every
  // render of it, or clearing the tick would immediately re-tick itself.
  useEffect(() => {
    if (seeded.current || items === null) return;
    seeded.current = true;
    if (!preselectMediaId) return;
    if (eligible.some((it) => it.media_id === preselectMediaId)) setPicked([preselectMediaId]);
  }, [items, eligible, preselectMediaId]);

  // The fee, from the server, through the same three-faced slot desktop renders. The
  // unconfirmed POST performs NO network call upstream and touches no account (see
  // api_contest_enter's own docstring) -- it answers what an entry WOULD do. One call, for
  // the first pick: the answer is a property of the route's contract, not of the artwork.
  const firstPick = picked[0] || "";
  const firstArt = eligible.find((it) => it.media_id === firstPick) || null;
  useEffect(() => {
    if (!csrf || !firstArt) { setAsk(null); return undefined; }
    let dead = false;
    apiPost("/api/contest/enter",
            { slug: contest.slug, artwork_id: firstArt.artwork_id, csrf })
      .then((d) => { if (!dead && !d.error) setAsk(d); });
    return () => { dead = true; };
  }, [csrf, contest.slug, firstArt]);

  // See the header: a cap only when the row states one.
  const maxPicks = Number(contest.max_entries) > 0 ? Number(contest.max_entries) : 0;
  const atCap = maxPicks > 0 && picked.length >= maxPicks;

  const toggle = (mid) => setPicked((cur) => (cur.includes(mid)
    ? cur.filter((x) => x !== mid)
    : (maxPicks > 0 && cur.length >= maxPicks ? cur : cur.concat(mid))));

  const enter = async () => {
    if (!picked.length || busy) return;
    setBusy(true); setFail(null);
    const refused = [];
    let ok = 0;
    for (const mid of picked) {
      const art = eligible.find((it) => it.media_id === mid);
      if (!art) continue;
      // Sequential on purpose. These are irreversible account writes against one upstream
      // account; firing them in parallel would give PixAI a burst and give us no way to
      // say which of them landed. `apiPost` never throws and never retries.
      // eslint-disable-next-line no-await-in-loop
      const d = await apiPost("/api/contest/enter",
                              { slug: contest.slug, artwork_id: art.artwork_id, csrf,
                                confirm: true });
      if (d.error) refused.push({ art, why: classifyEntryError(d.error) });
      else ok += 1;
    }
    setBusy(false);
    if (ok > 0) {
      // An entry lands in The Arena, an achievement metric -- the cached roster the Folio
      // and the Panel share is stale the moment one succeeds.
      invalidate("/api/achievements");
      toast({ kind: "ok", title: ok === 1 ? "Entry submitted" : ok + " entries submitted",
              msg: contest.title + " · counts toward The Arena",
              thumb: (eligible.find((it) => it.media_id === picked[0]) || {}).thumb || "" });
      if (onEntered) onEntered(contest);
    }
    if (refused.length) {
      // The pieces that DID land are dropped from the selection, so a second press cannot
      // re-enter them; what stayed is exactly what was refused.
      const bad = refused.map((r) => r.art.media_id);
      setPicked((cur) => cur.filter((m) => bad.includes(m)));
      setFail(refused[0].why);
      return;
    }
    onClose();
  };

  const n = picked.length;
  const loading = items === null;
  const nothing = !loading && eligible.length === 0;
  const missedSource = !!preselectMediaId && !loading
    && !eligible.some((it) => it.media_id === preselectMediaId);
  const cost = entryCostFace(ask ? ask.spends_credits : undefined);

  return (
    <div className="cmb-entry" role="dialog" aria-modal="true"
      aria-label={"Enter " + (contest.title || "contest")}>
      <div className="cmb-entryhead">
        <button type="button" className="cmb-back" onClick={onClose} disabled={busy}>
          <span aria-hidden="true">‹</span> Back
        </button>
        <span className="t">Enter {contest.title}</span>
        <span className="n">
          {maxPicks > 0 ? n + " / " + maxPicks + " max" : n + " selected"}
        </span>
      </div>

      {/* The handoff's own line, plus the fee the server actually answers — this is the
          last screen before an irreversible, public account write, and desktop states the
          fee here. Leaving it off the phone would be a quieter screen, not a truer one. */}
      <div className="cmb-tagline">
        {contest.tack_name ? (
          <>
            <span className="cmb-ok">✓</span> tag <span className="cmb-tack">#{contest.tack_name}</span>
            {" added on entry · "}
          </>
        ) : null}
        publishes to PixAI · <span className={"fee " + cost.cls}>{cost.text}</span>
      </div>

      {loading && <div className="cmb-entrynote">reading your published art…</div>}

      {nothing && (
        <div className="cmb-entrynote">
          <b>Nothing eligible yet.</b> Only art published after this contest opened can
          enter it. Publish something from the Menu — publishing can enter it directly —
          then come back.
        </div>
      )}

      {missedSource && !nothing && (
        <div className="cmb-entrynote">
          That picture can't enter this one — only art you have <b>published</b>, after the
          contest opened, is eligible. Pick from what can.
        </div>
      )}

      {fail && (
        <div className="cmb-fail">
          <div className="t">{fail.title}</div>
          <div>{fail.copy}</div>
        </div>
      )}

      <div className="cmb-grid">
        {eligible.map((it) => {
          const on = picked.includes(it.media_id);
          return (
            <button type="button" key={it.media_id} title={it.title}
              className={"cmb-tile" + (on ? " on" : "")}
              disabled={busy || (!on && atCap)}
              aria-pressed={on}
              onClick={() => toggle(it.media_id)}>
              <img src={it.thumb} alt="" loading="lazy" decoding="async" />
              {on ? <span className="cmb-tick" aria-hidden="true">✓</span> : null}
            </button>
          );
        })}
      </div>

      <div className="cmb-confirmbar">
        <button type="button" className="cmb-metal" disabled={!n || busy || !csrf}
          onClick={enter}>
          {busy ? "entering…"
            : n ? "Confirm entry — " + n + " image" + (n > 1 ? "s" : "")
            : "Pick at least one image"}
          <i aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
