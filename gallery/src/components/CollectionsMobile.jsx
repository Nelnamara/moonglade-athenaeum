import React, { useCallback, useEffect, useRef, useState } from "react";
import Icon from "../icons/Icons.jsx";
import { fetchCollectionDetail, manageCollections } from "../api.js";
import { checkRename, deleteBody, mergePlan, tickTitle } from "../curation/curationCore.js";
import "../styles/curation.css";
import "../styles/curation-mobile.css";

/* THE COLLECTIONS SCREEN (Session N, N2, phone). The desktop manager's phone twin, reached from
   the header menu: every collection with its cover and count, the smart ones marked with the
   refresh mark. TAP a row to open that collection in the Gallery tab. SWIPE a row to the left
   for Rename and Delete (Curation Handoff, Phone). MERGE is a checkbox mode: Merge... turns on
   the ticks, two or more hand-picked collections are ticked, and the button says what it will
   do -- the first one ticked takes the pictures, the others go, pictures are de-duplicated and
   never deleted.

   THE SWIPE HAS A TAP TWIN. The app's phone is tap-first (drift 25: no swipe-dismiss anywhere
   else), and a swipe is invisible until someone knows it is there, so every row also carries a
   ... button that opens the same two actions. Neither is the only way in.

   Same rules as the desktop manager, from the same core (curationCore.js) and the same route
   (POST /api/collections/manage): names are trimmed and unique, smart collections rename and
   delete but cannot merge (their tick is dashed and says why), delete ALWAYS confirms and says
   how many pictures stay, and NOTHING here deletes a picture -- a collection is a label on
   pictures the library already holds, or a saved search. Local catalog only; nothing reaches
   PixAI. Nothing is written on open.

   SESSION P HOSTS ITS MANUAL ORDER HERE TOO (P6): `renderRowSlot(collection)` is drawn in
   .mgcm-slot for every hand-picked row. Empty today, and it takes no room while it is. */

const ACTIONS_W = 132;        // the two actions' width when a row is swiped open
const SWIPE_START = 8;        // px of sideways drag before it is a swipe and not a tap

