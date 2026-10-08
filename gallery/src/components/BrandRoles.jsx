import React, { useEffect, useRef, useState } from "react";
import GalleryPicker from "./GalleryPicker.jsx";
import useRoleEditor from "./brandroles/useRoleEditor.js";
import { RestoreAsk, RoleArt, RoleLoud, RolePair, RolePreview, RoleTicks } from "./brandroles/RoleParts.jsx";
import { imageUrl, rowSub, specLine, unreadableNote } from "../lib/brandRolesCore.js";
import "../styles/brand-roles.css";

/* ✦ Branding -> Roles, on the desktop (Branding Roles Handoff, Session X; hidden: the whole
   Branding tab is unlock-gated and shows no hint before it, and this section lives inside it).

   Four rows in a fixed order (the server's, by where you meet each one), no group headers: the
   login companion, the job tracker's mascots, the reward icons, the power poses. A row shows the
   current art of every image it owns at 34 px -- an overridden image wears a lavender outline, and
   a single-image role shows the pack's default (28 px, dimmed) -> yours. Change expands the row in
   place (one open at a time; Esc folds it): the spec line, a drop zone that takes a file or
   opens From disk / From the gallery and then ticks each rule live, Use this (enabled only when
   every rule passes), the loud refusal when one does not, and the role in its real home.

   The checks run here first (lib/brandRolesCore.js) so nothing is uploaded that the server
   would refuse; the server measures again and decides (moonglade_gallery.py,
   branding_role_upload). The roles come from summary.branding.roles; every write re-reads the
   summary through onSaved. */

function RoleRow({ role, csrf, open, onOpen, onClose, onSaved }) {
  const ed = useRoleEditor({ role, csrf, onSaved });
  const [picking, setPicking] = useState(false);
  const [asking, setAsking] = useState(null);       // the image key the one-time ask is about
  const [leaving, setLeaving] = useState(false);    // the editor's .35 s exit
  const fileRef = useRef(null);
  const [over, setOver] = useState(false);

  // Esc folds the open row; it also drops a half-made candidate, which belongs to that row.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      if (picking) return;                           // the picker owns its own Escape
      e.stopPropagation();
      fold();
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  });   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { if (!open) { ed.drop(); setAsking(null); } }, [open]);   // eslint-disable-line react-hooks/exhaustive-deps

  const fold = () => {
    setLeaving(true); setAsking(null);
    setTimeout(() => { setLeaving(false); ed.drop(); onClose(); }, 350);
  };

  const img = role.images.find((i) => i.key === ed.key) || role.images[0];
  const note = unreadableNote(role);
  const single = role.images.length === 1;
  const ask = (k) => setAsking(k);
  const useDefault = async () => {
    const k = asking; setAsking(null);
    await ed.restore(k);
  };
  const onDrop = (e) => {
    e.preventDefault(); setOver(false);
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) ed.pickFile(f);
  };
  const candUrl = ed.ok && ed.cand ? ed.cand.url : "";

  return (
    <div className={"mgcp-rl" + (open ? " open" : "")} data-role={role.slot}>
      <div className="mgcp-rl-row">
        {single
          ? <RolePair img={role.images[0]} onAskDefault={() => ask(role.images[0].key)} />
          : role.images.map((i) => (
              <RoleArt key={i.key} src={imageUrl(i)} size={34} yours={i.yours} title={i.label} />
            ))}
        <div className="mgcp-rl-name"><div>{role.name}</div><div>{rowSub(role)}</div></div>
        <button type="button" className="mgcp-rl-ghost" aria-expanded={open}
          onClick={() => (open ? fold() : onOpen())}>Change</button>
      </div>
      {asking && single && (
        <RestoreAsk role={role} img={role.images[0]} busy={ed.busy}
          onKeep={() => setAsking(null)} onUse={useDefault} />
      )}
      {note && <div className="mgcp-rl-note">{note}</div>}

      {open && (
        <div className={"mgcp-rl-editor" + (leaving ? " leaving" : "")}>
          {!single && (
            <div className="mgcp-rl-tabs" role="tablist">
              {role.images.map((i) => (
                <button type="button" key={i.key} role="tab" aria-selected={i.key === ed.key}
                  className={"mgcp-rl-tab" + (i.key === ed.key ? " on" : "")} onClick={() => ed.select(i.key)}>
                  {i.label}
                </button>
              ))}
            </div>
          )}
          {!single && (
            <div className="mgcp-rl-imgrow">
              <RolePair img={img} onAskDefault={() => ask(img.key)} />
              <span className="mgcp-rl-imgname">{img.label}</span>
              <span className="mgcp-rl-imgstate">{img.yours ? "yours" : "default"}</span>
            </div>
          )}
          {asking && !single && (
            <RestoreAsk role={role} img={role.images.find((i) => i.key === asking) || img} busy={ed.busy}
              onKeep={() => setAsking(null)} onUse={useDefault} />
          )}
          <div className="mgcp-rl-spec">{specLine(img.spec)}</div>
          <div className={"mgcp-rl-drop" + (over ? " over" : "")}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)} onDrop={onDrop}
            onClick={() => fileRef.current && fileRef.current.click()}>
            <div>{ed.measuring ? "Checking…" : "Drop an image here, or choose…"}</div>
            {ed.cand && !ed.measuring && !ed.cand.unreadable && <RoleTicks list={ed.cand.ticks} />}
          </div>
          <input ref={fileRef} type="file" hidden accept="image/png,image/webp,image/jpeg,image/*"
            onChange={(e) => { const f = e.target.files[0]; e.target.value = ""; ed.pickFile(f); }} />
          <div className="mgcp-rl-btns">
            <button type="button" className="mgcp-rl-ghost" disabled={ed.busy}
              onClick={() => fileRef.current && fileRef.current.click()}>⬆ From disk</button>
            <button type="button" className="mgcp-rl-ghost" disabled={ed.busy}
              onClick={() => setPicking(true)}>🖼 From the gallery…</button>
            <span className="mgcp-rl-spacer" />
            <button type="button" className="mgcp-rl-primary" disabled={!ed.ok || ed.busy}
              onClick={async () => { if (await ed.useThis()) fold(); }}>Use this</button>
          </div>
          <RoleLoud>{ed.refusal}</RoleLoud>
          <RolePreview role={role} candKey={ed.key} candUrl={candUrl} />
        </div>
      )}
      {picking && <GalleryPicker defaultType="image"
        onPick={(m) => { setPicking(false); ed.pickGallery(m.media_id); }}
        onClose={() => setPicking(false)} />}
    </div>
  );
}

export default function RolesSection({ summary, onSaved }) {
  const roles = (summary.branding && summary.branding.roles) || [];
  const [openSlot, setOpenSlot] = useState("");
  return (
    <div className="mgcp-brandsec mgcp-roles">
      <h3 className="mgcp-brandh">Roles</h3>
      <div className="mgcp-rl-lede">The app's own mascots and icons, one row each. Change one and every
        screen that shows it wears yours; go back to the default whenever you like.</div>
      {roles.map((role) => (
        <RoleRow key={role.slot} role={role} csrf={summary.csrf} onSaved={onSaved}
          open={openSlot === role.slot}
          onOpen={() => setOpenSlot(role.slot)}
          /* A row closes only ITSELF. Its close lands at the end of its .35 s fold, and a
             Change pressed on another row inside that exit has opened that row by then: an
             unconditional "" shut the new editor under the user's hand. */
          onClose={() => setOpenSlot((cur) => (cur === role.slot ? "" : cur))} />
      ))}
    </div>
  );
}
