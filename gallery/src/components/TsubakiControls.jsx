import React, { useState } from "react";
import {
  CONFIRM_BODY, CREATIVITY, RATIOS, autoActive, confirmTitle, contextMax, contextModel, creativityName,
  effectiveCreativity, effectiveTier, heldItems, needsSwitchConfirm, onContextSide, profileExtra, profileLocked,
  profilePicked, profileRows, ratioAspect, ratioIndexOf, ratioLabel, sizeTiers, tierDims,
  tierLocked, tierMembersOnly,
} from "../gen/tsubakiCore.js";
import { UNLIMITED_PRO, landscapeOf, laneRefusesFrame, sizeInfo, unlimitedOffered } from "../gen/genCore.js";
import "../styles/tsubaki.css";

/* The Session H controls the desktop dock (GenerateDrawer.jsx) and the phone Create tab
   (CreateMobile.jsx) share -- pixel source: moonglade-internal/design/handoff-2026-09-04/
   Tsubaki3 Generate Handoff.dc.html, frames A (dock), E (phone) and G (T1a). Every rule is
   gen/tsubakiCore.js's; these only draw it. `phone` switches to the Create tab's 44 px
   targets and 48 px tier chips. Each reads and writes useGenerate's own `s` / `set` -- no
   state of its own except a hover or a tapped notice. */

const fmt = (n) => Number(n).toLocaleString();

/* ---- T1a: Pro / Ultra rows under the model row --------------------------------------------- */
export function ProfileRows({ s, set, phone }) {
  const rows = profileRows(s.model);
  const [notice, setNotice] = useState("");
  if (!rows) return null;
  const lanePinned = !!s.unlimited && !onContextSide(s);
  return (
    <div className={"mgts-profiles" + (phone ? " phone" : "")}>
      <div className="mgts-profrows" role="radiogroup" aria-label="Profile">
        {rows.map((r) => {
          const on = profilePicked(r, rows, s.mode);
          const locked = profileLocked(r, s.member);
          const members = r.flag === "membershipOnly" || (Number(r.required_tier) || 0) > 0;
          const extra = profileExtra(r, rows);
          const pinned = lanePinned && r.name !== "pro";
          return (
            <button type="button" key={r.name} role="radio" aria-checked={on}
              className={"mgts-profrow" + (on ? " on" : "") + (locked ? " locked" : "")}
              disabled={pinned}
              title={pinned ? UNLIMITED_PRO : locked ? (r.title || r.name) + " is for PixAI members" : r.desc || r.title}
              onClick={() => {
                if (locked) { setNotice(notice === r.name ? "" : r.name); return; }
                setNotice("");
                set({ mode: r.name });
              }}>
              <span className="mgts-profmain">
                <span className="mgts-profname">{r.title || r.name}
                  {extra != null ? <span className={"mgts-profprice" + (members ? " gold" : "")}>{" +" + fmt(extra)}</span> : null}
                </span>
                {r.desc ? <span className="mgts-profdesc">{r.desc}</span> : null}
              </span>
              {locked ? <span className="mgts-memtag">Members</span>
                : on ? <span className="mgts-check" aria-hidden="true">✓</span> : null}
            </button>
          );
        })}
      </div>
      {notice && (
        <div className="mgts-notice inline" role="note">
          <b>{(rows.find((r) => r.name === notice) || {}).title || notice} is for PixAI members.</b>{" "}
          Your account runs {(rows.find((r) => r.flag === "default") || rows[0]).title || "the default profile"} on this model (a live read of your membership).
        </div>
      )}
    </div>
  );
}