function Row({ c, open, merging, ticked, first, plan, renaming, draft, setDraft, onOpenRow, setOpenName,
  onTick, onStartRename, onCommitRename, onDelete, renderRowSlot }) {
  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);
  const st = useRef(null);
  const swallow = useRef(false);            // a swipe's release must not also count as a tap
  const smart = c.kind === "smart";
  const shown = merging || renaming ? 0 : (open ? -ACTIONS_W : 0) + dx;

  const down = (e) => {
    if (merging || renaming) return;
    if (e.pointerType === "mouse" && e.button !== 0) return;
    st.current = { id: e.pointerId, x: e.clientX, y: e.clientY, base: open ? -ACTIONS_W : 0, on: false };
  };
  const move = (e) => {
    const s = st.current;
    if (!s || s.id !== e.pointerId) return;
    const mx = e.clientX - s.x, my = e.clientY - s.y;
    if (!s.on) {
      if (Math.abs(mx) < SWIPE_START || Math.abs(mx) < Math.abs(my) * 1.5) return;
      s.on = true;
      setDragging(true);
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* not capturable */ }
    }
    setDx(Math.max(-ACTIONS_W, Math.min(0, s.base + mx)) - s.base);
  };
  const up = (e) => {
    const s = st.current;
    st.current = null;
    if (!s || s.id !== e.pointerId) return;
    if (s.on) {
      const at = Math.max(-ACTIONS_W, Math.min(0, s.base + (e.clientX - s.x)));
      swallow.current = true;
      setTimeout(() => { swallow.current = false; }, 60);   // the click that follows a swipe, if any
      setDragging(false);
      setDx(0);
      setOpenName(at < -ACTIONS_W / 2 ? c.name : "");
    }
  };
  const cancel = () => { st.current = null; setDragging(false); setDx(0); };
  const tap = () => {
    if (swallow.current) { swallow.current = false; return; }
    if (merging) { onTick(c); return; }
    if (renaming) return;
    if (open) { setOpenName(""); return; }
    onOpenRow(c);
  };

  return (
    <div className={"mgcm-row" + (open ? " open" : "") + (ticked ? " ticked" : "")}>
      <div className="mgcm-acts" aria-hidden={!open}>
        <button type="button" className="mgcm-act" tabIndex={open ? 0 : -1} onClick={() => onStartRename(c)}>Rename</button>
        <button type="button" className="mgcm-act danger" tabIndex={open ? 0 : -1} onClick={() => onDelete(c)}>Delete</button>
      </div>
      <div className={"mgcm-face" + (dragging ? " drag" : "")} style={{ transform: "translateX(" + shown + "px)" }}
        onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={cancel}>
        {merging ? (
          <button type="button" className={"mgcm-box" + (ticked ? " on" : "") + (smart ? " smart" : "")}
            aria-pressed={ticked} aria-disabled={smart} title={tickTitle(c)}
            onClick={(e) => { e.stopPropagation(); onTick(c); }}>{ticked ? "✓" : ""}</button>
        ) : null}
        <span className="mgcm-cover" style={c.cover ? { backgroundImage: "url(/thumbs/" + encodeURIComponent(c.cover) + ".jpg)" } : undefined} />
        {renaming ? (
          <input className="mgcm-name" autoFocus value={draft} aria-label={"Name of " + c.name}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => onCommitRename(c)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); } }} />
        ) : (
          <button type="button" className="mgcm-main" onClick={tap}>
            <span className="mgcm-title"><Icon name="collection" /> {c.name}{smart ? " ⟳" : ""}</span>
            <span className="mgcm-meta">
              {(smart ? "smart · " : "") + c.count + (c.count === 1 ? " picture" : " pictures")
                + (first && plan.can ? " · merge target" : "")}
            </span>
          </button>
        )}
        <span className="mgcm-slot" data-slot={smart ? undefined : "collection-order"}>
          {!smart && renderRowSlot ? renderRowSlot(c) : null}
        </span>
        {!merging && !renaming ? (
          <button type="button" className="mgcm-more" aria-label={"Rename or delete " + c.name} aria-expanded={open}
            onClick={() => setOpenName(open ? "" : c.name)}>{"⋯"}</button>
        ) : null}
      </div>
    </div>
  );
}

