import React, { useCallback, useEffect, useRef, useState, useLayoutEffect } from "react";
import { createPortal } from "react-dom";
import { apiPost, deletePreview, downloadZipForm, resolveVideoIds } from "../api.js";
import "../styles/librarybar.css";

/* The bulk Actions menu, refit per the Frontend Gallery DC (drift §10):

   - The trigger is the DC pill: `Actions (N)` + ▾, disabled STYLING and
     cursor:not-allowed at zero selection — it opens only WITH a selection.
   - The menu renders at PAGE level (portal, fixed at the button's measured
     rect — the banner it sits in is overflow-clipped, so an inline absolute
     menu would be scissored). mgChipsIn .2s in, mglMenuOut .2s + 200ms
     deferred unmount out; a transparent fixed scrim closes it on any outside
     press (swallowing that press, matching the DC); Esc closes it too.
   - Items mirror the DC's 8-item list, DC glyphs and order, the ruby
     destructive pair LAST and separated. The pilot's conditional
     "− Remove from collection" (only inside a collection view) is kept — a
     deliberate extra over the DC's 8.

   The four bulk-mutation flows are now owned HERE, against the JSON routes
   (tests/test_api_bulk_json.py):
     + Add / − Remove collection  →  POST /api/collection  {action, collection, media_ids}
     Find / replace in prompts    →  POST /api/replace-prompts {find, replace, media_ids}
     Delete locally               →  POST /api/delete-local {media_ids}
     Delete from PixAI            →  preview POST /api/delete-preview, then
                                     POST /api/delete-tasks {media_ids}
   Confirm/prompt texts ride along VERBATIM from the classic flows (formerly
   App.jsx's `actions`). "Delete from PixAI" keeps the full blast-radius
   preview (CloudDeleteModal, batch siblings shown and counted) plus the typed
   DELETE gate. After a mutation: clearSelection() when the mount passes it,
   onMutated() when passed, and always an mg-gen-done dispatch — the shell
   already reloads the grid + credits chip on that event.

   Prop contract:
     ids, shelf, isTrueLocal            — as before.
     onSendCast / onPrintSheet /
     onDownloadZip                      — optional; local fallbacks exist so the
                                          component also works standalone.
     onSendVideo                        — optional; absent = the item shows
                                          disabled (the GenerateDock retab owns
                                          the bulk→video prefill contract).
     onMutated, clearSelection          — optional post-mutation hooks.
   Nine props, and every one of them is read. Five more (onAddCollection /
   onRemoveCollection / onReplacePrompt / onDeleteLocal / onDeleteCloud) were Strip's old
   delegation contract, kept "so existing mounts compile" after the JSON flows above replaced
   them; no mount has passed one since, so they are gone (2026-08-23). Both mounts --
   FiltersPanel's LibraryBar and GalleryMobile's actions sheet -- speak this one contract. */

function plural(v, one, many) { return v + " " + (v === 1 ? one : many); }