/* ---- decision 1: the LoRAs | Context images switch ---------------------------------------- */
export function InputsSwitch({ s, set, onAskConfirm, phone }) {
  if (!contextModel(s.model)) return null;
  const ctxOn = onContextSide(s);
  const nl = (s.loras || []).length;
  const nc = (s.ctx || []).length;
  const loraLabel = phone ? "LoRAs" + (nl ? " · " + nl : "")
    : "LoRAs" + (nl ? " · " + nl + (ctxOn ? " held" : "") : "");
  const ctxLabel = phone ? "Context" + (nc ? " · " + nc : "")
    : "Context images" + (ctxOn && nc ? " · " + nc : "");
  const toContext = () => {
    if (ctxOn) return;
    if (needsSwitchConfirm(s)) { onAskConfirm(); return; }
    set({ inputs: "context" });
  };
  return (
    <div className={"mgts-seg" + (phone ? " phone" : "")} role="tablist" aria-label="Inputs">
      <button type="button" role="tab" aria-selected={!ctxOn} className={"mgts-segbtn" + (!ctxOn ? " on" : "")}
        onClick={() => set({ inputs: "loras" })}>{loraLabel}</button>
      <button type="button" role="tab" aria-selected={ctxOn} className={"mgts-segbtn" + (ctxOn ? " on" : "")}
        onClick={toContext}>{ctxLabel}</button>
    </div>
  );
}

/* The in-slab confirm card (desktop; the phone shows the same words in a bottom sheet). */
export function SwitchConfirm({ s, onSwitch, onStay, sheet }) {
  const held = heldItems(s);
  return (
    <div className={"mgts-confirm" + (sheet ? " sheet" : "")} role="alertdialog" aria-label={confirmTitle(held)}>
      <div className="mgts-confirm-t">{confirmTitle(held)}</div>
      <div className="mgts-confirm-b">{CONFIRM_BODY}</div>
      <div className="mgts-confirm-acts">
        <button type="button" className="mgts-btn primary" onClick={onSwitch}>Switch</button>
        <button type="button" className="mgts-btn" onClick={onStay}>Stay on LoRAs</button>
      </div>
    </div>
  );
}

/* The dashed line the Unlimited row becomes on the Context side (only where the lane is
   offered at all). */
export function UnlimitedHeldLine({ s, phone }) {
  if (!onContextSide(s) || !unlimitedOffered(s.model)) return null;
  return (
    <div className={"mgts-unlheld" + (phone ? " phone" : "")}>
      <span className="mgts-unlmark" aria-hidden="true">∞</span>
      <span>Unlimited Mode is for runs without context images</span>
    </div>
  );
}

/* ---- the context slots (decision 1): up to the live max, from history · gallery · upload -- */
export function ContextSlots({ s, onAdd, onRemove, phone }) {
  const ctx = s.ctx || [];
  const max = contextMax(s.model);
  return (
    <>
      <div className={"mgts-slots" + (phone ? " phone" : "")}>
        {ctx.map((c, i) => (
          <div key={c.media_id} className={"mgts-slot filled" + (i === 0 ? " first" : "")}>
            {c.thumb ? <img src={c.thumb} alt="" /> : null}
            <span className="mgts-slotn">{phone ? "@image" + (i + 1) : i + 1}</span>
            <button type="button" className="mgts-slotx" title={"Remove @image" + (i + 1)}
              aria-label={"Remove @image" + (i + 1)} onClick={() => onRemove(i)}>×</button>
          </div>
        ))}
        {ctx.length < max && (
          <button type="button" className="mgts-slot add" onClick={onAdd}
            title="Add a context image from your history, the gallery or an upload">
            {phone ? "+" : <>+ add<br />history · gallery · upload</>}
          </button>
        )}
      </div>
      {!phone && (
        <div className="mgts-slotnote">
          Name them in the prompt as <code>@image1</code>–<code>@image{max}</code> · type @ to pick
        </div>
      )}
    </>
  );
}