export default function CollectionsMobile({ csrf, onOpenCollection, onChanged, renderRowSlot }) {
  const [rows, setRows] = useState(null);
  const [openName, setOpenName] = useState("");        // the row swiped open
  const [merging, setMerging] = useState(false);
  const [ticked, setTicked] = useState([]);            // names, in tick order
  const [renameName, setRenameName] = useState("");
  const [draft, setDraft] = useState("");
  const [delName, setDelName] = useState("");
  const [msg, setMsg] = useState({ text: "", err: false });
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => { setRows((await fetchCollectionDetail()) || []); }, []);
  useEffect(() => { reload(); }, [reload]);

  const all = rows || [];
  const plan = mergePlan(ticked, all);
  const say = (text, err) => setMsg({ text, err: !!err });
  const pics = (n) => n + " " + (n === 1 ? "picture" : "pictures");

  const tick = (c) => {
    if (c.kind === "smart") { say(tickTitle(c), true); return; }
    setTicked((t) => (t.indexOf(c.name) >= 0 ? t.filter((n) => n !== c.name) : t.concat(c.name)));
  };

  const startRename = (c) => { setOpenName(""); setDelName(""); setRenameName(c.name); setDraft(c.name); };
  const commitRename = async (c) => {
    if (renameName !== c.name) return;
    const chk = checkRename(draft, c.name, all);
    setRenameName("");
    if (chk.unchanged) return;
    if (!chk.ok) { say(chk.error, true); return; }
    setBusy(true);
    const d = await manageCollections(csrf, { action: "rename", name: c.name, new_name: chk.name });
    setBusy(false);
    if (d.error) { say(d.error, true); return; }
    say("Renamed to “" + d.name + "”.");
    await reload();
    onChanged({ renamed: { from: c.name, to: d.name } });
  };

  const merge = async () => {
    if (!plan.can || busy) return;
    setBusy(true);
    const d = await manageCollections(csrf, { action: "merge", names: plan.hand });
    setBusy(false);
    if (d.error) { say(d.error, true); return; }
    setTicked([]);
    setMerging(false);
    say("Merged " + (d.merged.length + 1) + " collections into “" + d.target + "”: " + pics(d.pictures) + ", none lost.");
    await reload();
    onChanged({ merged: { target: d.target, others: d.merged } });
  };

  const delRow = all.find((c) => c.name === delName);
  const del = async () => {
    if (!delRow || busy) return;
    setBusy(true);
    const d = await manageCollections(csrf, { action: "delete", name: delRow.name });
    setBusy(false);
    setDelName("");
    if (d.error) { say(d.error, true); return; }
    say("Deleted “" + delRow.name + "”. Its " + pics(d.kept) + (d.kept === 1 ? " stays" : " stay") + " in your library.");
    await reload();
    onChanged({ deleted: delRow.name });
  };

  const toggleMerging = () => { setMerging((m) => !m); setTicked([]); setOpenName(""); setDelName(""); say(""); };

  return (
    <div className="mgcm">
      <div className="mgcm-bar">
        <span className="mgcm-cap">COLLECTIONS</span>
        <span className="mgcm-fill" />
        {all.length > 1 ? (
          <button type="button" className={"mgcm-modebtn" + (merging ? " on" : "")} onClick={toggleMerging}>
            {merging ? "Done" : "Merge…"}
          </button>
        ) : null}
      </div>

      <div className={"mgcm-msg" + (msg.err ? " err" : "")} role="status">
        {msg.text || (merging ? plan.note : "Tap to open · swipe a row for Rename and Delete.")}
      </div>

      {rows && rows.length === 0 ? (
        <div className="mgcu-empty">No collections yet. Select pictures and add them to a collection, or save a search as a smart collection.</div>
      ) : null}

      <div className="mgcm-list">
        {all.map((c) => (
          <Row key={c.name} c={c} open={openName === c.name} merging={merging}
            ticked={ticked.indexOf(c.name) >= 0} first={ticked[0] === c.name} plan={plan}
            renaming={renameName === c.name} draft={draft} setDraft={setDraft}
            onOpenRow={(row) => onOpenCollection(row.name)} setOpenName={setOpenName}
            onTick={tick} onStartRename={startRename} onCommitRename={commitRename}
            onDelete={(row) => { setOpenName(""); setDelName(row.name); }}
            renderRowSlot={renderRowSlot} />
        ))}
      </div>

      {delRow ? (
        <div className="mgcu-confirm mgcm-confirm" role="alertdialog" aria-label={"Delete " + delRow.name}>
          <div className="mgcu-confirm-t">Delete {"“"}{delRow.name}{"”"}?</div>
          <div className="mgcu-confirm-b">{deleteBody(delRow)}</div>
          <div className="mgcu-confirm-go">
            <button type="button" className="mgcu-btn danger" disabled={busy} onClick={del}>Delete collection</button>
            <button type="button" className="mgcu-btn" onClick={() => setDelName("")}>Cancel</button>
          </div>
        </div>
      ) : null}

      {merging ? (
        <div className="mgcm-mergebar">
          <button type="button" className={"mgcu-btn" + (plan.can ? " primary" : "")} disabled={!plan.can || busy} onClick={merge}>{plan.label}</button>
        </div>
      ) : null}
    </div>
  );
}
