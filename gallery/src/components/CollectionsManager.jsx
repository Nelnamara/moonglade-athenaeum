import React, { useCallback, useEffect, useState } from "react";
import { fetchCollectionDetail, manageCollections } from "../api.js";
import { checkRename, deleteBody, mergePlan, tickTitle } from "../curation/curationCore.js";
import "../styles/curation.css";

/* THE COLLECTIONS MANAGER (Session N, N2). Rename inline (trimmed, unique), merge two or more
   hand-picked collections into the first one ticked (pictures de-duplicated, the others
   removed), delete with a confirm that says how many pictures stay. Smart collections rename
   and delete like any other but cannot merge: their tick box is dashed and says why.

   NOTHING HERE DELETES A PICTURE. A collection is a label on pictures the library already
   holds (or, for a smart one, a saved search); deleting or merging rewrites labels and the
   server never touches a row or a file for it. The confirm says so in numbers.

   SESSION P HOSTS ITS MANUAL ORDER HERE (P6). `renderRowSlot(collection)` is called for every
   hand-picked row and whatever it returns is drawn in .mgcu-mslot between the count and
   Delete. It is empty today and takes no room while it is; the Loom's session fills it
   without touching this file's rename / merge / delete.

   `onChanged` tells the shell what moved ({renamed}, {merged}, {deleted}) so the open
   collection follows its rename and the lists refresh. */
export default function CollectionsManager({ csrf, onClose, onChanged, renderRowSlot }) {
  const [rows, setRows] = useState(null);
  const [ticked, setTicked] = useState([]);       // names, in the order they were ticked
  const [drafts, setDrafts] = useState({});       // name -> what is typed in its field
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
    if (c.kind === "smart") return;
    setTicked((t) => (t.indexOf(c.name) >= 0 ? t.filter((n) => n !== c.name) : t.concat(c.name)));
  };

  const rename = async (c) => {
    const typed = drafts[c.name];
    if (typed === undefined) return;
    const chk = checkRename(typed, c.name, all);
    setDrafts((d) => { const n = { ...d }; delete n[c.name]; return n; });
    if (chk.unchanged) return;
    if (!chk.ok) { say(chk.error, true); return; }
    setBusy(true);
    const d = await manageCollections(csrf, { action: "rename", name: c.name, new_name: chk.name });
    setBusy(false);
    if (d.error) { say(d.error, true); return; }
    setTicked((t) => t.map((n) => (n === c.name ? d.name : n)));
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
    setTicked((t) => t.filter((n) => n !== delRow.name));
    say("Deleted “" + delRow.name + "”. Its " + pics(d.kept) + (d.kept === 1 ? " stays" : " stay") + " in your library.");
    await reload();
    onChanged({ deleted: delRow.name });
  };

  return (
    <>
      <div className="mgcu-scrim" onMouseDown={onClose} />
      <div className="mgcu-mgr" role="dialog" aria-modal="true" aria-label="Manage collections">
        <div className="mgcu-mgr-hd">
          <div className="mgcu-mgr-title">Manage collections</div>
          <button type="button" className="mgcu-x" onClick={onClose} aria-label="Close">{"✕"}</button>
        </div>

        {rows && rows.length === 0 ? (
          <div className="mgcu-empty">No collections yet. Select pictures and use {"“"}+ Add to collection{"”"}, or save a search as a smart collection.</div>
        ) : null}

        {all.map((c) => {
          const on = ticked.indexOf(c.name) >= 0;
          const first = ticked[0] === c.name;
          const smart = c.kind === "smart";
          return (
            <div key={c.name} className="mgcu-mrow">
              <button type="button" className={"mgcu-box" + (on ? " on" : "") + (smart ? " smart" : "")}
                aria-pressed={on} aria-disabled={smart} title={tickTitle(c)} onClick={() => tick(c)}>
                {on ? "✓" : ""}
              </button>
              <span className="mgcu-cover" style={c.cover ? { backgroundImage: "url(/thumbs/" + encodeURIComponent(c.cover) + ".jpg)" } : undefined} />
              <input className="mgcu-mname" aria-label={"Name of " + c.name}
                value={drafts[c.name] !== undefined ? drafts[c.name] : c.name}
                onChange={(e) => setDrafts((d) => ({ ...d, [c.name]: e.target.value }))}
                onBlur={() => rename(c)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); } }} />
              <span className="mgcu-mmeta">
                {(smart ? "⟳ smart · " : "") + c.count + (first && plan.can ? " · merge target" : "")}
              </span>
              <span className="mgcu-mslot" data-slot={smart ? undefined : "collection-order"}>
                {!smart && renderRowSlot ? renderRowSlot(c) : null}
              </span>
              <button type="button" className="mgcu-mdel" title="Delete collection" onClick={() => setDelName(c.name)}>Delete</button>
            </div>
          );
        })}

        <div className="mgcu-mgr-ft">
          <button type="button" className={"mgcu-btn" + (plan.can ? " primary" : "")} disabled={!plan.can || busy} onClick={merge}>{plan.label}</button>
          <div className={"mgcu-mgr-note" + (msg.err ? " err" : "")} role="status">{msg.text || plan.note}</div>
        </div>

        {delRow ? (
          <div className="mgcu-confirm" role="alertdialog" aria-label={"Delete " + delRow.name}>
            <div className="mgcu-confirm-t">Delete {"“"}{delRow.name}{"”"}?</div>
            <div className="mgcu-confirm-b">{deleteBody(delRow)}</div>
            <div className="mgcu-confirm-go">
              <button type="button" className="mgcu-btn danger" disabled={busy} onClick={del}>Delete collection</button>
              <button type="button" className="mgcu-btn" onClick={() => setDelName("")}>Cancel</button>
            </div>
          </div>
        ) : null}
      </div>
    </>
  );
}
