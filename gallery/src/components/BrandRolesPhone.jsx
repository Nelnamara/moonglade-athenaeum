import React, { useRef, useState } from "react";
import MobileScreen from "./MobileScreen.jsx";
import useLayerHistory from "../hooks/useLayerHistory.js";
import useRoleEditor from "./brandroles/useRoleEditor.js";
import { RestoreAsk, RoleArt, RoleLoud, RolePair, RolePreview, RoleTicks } from "./brandroles/RoleParts.jsx";
import { imageUrl, phoneState, specLine, unreadableNote } from "../lib/brandRolesCore.js";
import "../styles/brand-roles.css";

/* ✦ Branding -> Roles, on the phone (Branding Roles Handoff, X5a; hidden with the rest of the
   Branding tab). A "Roles" group on the phone's Branding screen: four 52 px rows in the same order
   as the desktop's, each showing its first image at 28 px, the name, "yours" / "default" /
   "N of M yours" and a chevron. A row pushes the role's own screen (MobileScreen.jsx):
   the pack's default -> yours (44 -> 64 px), the gold spec line, the live checks after a pick, the
   loud refusal, the role in its home, and exactly two 44 px buttons, Choose photo and Use default
   (with the same one-time ask). The system photo picker is the only source here; the file is measured
   on the device first, with the desktop's rules and words. A pick that passes every check uploads at
   once and the screen shows default -> yours; one that fails shows the live ticks and the loud
   refusal and uploads nothing. There is no Use this on the phone (the desktop keeps its drawn one). */

function RoleScreen({ role, csrf, onSaved }) {
  const ed = useRoleEditor({ role, csrf, onSaved });
  const [asking, setAsking] = useState(false);
  const fileRef = useRef(null);
  const single = role.images.length === 1;
  const img = role.images.find((i) => i.key === ed.key) || role.images[0];
  const candUrl = ed.ok && ed.cand ? ed.cand.url : "";
  const note = unreadableNote(role);
  return (
    <div className="mgcp-rlm-screen">
      {!single && (
        <div className="mgcp-rlm-seg" role="tablist">
          {role.images.map((i) => (
            <button type="button" key={i.key} role="tab" aria-selected={i.key === ed.key}
              className={"mgcp-rl-tab" + (i.key === ed.key ? " on" : "")}
              onClick={() => { setAsking(false); ed.select(i.key); }}>{i.label}</button>
          ))}
        </div>
      )}
      <div className="mgcp-rlm-pair"><RolePair img={img} big /></div>
      {note && <div className="mgcp-rl-note">{note}</div>}
      <div className="mgcp-rl-spec">{specLine(role.spec, { phone: true })}</div>
      {(ed.measuring || ed.busy) && <div className="mgcp-rlm-checks">{ed.busy ? "Saving…" : "Checking…"}</div>}
      {ed.cand && !ed.measuring && !ed.cand.unreadable && (
        <div className="mgcp-rlm-checks"><RoleTicks list={ed.cand.ticks} /></div>
      )}
      <RoleLoud>{ed.refusal}</RoleLoud>
      <RolePreview role={role} candKey={ed.key} candUrl={candUrl} />
      {asking && (
        <RestoreAsk role={role} img={img} busy={ed.busy} big
          onKeep={() => setAsking(false)}
          onUse={async () => { setAsking(false); await ed.restore(img.key); }} />
      )}
      <input ref={fileRef} type="file" hidden accept="image/*"
        onChange={(e) => { const f = e.target.files[0]; e.target.value = ""; ed.pickFile(f, { commit: true }); }} />
      <div className="mgcp-rlm-btns">
        <button type="button" className="mgcp-rl-ghost" disabled={ed.busy}
          onClick={() => fileRef.current && fileRef.current.click()}>Choose photo</button>
        <button type="button" className="mgcp-rl-ghost" disabled={ed.busy || !img.yours}
          onClick={() => setAsking(true)}>Use default</button>
      </div>
    </div>
  );
}

export default function RolesPhone({ summary, onSaved }) {
  const roles = (summary.branding && summary.branding.roles) || [];
  const [openSlot, setOpenSlot] = useState("");
  const [closing, setClosing] = useState(false);
  const close = () => {
    setClosing(true);
    setTimeout(() => { setOpenSlot(""); setClosing(false); }, 220);
  };
  useLayerHistory(!!openSlot, close);
  const role = roles.find((r) => r.slot === openSlot) || null;
  return (
    <div className="mgcp-rlm-group">
      <div className="mgcp-rlm-lab">ROLES</div>
      {roles.map((r) => (
        <button type="button" key={r.slot} className="mgcp-rlm-row" onClick={() => setOpenSlot(r.slot)}>
          <RoleArt src={imageUrl(r.images[0])} size={28} yours={r.images[0].yours} title={r.images[0].label} />
          <div className="mgcp-rl-name"><div>{r.name}</div><div>{phoneState(r)}</div></div>
          <span className="mgcp-rlm-chev" aria-hidden="true">›</span>
        </button>
      ))}
      {role && (
        <MobileScreen open closing={closing} onClose={close} title={role.name}>
          <RoleScreen key={role.slot} role={role} csrf={summary.csrf} onSaved={onSaved} />
        </MobileScreen>
      )}
    </div>
  );
}
