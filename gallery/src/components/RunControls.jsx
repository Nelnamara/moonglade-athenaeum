import React, { useState } from "react";
import {
  CELL_CAP, confirmCopy, listItemsFromText, listProblem, previewRows, sendSummary, tokenLine,
} from "../gen/templateCore.js";
import "../styles/runs.css";

/* Session M's dock pieces (Generate Power Tools Handoff, frame A "the dock"): the token line
   under the prompt, the Random | Matrix row with its count and ⚄ Reroll, the preview, the
   Lists sheet, and THE ONE multi-send confirm. Drawing only: what is sent is decided by the
   server (useRuns + /api/generate/plan, /run). The phone mounts RunConfirm too. */

/* The prompt's tokens, tinted: variables lavender with their option count, refusals peach. */
export function TokenLine({ parsed }) {
  if (!parsed || !parsed.syntax) return null;
  return (
    <div className="mgrun-toks" aria-label="Prompt variables">
      {tokenLine(parsed).map((k, i) => (
        <span key={i} className={"mgrun-tok" + (k.kind === "lit" ? "" : " " + k.kind)}
          title={k.why || undefined}>{k.t}</span>
      ))}
    </div>
  );
}

/* Random | Matrix · ×1–4 · ⚄ Reroll · the summary. Shown while the prompt uses the syntax (a
   plain prompt is a plain send; its count stays the COUNT stops). */
export function RunModeRow({ s, set, parsed, plan, onLists, listsOpen }) {
  if (!parsed || !parsed.syntax) return null;
  const matrix = s.varMode === "matrix";
  const summary = sendSummary(parsed, plan, s.varMode || "random", s.count);
  const bad = !!(parsed.error || (plan && plan.error));
  return (
    <>
      <div className="mgrun-moderow">
        <div className="mgrun-seg">
          {[["random", "Random", "One value per image"], ["matrix", "Matrix", "Every combination, queued (cap " + CELL_CAP + ")"]]
            .map(([k, l, t]) => (
              <button key={k} type="button" title={t}
                className={(s.varMode || "random") === k ? "on" : ""}
                disabled={k === "matrix" && s.unlimited}
                onClick={() => set({ varMode: k })}>{l}</button>
            ))}
        </div>
        {!matrix && (
          <>
            <div className="mgrun-seg">
              {[1, 2, 3, 4].map((n) => (
                <button key={n} type="button" className={s.count === n ? "on" : ""}
                  disabled={s.unlimited && n !== 1}
                  title={s.unlimited && n !== 1 ? "Unlimited Mode makes one picture at a time" : undefined}
                  onClick={() => set({ count: n })}>{"×" + n}</button>
              ))}
            </div>
            <button type="button" className="mgrun-reroll" title="Draw new values for the variables"
              onClick={() => set({ roll: nextRoll(s.roll) })}>⚄ Reroll</button>
          </>
        )}
        {onLists && (
          <button type="button" className={"mgrun-lists" + (listsOpen ? " on" : "")}
            onClick={onLists} title="Your saved lists — __name__ in a prompt">Lists ▾</button>
        )}
        <div className={"mgrun-summary" + (bad ? " bad" : "")}>{summary}</div>
      </div>
    </>
  );
}

/* The preview (page: "PREVIEW · what each image will get" / "the first cells" / "over the
   cap"): up to six resolved prompts, then "… N more". Under the confirm, as on the page. */
export function RunPreview({ s, parsed, plan }) {
  if (!parsed || !parsed.syntax || !parsed.vars.length) return null;
  const matrix = s.varMode === "matrix";
  const label = matrix ? (plan && plan.error && plan.product > CELL_CAP ? "PREVIEW · over the cap" : "PREVIEW · the first cells")
    : "PREVIEW · what each image will get";
  const rows = previewRows(plan);
  if (!rows.length) return null;
  return (
    <div className="mgrun-preview">
      <div className="mgrun-prevlbl">{label}</div>
      {rows.map((r, i) => <div key={i} className="mgrun-prevrow" title={r}>{r}</div>)}
    </div>
  );
}

/* The page's reroll moves the roll by a fixed step (roll + 7919); wrapped into the run seed's
   range so the server's own check always accepts it. */
function nextRoll(roll) {
  return (Number(roll || 0) + 7919) % 2147483647;
}

