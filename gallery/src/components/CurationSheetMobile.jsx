import React, { useState } from "react";
import "../styles/curation.css";
import "../styles/curation-mobile.css";

/* THE PHONE'S BULK CURATION (Session N, N4). The desktop's bulk bar, drawn for a thumb: the
   stars, a tag, Keeper and Reject over the picked pictures, at the top of the Actions sheet
   (the sheet's own list -- send to the Loom, add to a collection, print, delete -- follows).
   Long-press on a tile has started Select mode since the phone grid was built, so this is
   what a selection can now DO beyond moving pictures around.

   Every control is 44 px. The verbs are the shell's (useCurate): the server answers how many
   pictures REALLY changed and which values to put back on Undo, and the toast says so.
   `Clear` takes the rating off, since the phone has no 0 key. The tag box is checked here
   first (lowercase, hyphenated, up to 32 characters) so a refusal reads in place. */
export default function CurationSheetMobile({ count, onStar, onTag, onKeeper, onReject }) {
  const [tag, setTag] = useState("");
  const addTag = () => {
    if (!tag.trim()) return;
    onTag(tag);
    setTag("");
  };
  return (
    <div className="mgcs-sheet" role="group" aria-label="Curate the selection">
      <div className="mgcs-cap">RATE {count} {count === 1 ? "PICTURE" : "PICTURES"}</div>
      <div className="mgcs-stars">
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} type="button" className="mgcs-star" aria-label={"Rate " + n + " stars"}
            onClick={() => onStar(n)}>{"☆"}</button>
        ))}
        <button type="button" className="mgcs-clear" onClick={() => onStar(0)}>Clear</button>
      </div>
      <div className="mgcs-marks">
        <button type="button" className="mgcs-mark keeper" onClick={onKeeper}>{"✓"} Keeper</button>
        <button type="button" className="mgcs-mark" onClick={onReject}>{"✕"} Reject</button>
      </div>
      <div className="mgcs-tagrow">
        <input className="mgcs-tag" value={tag} placeholder="tag…" aria-label="Tag to add"
          autoCapitalize="none" autoCorrect="off"
          onChange={(e) => setTag(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }} />
        <button type="button" className="mgcs-addtag" disabled={!tag.trim()} onClick={addTag}>+ Tag</button>
      </div>
    </div>
  );
}