function toastOk(title, msg) {
  if (window.Toast) window.Toast.show({ kind: "ok", title, msg });
}
function toastErr(title, msg) {
  if (window.Toast) window.Toast.show({ kind: "err", title, msg });
  else window.alert(title + (msg ? "\n" + msg : ""));
}

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
  onSendCast, onPrintSheet, onDownloadZip, onSendVideo,
  onMutated, clearSelection,
}) {
  const count = ids.length;
  const [open, setOpen] = useState(false);
  const [closing, setClosing] = useState(false);
  // bumped on EVERY opening toggle -- the clamp effect keys on this, not `open`,
  // because a fast reopen inside closeMenu()'s 200ms fade window leaves `open`
  // true the whole time (adversarial review, 2026-08-29: keying on [open] skipped
  // the clamp exactly then, re-landing the unclamped rect.bottom+8 guess).
  const [openNonce, setOpenNonce] = useState(0);
  const [pos, setPos] = useState({ x: 22, y: 260 });
  const [preview, setPreview] = useState(null); // {data, ids}
  const btnRef = useRef(null);
  const menuRef = useRef(null);
  const trigRectRef = useRef(null);
  const timer = useRef(null);
  const busyRef = useRef(false);

  const closeMenu = useCallback(() => {
    setClosing(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { setOpen(false); setClosing(false); }, 200);
  }, []);

  const toggle = () => {
    if (count === 0) return; // opens only WITH a selection (DC toggleActions)
    if (open && !closing) { closeMenu(); return; }
    clearTimeout(timer.current);
    const r = btnRef.current ? btnRef.current.getBoundingClientRect() : null;
    trigRectRef.current = r;
    setPos({
      x: r ? Math.max(10, Math.min(r.left, window.innerWidth - 252)) : 22,
      y: r ? r.bottom + 8 : 260,
    });
    setOpen(true);
    setClosing(false);
    setOpenNonce((n) => n + 1);
  };

  // #40: a trigger anchored inside a bottom sheet (mobile Gallery Actions) puts
  // `rect.bottom + 8` low enough that the portalled fixed menu ran past
  // window.innerHeight with no way to scroll it — the tail items (the delete
  // pair, deliberately LAST) were simply unreachable. After the menu mounts,
  // measure its REAL height and keep it on-screen: flip above the trigger when
  // it would overflow the bottom, and as a last resort pin it inside the
  // viewport (the .mgl-menu max-height + overflow-y in librarybar.css
  // guarantees that final clamp always fits, scrolling internally).
  useLayoutEffect(() => {
    if (!open || !menuRef.current) return;
    const mh = menuRef.current.offsetHeight;
    const r = trigRectRef.current;
    const below = r ? r.bottom + 8 : pos.y;
    let y = below;
    if (below + mh > window.innerHeight - 10) {
      const above = r ? r.top - 8 - mh : window.innerHeight - mh - 10;
      y = above >= 10 ? above : Math.max(10, window.innerHeight - mh - 10);
    }
    if (y !== pos.y) setPos((p) => ({ ...p, y }));
  }, [open, openNonce]);   // eslint-disable-line react-hooks/exhaustive-deps -- re-measure on every opening toggle

  // Esc closes the menu first (capture beats the drawer's own Esc ladder)
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      closeMenu();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, closeMenu]);
  useEffect(() => () => clearTimeout(timer.current), []);

  /* what the classic afterMutation did, minus the App state we can't reach:
     the grid + credits chip reload on mg-gen-done (App's existing listener);
     selection/collections need the mount to pass clearSelection/onMutated. */
  const afterMutation = () => {
    if (clearSelection) clearSelection();
    if (onMutated) onMutated();
    window.dispatchEvent(new CustomEvent("mg-gen-done"));
  };

  // one flow at a time — a double-click must not double-POST
  const run = (fn) => async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    try { await fn(); } finally { busyRef.current = false; }
  };

  /* ---- the four JSON-route flows (confirm texts verbatim from the classic) ---- */

  const addCollection = run(async () => {
    const name = window.prompt(
      "Add " + count + " image(s) to which collection? (a name; files are NOT moved)");
    if (name === null || !name.trim()) return;
    const d = await apiPost("/api/collection",
      { action: "add", collection: name.trim(), media_ids: ids });
    if (d.error) { toastErr("Not added", d.error); return; }
    toastOk("Added to “" + name.trim() + "”", plural(d.count || 0, "item", "items") + " newly labeled");
    afterMutation();
  });

  const removeCollection = run(async () => {
    if (!shelf) return;
    if (!window.confirm(
      "Remove " + count + " item(s) from the collection “" + shelf + "”?\n\n" +
      "Only the collection label is removed — no files are deleted and nothing leaves your PixAI account.")) return;
    const d = await apiPost("/api/collection",
      { action: "remove", collection: shelf, media_ids: ids });
    if (d.error) { toastErr("Not removed", d.error); return; }
    toastOk("Removed from “" + shelf + "”", plural(d.count || 0, "item", "items") + " unlabeled");
    afterMutation();
  });

  const replacePrompt = run(async () => {
    const find = window.prompt(
      "Find this text in the prompts of " + count + " selected image(s):");
    if (find === null || find === "") return;
    const repl = window.prompt('Replace "' + find + '" with: (leave blank to delete it)');
    if (repl === null) return;
    if (!window.confirm('Replace "' + find + '" with "' + repl + '" across ' +
      count + " prompt(s)? This edits catalog.db.")) return;
    const d = await apiPost("/api/replace-prompts",
      { find, replace: repl, media_ids: ids });
    if (d.error) { toastErr("Nothing replaced", d.error); return; }
    toastOk("Prompts updated", plural(d.changed || 0, "prompt", "prompts") + " actually changed");
    afterMutation();
  });

  const deleteLocal = run(async () => {
    if (!window.confirm(
      "Remove " + count + " image" + (count !== 1 ? "s" : "") +
      " from the local catalog? Files move to the _deleted/ folder (recoverable); the cloud task is untouched.")) return;
    const d = await apiPost("/api/delete-local", { media_ids: ids });
    if (d.error) { toastErr("Not removed", d.error); return; }
    if (d.failed) {
      // the page route's wording, minus the redirect banner
      toastErr("Some files are locked",
        d.failed + " of " + count + " could not be moved to the trash folder and were left alone");
    } else {
      toastOk("Removed locally",
        plural(d.count || 0, "file", "files") + " moved to _deleted/ (recoverable)");
    }
    if (d.count) afterMutation();
  });

  const deleteCloud = async (idsArg) => {
    // The typed gate, unchanged: the preview makes the consequence visible,
    // it does not replace the guard.
    const typed = window.prompt("This permanently deletes from PixAI. Type DELETE to confirm:");
    if (typed !== "DELETE") { window.alert("Cancelled."); return; }
    const d = await apiPost("/api/delete-tasks", { media_ids: idsArg });
    if (d.error) { toastErr("Not deleted", d.error); return; }
    toastOk("Deleting from PixAI",
      plural(d.count || 0, "file", "files") + " across " + plural(d.tasks || 0, "task", "tasks") +
      (d.local_only ? " (+" + d.local_only + " local-only)" : "") +
      " — the Activity card tracks it");
    afterMutation();
  };

  const askCloud = run(async () => {
    const data = await deletePreview(ids);
    if (data) { setPreview({ data, ids }); return; }
    // Fail-soft, verbatim from the classic: an unreachable preview falls back to
    // the prose-only confirm rather than a dead click or a silent skip.
    if (window.confirm(
      "Delete " + ids.length + " selected file(s) from your PixAI account AND locally?\n\n" +
      "The preview of exactly what that takes could not be loaded, so: this deletes the whole " +
      "TASK behind each selection (every image in the batch, including ones you did not " +
      "select), from the cloud AND your backup. It is IRREVERSIBLE."
    )) await deleteCloud(ids);
  });

  /* ---- non-destructive items: props when given, local fallbacks otherwise ---- */

  const printSheet = onPrintSheet ||
    (() => window.open("/contact-sheet?ids=" + encodeURIComponent(ids.join(",")), "_blank"));
  const downloadZip = onDownloadZip || (() => downloadZipForm(ids));
  const sendCast = onSendCast || (async () => {
    // cast is images — videos are filtered out, unknown ids resolved like the classic
    const vids = await resolveVideoIds(ids, new Map());
    const keep = ids.filter((mid) => !vids.has(mid));
    if (!keep.length) return;
    if (clearSelection) clearSelection(); // the selection is consumed into the cast
    window.location.href = "/loom?cast=" + encodeURIComponent(keep.join(","));
  });

  const item = (label, fn, opts = {}) => (
    <button
      type="button"
      role="menuitem"
      className={"mgl-item" + (opts.danger ? " danger" : "") + (opts.sep ? " sep" : "")
        + (opts.disabled ? " off" : "")}
      title={opts.title}
      onClick={() => { if (opts.disabled || !fn) return; closeMenu(); fn(); }}
    >
      {label}
    </button>
  );

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        className={"mgl-actbtn" + (count > 0 ? " has" : "")}
        aria-haspopup="menu"
        aria-expanded={open && !closing}
        aria-disabled={count === 0}
        title={count === 0
          ? "Select images first — the count rides this button"
          : "Bulk actions for the selection"}
        onClick={toggle}
      >
        <span>Actions ({count})</span>
        <span className="mgl-caret8">▾</span>
      </button>

      {open && createPortal(
        <>
          {/* transparent click-catcher: any outside press closes the menu and
              is swallowed, exactly the DC's scrim behavior */}
          <div className="mgl-scrim" onMouseDown={closeMenu} aria-hidden="true" />
          <div
            ref={menuRef}
            className={"mgl-menu" + (closing ? " closing" : "")}
            role="menu"
            style={{ left: pos.x, top: pos.y }}
          >
            {item("+ Add to collection", addCollection)}
            {shelf
              ? item("− Remove from “" + shelf + "”", removeCollection,
                  { title: "Take the selected items out of this collection (a label only — no files are deleted)" })
              : null}
            {item("▶ Send to Video", onSendVideo ? () => onSendVideo(ids) : null,
              { disabled: !onSendVideo,
                title: onSendVideo ? "Load the selection into the Video tab"
                  : "Ports with the GenerateDock retab — the shared drawer has no bulk video prefill yet" })}
            {item("▮ Send to The Loom (cast)", sendCast)}
            {item("▤ Print sheet", printSheet)}
            {item("⬇ Download ZIP", downloadZip)}
            {item("Find / replace in prompts", replacePrompt)}
            {item("Delete locally", deleteLocal,
              { danger: true, sep: true,
                title: "Remove from this local catalog only (keeps the cloud task)" })}
            {isTrueLocal
              ? item("Delete from PixAI", askCloud,
                  { danger: true,
                    title: "Delete the whole TASK from your PixAI account AND locally (irreversible)" })
              : null}
          </div>
        </>,
        document.body
      )}

      {preview && createPortal(
        <CloudDeleteModal
          data={preview.data}
          ids={preview.ids}
          onCancel={() => setPreview(null)}
          onProceed={(pids) => { setPreview(null); deleteCloud(pids); }}
        />,
        document.body
      )}
    </>
  );
}
