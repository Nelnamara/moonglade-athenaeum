import React, { useEffect, useState } from "react";
import { NOTE_MAX, checkTag, clampNote } from "../curation/curationCore.js";
import "../styles/curation.css";

/* DETAILS: YOUR LAYER (Session N, N3). The three things only the owner says about a picture:
   a keeper or reject mark (one at a time, choosing one clears the other), tags, and a note.
   They live in the LOCAL catalog and are never sent to PixAI -- the card says so, in the
   page's own words.

   Every edit goes through `onCurate(ids, op)` (App's useCurate), so the grid's card, the
   Lightbox and this record all show what the server answered. A tag is checked here first
   (lowercase and hyphenated, up to 32 characters, up to 32 tags) so a refusal reads next to
   the field, not as a toast. */
export default function YourLayer({ mediaId, personal, onCurate }) {
  const p = personal || { tags: [], mark: "", note: "" };
  const [tagInput, setTagInput] = useState("");
  const [err, setErr] = useState("");
  const [note, setNote] = useState(p.note || "");
  useEffect(() => { setNote(p.note || ""); }, [mediaId, p.note]);
  useEffect(() => { setTagInput(""); setErr(""); }, [mediaId]);

  const mark = (k) => onCurate([mediaId], { mark: p.mark === k ? "" : k });
  const addTag = () => {
    if (!tagInput.trim()) return;
    const chk = checkTag(tagInput, p.tags);
    if (!chk.ok) { setErr(chk.error); return; }
    setErr("");
    setTagInput("");
    if (!chk.dupe) onCurate([mediaId], { add_tag: chk.tag });
  };
  const saveNote = () => {
    if (note !== (p.note || "")) onCurate([mediaId], { note });
  };

  return (
    <section className="mgcu-layer" aria-label="Your layer">
      <div className="mgcu-layer-cap">YOUR LAYER</div>
      <div className="mgcu-verdicts">
        <button type="button" className={"mgcu-verdict keeper" + (p.mark === "keeper" ? " on" : "")}
          aria-pressed={p.mark === "keeper"} onClick={() => mark("keeper")}>{"✓"} Keeper</button>
        <button type="button" className={"mgcu-verdict reject" + (p.mark === "reject" ? " on" : "")}
          aria-pressed={p.mark === "reject"} onClick={() => mark("reject")}>{"✕"} Reject</button>
      </div>
      <div className="mgcu-sub">
        <div className="mgcu-layer-cap">TAGS</div>
        <div className="mgcu-tags">
          {p.tags.map((t) => (
            <button key={t} type="button" className="mgcu-tag" title="Remove tag"
              onClick={() => onCurate([mediaId], { remove_tag: t })}>{t} {"✕"}</button>
          ))}
        </div>
        <input className="mgcu-field" value={tagInput} placeholder="add a tag, Enter" aria-label="Add a tag"
          onChange={(e) => { setTagInput(e.target.value); setErr(""); }}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }} />
        {err ? <div className="mgcu-field-err" role="alert">{err}</div> : null}
      </div>
      <div className="mgcu-sub">
        <div className="mgcu-layer-cap">NOTE</div>
        <input className="mgcu-field" value={note} maxLength={NOTE_MAX} placeholder="a note only you see"
          aria-label="Note" onChange={(e) => setNote(clampNote(e.target.value))} onBlur={saveNote}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); } }} />
      </div>
      <div className="mgcu-privacy">Private. It{"’"}s kept in your local catalog and never sent to PixAI.</div>
    </section>
  );
}
