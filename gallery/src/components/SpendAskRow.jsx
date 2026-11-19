import React, { useEffect, useState } from "react";
import useAccountPrefs from "../hooks/useAccountPrefs.js";
import { SPEND_ASK_KEY, askThreshold, parseAskInput } from "../gen/spendButtonCore.js";

/* The one-time ask's setting (3.21.x look pick round 2, topic 1, "The same in every choice"):
   a row in the Control Panel's PixAI account tile, "Ask before spending more than [ 10,000 ]
   credits", off until set. Above that amount a button that spends turns into "Confirm — spend
   ≈ N" on the first press and sends on the second (SpendButton.jsx); a free card never asks.

   On the account, not the device: /api/account/prefs under SPEND_ASK_KEY, so the phone and the
   desktop ask at the same amount. An empty field (or 0) removes the key, which is off. The
   number box is the Panel's own small field (.mgcp-bjport, the Bonjour port's), in the tile's
   own row (.mgcp-devrow, the blur switch's). The tile itself opens the account sheet on a
   click, so this row keeps its clicks to itself. */
export default function SpendAskRow() {
  const prefs = useAccountPrefs();
  const stored = askThreshold(prefs.get(SPEND_ASK_KEY, 0));
  const [text, setText] = useState(stored ? String(stored) : "");
  const [msg, setMsg] = useState("");
  // Follow the stored value when it arrives (the first load) or changes elsewhere.
  useEffect(() => { setText(stored ? String(stored) : ""); }, [stored]);

  const save = async () => {
    const { value, error } = parseAskInput(text);
    if (error) { setMsg(error); return; }
    if ((value || 0) === stored) { setMsg(""); setText(value ? String(value) : ""); return; }
    const r = value ? await prefs.set(SPEND_ASK_KEY, value) : await prefs.unset(SPEND_ASK_KEY);
    setMsg(r && r.error ? String(r.error) : "");
  };

  const stop = (e) => e.stopPropagation();
  return (
    <div className="mgcp-spendask" onClick={stop}>
      <label className="mgcp-devrow">
        <span>Ask before spending more than</span>
        <input className="mgcp-bjport" inputMode="numeric" value={text} placeholder="off"
          aria-label="Ask before spending more than this many credits (empty = never ask)"
          onChange={(e) => { setText(e.target.value); setMsg(""); }}
          onBlur={save} onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
        <span className="mgcp-spendask-unit">credits</span>
      </label>
      {msg ? <div className="mgcp-tilenote mgcp-spendask-err">{msg}</div> : null}
    </div>
  );
}