/* ---- decision 5: creativity stops -------------------------------------------------------- */
export function CreativityStops({ s, set, phone }) {
  const ctxOn = onContextSide(s);
  const level = effectiveCreativity(s);
  const li = CREATIVITY.findIndex(([k]) => k === level);
  return (
    <div className={"mgts-creat" + (phone ? " phone" : "")}>
      <div className="mgts-creathead">
        <span className="mgts-creatname">{creativityName(level)}</span>
        <span className="mgts-creatsub">creativity</span>
        <span className="sp" />
        {ctxOn ? <span className="mgts-settag">set by context images</span> : null}
      </div>
      <div className="mgts-stops" role="radiogroup" aria-label="Creativity">
        {CREATIVITY.map(([k, name, tip], i) => (
          <button type="button" key={k} role="radio" aria-checked={level === k} aria-label={name}
            className={"mgts-cstop" + (i <= li ? " lit" : "") + (ctxOn && i < 2 ? " locked" : "")}
            disabled={ctxOn} title={ctxOn ? "Set by context images — " + tip : tip}
            onClick={() => set({ creativity: k })} />
        ))}
      </div>
      {!phone && (
        <div className="mgts-stoplabels"><span>off</span><span>low</span><span>medium</span></div>
      )}
    </div>
  );
}

/* ---- decisions 6 + 7: the Frame slab ------------------------------------------------------- */
function Glyph({ w, h, on, dashed }) {
  return <i className={"mgts-glyph" + (on ? " on" : "") + (dashed ? " dashed" : "")} style={{ width: w, height: h }} />;
}

/* The size line: what is sent, in mono. */
export function sizeLine(s) {
  const d = sizeInfo(s);
  const tiers = sizeTiers(s.model);
  if (d.source === "auto") return "✦ Output size " + d.width + " × " + d.height + " · from @image1";
  if (d.source === "custom") return "sends " + d.width + " × " + d.height + " · custom";
  if (!tiers) return "→ " + d.width + " × " + d.height + " px";
  const i = ratioIndexOf(s.aspect);
  return "sends " + d.width + " × " + d.height + " · " + ratioLabel(Math.max(0, i), landscapeOf(s))
    + " · " + (d.tier ? d.tier.name : "") + (d.held ? " · short edge held at 512" : "");
}

export function OrientSwitch({ s, set, dim, phone }) {
  const land = landscapeOf(s);
  const flip = (toLand) => {
    if (toLand === land) { if (autoActive(s)) set({ auto: false }); return; }
    const a = Number(s.aspect) || 1;
    set({ landscape: toLand, aspect: a === 1 ? 1 : 1 / a, customW: "", customH: "", auto: false });
  };
  return (
    <div className={"mgts-orient" + (phone ? " phone" : "")} style={dim ? { opacity: 0.38 } : undefined}>
      <button type="button" className={"mgts-orbtn" + (!land ? " on" : "")} title="Portrait · tall frames"
        onClick={() => flip(false)}><Glyph w={11} h={16} on={!land} />Portrait</button>
      <button type="button" className={"mgts-orbtn" + (land ? " on" : "")} title="Landscape · wide frames (every ratio flips)"
        onClick={() => flip(true)}><Glyph w={16} h={11} on={land} />Landscape</button>
    </div>
  );
}

export function RatioRow({ s, set, phone }) {
  const ctxOn = onContextSide(s);
  const auto = autoActive(s);
  const land = landscapeOf(s);
  const custom = !!(parseInt(s.customW, 10) > 0 && parseInt(s.customH, 10) > 0);
  const cur = custom ? -1 : ratioIndexOf(s.aspect);
  return (
    <>
      <div className={"mgts-ratios" + (phone ? " phone" : "")}>
        {ctxOn && !phone && (
          <button type="button" className={"mgts-ratio auto" + (auto ? " on" : "")}
            title="Auto · size from @image1" onClick={() => set({ auto: true, customW: "", customH: "" })}>
            <span className={"mgts-autoglyph" + (auto ? " on" : "")}>✦</span>
            <span className="mgts-ratiolbl">Auto</span>
          </button>
        )}
        {RATIOS.map(([a, b, src], i) => {
          const on = i === cur && !auto;
          const k = 28 / a;
          const long = 28, short = Math.max(6, Math.round(b * k));
          const label = ratioLabel(i, land);
          const aspect = ratioAspect(i, land);
          const laneOff = laneRefusesFrame(s, { aspect });
          return (
            <button type="button" key={a + ":" + b} disabled={laneOff}
              className={"mgts-ratio" + (on ? " on" : "")}
              title={laneOff ? "Too large for Unlimited Mode at this size"
                : label + (src === "new" ? " · new — neither the app nor PixAI offers it"
                  : src === "web" ? " · from PixAI, new to the app" : "")}
              onClick={() => set({ aspect, customW: "", customH: "", auto: false })}>
              <Glyph w={land ? long : short} h={land ? short : long} on={on} />
              <span className="mgts-ratiolbl">{label}</span>
              {src !== "both" ? <span className={"mgts-dot " + src} aria-hidden="true" /> : null}
            </button>
          );
        })}
      </div>
      {!phone && (
        <div className="mgts-legend">
          <span><i className="mgts-dot web" />from PixAI, new to the app</span>
          <span><i className="mgts-dot new" />offered by neither</span>
        </div>
      )}
    </>
  );
}

