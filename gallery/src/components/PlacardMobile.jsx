import React from "react";
import { accessionStamp, placardStrip, SAVER_THUMB } from "../lib/phoneCore.js";
import "../styles/phone-q.css";

/* The card placard on the phone (Session Q, Q1; Phone Handoff.dc.html): the desktop placard's own two
   facts -- the accession stamp (catalog number and date) and the sibling strip (the other pictures from
   the same batch) -- between the picture and the action row in Lightbox Mobile.

   THE DATA IS THE DESKTOP'S, NOT A NEW CALL. `siblings` is what the page's ONE batched POST /api/siblings
   answered for this picture's task (the Lightbox asks once per page of pictures, never per picture), and
   the picture's own row supplies the stamp. Tapping a sibling swaps the picture IN PLACE: the sibling is
   on the loaded page, so the viewer just moves to it (`onPick(index)`) -- the current one is ringed. One
   that lives on another page is drawn dimmed and does nothing (there is no per-picture read to fetch it
   with). A single image draws "single image" and no strip.

   The strip's tiles are the 256 px thumbnails whatever the saver says: the server's own sibling URLs are
   its 32 px strip tier, which is soft at the 38 px these are drawn at on a 2-3x screen, and 256 is a
   fraction of the 768 the film strip below already loads. */

export default function PlacardMobile({ item, items, siblings, onPick }) {
  if (!item) return null;
  const strip = placardStrip(item, siblings, items);
  return (
    <div className="lbm-placard" role="group" aria-label="Placard">
      <div className="lbm-placard-stamp">{accessionStamp(item)}</div>
      {strip.single ? null : (
        <div className="lbm-placard-strip">
          {strip.tiles.map((t, k) => {
            const away = t.index < 0;
            return (
              <button key={t.media_id} type="button"
                className={"lbm-sib" + (t.current ? " on" : "") + (away ? " away" : "") + (t.is_video ? " vid" : "")}
                aria-label={"Sibling " + (k + 1) + " of " + strip.tiles.length + (t.current ? ", showing" : away ? ", on another page" : "")}
                aria-current={t.current ? "true" : undefined}
                disabled={away}
                onClick={() => { if (!away && !t.current) onPick(t.index); }}>
                <img src={"/thumbs/" + encodeURIComponent(t.media_id) + ".jpg?s=" + SAVER_THUMB} alt="" draggable={false} />
              </button>
            );
          })}
        </div>
      )}
      <div className="lbm-placard-line">{strip.line}</div>
    </div>
  );
}
