import React, { useEffect, useMemo, useState } from "react";
import { apiGet } from "../api.js";
import { dayOf, qualifies } from "../hooks/useContests.js";
import "../styles/myart-contests.css";

/* THE PICKER — Contest Surface v2.dc.html C1/C2/C3 (§8.5): one modal, two labeled
   sections, same tile density, single select ring in --accent with a ✓ chip.

   ☆ SHORTLIST FIRST. The shipped Shortlist button stages the gallery's selection into a
   collection named "Contest: <title> (ends <date>)" (App.jsx's shortlistContest), so this
   enumerates the collections that carry that name for THIS contest and shows their
   members first. A shortlisted piece that was never published has no artwork to enter, so
   the section shows the intersection with published art -- the honest membership, not a
   list of tiles that would all refuse.

   ELIGIBLE PUBLISHED. Everything else the owner has published that post-dates the
   contest's start. GROUNDED, and the label says what it means: the catalog holds no
   artwork PUBLISH date (--sync-artworks stores none), so the date on a tile is when the
   piece was MADE. It is a fair proxy and a deliberately best-effort filter -- PixAI's own
   NOT_ELIGIBLE is the real gate, and the confirm dialog surfaces it. */

export default function ContestPicker({ contest, onCancel, onPick, onOpenPublish, onBrowse }) {
  const [items, setItems] = useState(null);
  const [shortIds, setShortIds] = useState(null);   // Set of media_id, or null while loading
  const [sel, setSel] = useState(null);

  useEffect(() => {
    let dead = false;
    apiGet("/api/myart/items").then((d) => { if (!dead) setItems(d.items || []); });
    return () => { dead = true; };
  }, []);

  // The shortlist collection for THIS contest, if the owner staged one.
  useEffect(() => {
    let dead = false;
    const title = String(contest.title || "");
    const exact = "Contest: " + (title || "(untitled)")
      + (contest.end_at ? " (ends " + dayOf(contest.end_at) + ")" : "");
    apiGet("/api/collections").then((d) => {
      if (dead) return;
      const names = (d.collections || []).map((c) => (typeof c === "string" ? c : c.name));
      const hit = names.find((n) => n === exact)
        || names.find((n) => n && n.startsWith("Contest: ") && title
                             && n.toLowerCase().includes(title.toLowerCase()));
      if (!hit) { setShortIds(new Set()); return; }
      apiGet("/api/next/library", { collection: hit, page_size: 200, sort: "newest" })
        .then((lib) => {
          if (dead) return;
          setShortIds(new Set((lib.items || []).map((it) => it.media_id)));
        });
    });
    return () => { dead = true; };
  }, [contest]);

  const eligible = useMemo(
    () => (items || []).filter((it) => qualifies(it, contest)), [items, contest]);
  const shortlist = useMemo(
    () => (shortIds ? eligible.filter((it) => shortIds.has(it.media_id)) : []),
    [eligible, shortIds]);
  const rest = useMemo(
    () => (shortIds ? eligible.filter((it) => !shortIds.has(it.media_id)) : eligible),
    [eligible, shortIds]);

  const loading = items === null || shortIds === null;
  const nothing = !loading && eligible.length === 0;
  const started = dayOf(contest.start_at);

  const tile = (it) => (
    <button type="button" key={it.media_id}
      className={"mgct-picktile" + (sel && sel.media_id === it.media_id ? " on" : "")}
      title={it.title} onClick={() => setSel(it)}>
      <img src={it.thumb} alt="" loading="lazy" />
      {sel && sel.media_id === it.media_id && <span className="mgct-pickcheck">✓</span>}
      <div className="mgct-pickdate">{dayOf(it.created_at).slice(5)}</div>
    </button>
  );

  return (
    <>
      <div className="mgct-subscrim" onClick={onCancel} />
      <div className="mgct-subhost">
        <div className="mgct-sub pick" role="dialog" aria-label="Pick an artwork to enter">
          <div className="mgct-pickhead">
            <div>
              <div className="mgct-picktitle">Enter — {contest.title}</div>
              <div className="mgct-picksub">
                ends {dayOf(contest.end_at) || "—"} · pick one artwork
              </div>
            </div>
            <button type="button" className="mgv-x" onClick={onCancel} aria-label="Close">×</button>
          </div>

          {loading && <div className="mgh-loading">reading your published art…</div>}

          {nothing && (
            <div className="mgct-pickempty">
              <div className="glyph">☆</div>
              <div className="t">Nothing eligible yet</div>
              <div className="c">
                Only art published after this contest opened{started ? " (" + started + ")" : ""} can
                enter. Publish something new — publishing can enter it directly — or ☆ shortlist
                candidates from the gallery for later.
              </div>
              <div className="a">
                <button type="button" className="mgct-ghost lav" onClick={onOpenPublish}>Open Publish</button>
                <button type="button" className="mgct-ghost" onClick={onBrowse}>Browse the gallery</button>
              </div>
            </div>
          )}

          {!loading && !nothing && (
            <>
              {shortlist.length > 0 && (
                <>
                  <div className="mgct-pickh shortlist">
                    ☆ SHORTLIST <span className="n">— staged for this contest · {shortlist.length}</span>
                  </div>
                  <div className="mgct-pickgrid">{shortlist.map(tile)}</div>
                </>
              )}
              {rest.length > 0 && (
                <>
                  <div className="mgct-pickh">
                    ELIGIBLE PUBLISHED <span className="n">
                      · made after {started || "the contest opened"} · newest first · {rest.length}
                    </span>
                  </div>
                  <div className="mgct-pickgrid">{rest.map(tile)}</div>
                </>
              )}
              {shortlist.length === 0 && (
                <div className="mgct-picktip">
                  ☆ Tip — the Shortlist button on any contest card stages your gallery
                  selection here for later.
                </div>
              )}
              <div className="mgct-pickfoot">
                <div className="mgct-picksel">
                  {sel ? <>1 selected — <b>{sel.title}</b></> : "nothing selected yet"}
                </div>
                <button type="button" className="mgct-ghost" onClick={onCancel}>Cancel</button>
                <button type="button" className="mgct-enter small" disabled={!sel}
                  onClick={() => onPick(sel)}>Continue →</button>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
