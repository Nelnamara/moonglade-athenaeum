import React, { useEffect, useRef, useState } from "react";
import { deletePreview } from "../api.js";

/* The bulk Actions menu -- the destructive tier, ported with the classic's confirm
   flows intact: plain confirms verbatim, and "Delete from PixAI" keeps the full
   blast-radius preview (batch siblings shown and counted) plus the typed DELETE
   gate. Send to Video stays parked until the Generate drawer ports. */

function plural(v, one, many) { return v + " " + (v === 1 ? one : many); }

function CloudDeleteModal({ data, ids, onCancel, onProceed }) {
  const t = data.totals;
  let head;
  if (t.tasks === 0) {
    head = (
      <><b>{plural(t.media, "file", "files")}</b> will be removed from your backup.
      None of them is on PixAI (local imports), so nothing is deleted from your account.</>
    );
  } else {
    head = (
      <><b>{plural(t.media, "file", "files")}</b> across <b>{plural(t.tasks, "task", "tasks")}</b>{" "}
      will be deleted from your PixAI account <b>and</b> from your backup.
      {t.unselected > 0 && (
        <> You picked {plural(t.selected, "file", "files")}; the other{" "}
        {t.unselected === 1 ? "1 comes with its batch." : t.unselected + " come with their batches."}</>
      )}
      {t.local_only > 0 && (
        t.local_only === 1
          ? <> One is a local import with no PixAI task — that one only leaves your backup.</>
          : <> {t.local_only} are local imports with no PixAI task — those only leave your backup.</>
      )}</>
    );
  }
  const strip = (media) => (
    <div className="cd-strip">
      {media.map((m) => (
        <div
          key={m.media_id}
          className={"cd-thumb" + (m.selected ? " on" : "")}
          title={m.media_id + (m.selected ? " (you selected this)" : " (comes with the batch)")}
        >
          {m.thumb
            ? <img src={"/thumbs/" + encodeURIComponent(m.thumb) + ".jpg"} alt="" loading="lazy" />
            : <span className="cd-noimg">{m.media_id}</span>}
          {m.is_video ? <span className="cd-vid">▶</span> : null}
        </div>
      ))}
    </div>
  );
  return (
    <div className="lb" role="dialog" aria-modal="true" onClick={onCancel}>
      <div className="cd-inner" onClick={(e) => e.stopPropagation()}>
        <div className="cd-head">Delete from PixAI — the whole blast radius</div>
        <p className="cd-summary">{head}</p>
        <div className="cd-tasks">
          {data.tasks.map((tk) => (
            <div className="cd-task" key={tk.task_id}>
              <div className="cd-tlbl">whole batch
                <span className="cd-tid">task {tk.task_id}</span>
                <span>{plural(tk.media.length, "file", "files")}</span>
              </div>
              {strip(tk.media)}
            </div>
          ))}
          {data.local_only.length > 0 && (
            <div className="cd-task">
              <div className="cd-tlbl">no PixAI task · removed locally only
                <span>{plural(t.local_only, "file", "files")}</span>
              </div>
              {strip(data.local_only)}
            </div>
          )}
          {data.truncated && (
            <div className="cd-more">Not every batch is shown above — the counts in the
            first line cover the whole selection.</div>
          )}
        </div>
        <div className="flyft">
          <button className="card" onClick={onCancel}>Cancel</button>
          <span className="sp" />
          <button className="card danger" onClick={() => onProceed(ids)}>Continue…</button>
        </div>
      </div>
    </div>
  );
}

export default function ActionsMenu({
  ids, shelf, isTrueLocal,
  onAddCollection, onRemoveCollection, onSendCast, onPrintSheet,
  onDownloadZip, onReplacePrompt, onDeleteLocal, onDeleteCloud,
}) {
  const count = ids.length;
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState(null); // {data, ids}
  const ref = useRef(null);

  useEffect(() => {
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("pointerdown", onDoc);
    return () => document.removeEventListener("pointerdown", onDoc);
  }, []);

  const item = (label, fn, opts = {}) => (
    <button
      className={"am-item" + (opts.danger ? " danger" : "")}
      disabled={opts.disabled}
      title={opts.title}
      onClick={() => { setOpen(false); fn(); }}
    >
      {label}
    </button>
  );

  const askCloud = async () => {
    setOpen(false);
    const data = await deletePreview(ids);
    if (data) { setPreview({ data, ids }); return; }
    // Fail-soft, verbatim from the classic: an unreachable preview falls back to
    // the prose-only confirm rather than a dead click or a silent skip.
    if (window.confirm(
      "Delete " + ids.length + " selected file(s) from your PixAI account AND locally?\n\n" +
      "The preview of exactly what that takes could not be loaded, so: this deletes the whole " +
      "TASK behind each selection (every image in the batch, including ones you did not " +
      "select), from the cloud AND your backup. It is IRREVERSIBLE."
    )) onDeleteCloud(ids);
  };

  return (
    <span className="am-wrap" ref={ref}>
      <button
        className={"card" + (open ? " on" : "")}
        disabled={count === 0}
        title={count === 0 ? "Select images first — the count rides this button" : "Bulk actions for the selection"}
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        Actions{count > 0 ? " " + count : ""} ▾
      </button>
      {open && (
        <div className="am-menu">
          {item("＋ Add to collection", onAddCollection)}
          {shelf
            ? item("− Remove from “" + shelf + "”", () => onRemoveCollection(shelf),
                { title: "Take the selected items out of this collection (a label only — no files are deleted)" })
            : null}
          {item("▶ Send to Video", () => {},
            { disabled: true, title: "Ports with the Generate drawer" })}
          {item("▰ Send to The Loom (cast)", onSendCast)}
          {item("🖨 Print sheet", onPrintSheet)}
          {item("⬇ Download ZIP", onDownloadZip)}
          {item("Find / replace in prompts", onReplacePrompt)}
          <div className="am-div" />
          {item("Delete locally", onDeleteLocal,
            { danger: true, title: "Remove from this local catalog only (keeps the cloud task)" })}
          {isTrueLocal
            ? item("Delete from PixAI", askCloud,
                { danger: true, title: "Delete the whole TASK from your PixAI account AND locally (irreversible)" })
            : null}
        </div>
      )}
      {preview && (
        <CloudDeleteModal
          data={preview.data}
          ids={preview.ids}
          onCancel={() => setPreview(null)}
          onProceed={(ids) => { setPreview(null); onDeleteCloud(ids); }}
        />
      )}
    </span>
  );
}