/* The Lists sheet (page M1): a name and one item per line, saved to the account store
   (gen.lists) so the phone sees them too. Saving is a deliberate click; nothing is written
   on open. */
export function ListsSheet({ lists, onSave, onClose }) {
  const names = Object.keys(lists || {}).sort();
  const [name, setName] = useState(names[0] || "");
  const [text, setText] = useState(names[0] ? (lists[names[0]] || []).join("\n") : "");
  const [msg, setMsg] = useState("");
  const [bad, setBad] = useState(false);
  const pick = (n) => { setName(n); setText((lists[n] || []).join("\n")); setMsg(""); };
  const items = listItemsFromText(text);
  const problem = listProblem(name, items, lists);
  const save = async () => {
    if (problem) { setMsg(problem); setBad(true); return; }
    const d = await onSave({ ...(lists || {}), [name]: items });
    if (d && d.error) { setMsg(d.error); setBad(true); } else { setMsg("Saved __" + name + "__."); setBad(false); }
  };
  const del = async () => {
    if (!name || !(lists || {})[name]) return;
    const next = { ...(lists || {}) };
    delete next[name];
    const d = await onSave(next);
    if (d && d.error) { setMsg(d.error); setBad(true); } else { pick(""); setMsg("Deleted."); setBad(false); }
  };
  return (
    <div className="mgrun-sheet" role="dialog" aria-label="Saved lists">
      <div className="mgrun-sheetrow">
        {names.map((n) => (
          <button key={n} type="button" className={"mgrun-chip" + (n === name ? " on" : "")}
            onClick={() => pick(n)}>{"__" + n + "__"}</button>
        ))}
        <button type="button" className="mgrun-chip" onClick={() => pick("")}>+ new</button>
      </div>
      <div className="mgrun-sheetrow">
        <input value={name} placeholder="list name (a–z, 0–9, _)" aria-label="List name"
          onChange={(e) => { setName(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "")); setMsg(""); }} />
        <span className="mgrun-sheetmsg">{items.length} item{items.length === 1 ? "" : "s"}</span>
      </div>
      <textarea rows={5} value={text} placeholder="one item per line" aria-label="List items"
        onChange={(e) => { setText(e.target.value); setMsg(""); }} />
      <div className="mgrun-sheetrow">
        <button type="button" className="mgrun-save" disabled={!!problem} title={problem || "Save to your account"}
          onClick={save}>Save</button>
        {(lists || {})[name] ? <button type="button" className="mgrun-ccancel" onClick={del}>Delete</button> : null}
        <button type="button" className="mgrun-ccancel" onClick={onClose}>Close</button>
        <span className={"mgrun-sheetmsg" + (bad ? " bad" : "")}>{msg}</span>
      </div>
    </div>
  );
}

/* THE ONE confirm (NOTES 2, page "$"): the count, the total credits and the free cards that
   cover it, from the server's own quote. Cancel sends nothing; there is no "don't ask
   again". A refusal or a moved price is peach. */
export function RunConfirm({ confirm, onGo, onCancel, busy }) {
  if (!confirm) return null;
  if (confirm.loading) {
    return (
      <div className="mgrun-confirm" role="status">
        <div className="mgrun-ccards">Checking the price with PixAI…</div>
      </div>
    );
  }
  if (confirm.error) {
    return (
      <div className="mgrun-confirm err" role="alert">
        <div className="mgrun-cerr">{confirm.error}</div>
        <div className="mgrun-cbtns">
          <button type="button" className="mgrun-ccancel" onClick={onCancel}>Close · nothing was sent</button>
        </div>
      </div>
    );
  }
  const c = confirmCopy(confirm.plan);
  return (
    <div className="mgrun-confirm" role="dialog" aria-label="Confirm the run">
      {confirm.moved ? <div className="mgrun-cmoved">{confirm.moved} Here are the new numbers.</div> : null}
      <div className="mgrun-ctitle">{c.title}</div>
      <div className="mgrun-ccredits">{c.credits}</div>
      <div className="mgrun-ccards">{c.cards}</div>
      {c.note ? <div className="mgrun-cnote">{c.note}</div> : null}
      <div className="mgrun-cbtns">
        <button type="button" className="mgrun-cgo" disabled={c.blocked || busy} onClick={onGo}>{c.go}</button>
        <button type="button" className="mgrun-ccancel" onClick={onCancel}>Cancel · nothing is sent</button>
      </div>
    </div>
  );
}