/* The model's own live tiers (6a) with the gold members notice (6c). A non-member's click on a
   members-only tier never selects it: desktop shows the notice on hover and on click, the phone
   on tap, inline under the row. */
export function TierRow({ s, set, phone }) {
  const tiers = sizeTiers(s.model);
  const [tip, setTip] = useState("");
  if (!tiers) return null;
  const ctxOn = onContextSide(s);
  const auto = autoActive(s);
  const inForce = effectiveTier(s.model, s.tier, s.member);
  const land = landscapeOf(s);
  const i = Math.max(0, ratioIndexOf(s.aspect));
  const custom = !!(parseInt(s.customW, 10) > 0 && parseInt(s.customH, 10) > 0);
  const tipTier = tiers.find((t) => t.name === tip);
  const usable = tiers.filter((t) => !tierLocked(t, s.member));
  const upTo = usable.length ? usable[0].name : "";
  return (
    <>
      <div className={"mgts-tiers" + (phone ? " phone" : "")} style={auto ? { opacity: 0.38 } : undefined}>
        {tiers.map((t) => {
          const locked = tierLocked(t, s.member);
          const on = !custom && inForce && inForce.name === t.name;
          const d = tierDims(s.model, t, i, land);
          const laneOff = !locked && laneRefusesFrame(s, { tier: t.name });
          return (
            <button type="button" key={t.name} disabled={laneOff || (auto && !locked)}
              className={"mgts-tier" + (on ? " on" : "") + (locked ? " locked" : "") + (tip === t.name ? " lift" : "")}
              title={laneOff ? "Too large for Unlimited Mode" : locked ? t.name + " is for PixAI members" : t.name + " · " + d.width + "×" + d.height}
              onMouseEnter={() => { if (!phone && locked && !auto) setTip(t.name); }}
              onMouseLeave={() => { if (!phone) setTip(""); }}
              onClick={() => {
                if (auto) return;
                if (locked) { setTip(tip === t.name ? "" : t.name); return; }
                setTip("");
                set({ tier: t.name, customW: "", customH: "" });
              }}>
              <span className="mgts-tiername">{t.name}</span>
              {!phone ? <span className="mgts-tierdims">{d.width}×{d.height}</span> : null}
              {tierMembersOnly(t) && s.member === false ? <span className="mgts-memtag tier">Members</span> : null}
            </button>
          );
        })}
        {tipTier && !phone && (
          <div className="mgts-notice" role="note">
            <b>{tipTier.name} is for PixAI members.</b> Your account can send up to {upTo} on {s.model.title || "this model"} (a live read of your limit).
          </div>
        )}
      </div>
      {tipTier && phone && (
        <div className="mgts-notice inline" role="note">
          <b>{tipTier.name} is for PixAI members.</b> You can send up to {upTo}.
        </div>
      )}
    </>
  );
}

/* The size line, mono, tinted while Auto rules the frame. */
export function SizeLine({ s, className }) {
  const d = sizeInfo(s);
  return (
    <div className={"mgts-sizeline" + (d.source === "auto" ? " auto" : "") + (className ? " " + className : "")}>
      {sizeLine(s)}
    </div>
  );
}
