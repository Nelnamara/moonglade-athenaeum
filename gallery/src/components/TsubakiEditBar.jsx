import React, { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import CostBadge from "./CostBadge.jsx";
import { apiGet } from "../api.js";
import { buildPayload, goGate, tsubakiEditState, versionPatch } from "../gen/genCore.js";
import { TSUBAKI3, profileLocked, profileRows } from "../gen/tsubakiCore.js";
import { GEN_PREFS_KEY, stateFromPrefs } from "../gen/genPrefs.js";
import useAccountPrefs from "../hooks/useAccountPrefs.js";
import usePriceProbe from "../gen/usePriceProbe.js";
import { submitTask } from "../gen/submitTask.js";
import "../styles/tsubaki.css";

/* The Lightbox edit bar (Session H T3a; handoff frame G, "T3a · LIGHTBOX EDIT BAR"): "Describe
   your edits…" over the stage foot, on every still picture -- the same pictures as the "Edit
   with Tsubaki" menu item (the card's tsubaki_edit; never a video). ↵ sends a Tsubaki.3 run: this picture as @image1, the words as the prompt, the
   dock's profile (the per-account gen.image setting), size Auto, count 1, no recipes, no
   palette, no LoRAs, no negative, no boosters, no High priority. The run joins the dock's reel
   and the Activity toast; the Lightbox stays open.

   ONE PAYLOAD ROAD: the state is genCore.tsubakiEditState and the payload the dock's own
   buildPayload over it, priced by the shared usePriceProbe and sent by the shared submitTask --
   so the quote identity gate covers it, and the price shown in the bar is the one sent.

   SPEND SAFETY (BUILD-w2-gen review B1): submitTask has no latch of its own, so this handler
   carries one -- a synchronous busyRef set before the POST -- ignores an auto-repeating or
   composing Enter, checks the probe's verdict INSIDE the handler (a keyboard Enter needs no
   repaint), and forces a re-price when the server answers. The probe runs only while the bar
   has words (review N6). */

let _metaCache = null;          // {at, model} -- Tsubaki.3's applied meta, one read per page
let _metaWait = null;
function loadTsubakiMeta() {
  if (_metaCache && Date.now() - _metaCache.at < 10 * 60 * 1000) return Promise.resolve(_metaCache.model);
  if (_metaWait) return _metaWait;
  _metaWait = apiGet("/api/model-version?model_id=" + encodeURIComponent(TSUBAKI3.model_id) + "&all=1")
    .then((d) => {
      _metaWait = null;
      const versions = (d && d.versions) || [];
      const latest = versions.find((v) => v.is_latest) || versions[0];
      if (!latest || !latest.version_id) return null;
      const model = {
        model_id: TSUBAKI3.model_id, title: TSUBAKI3.title, thumb: "",
        version_id: latest.version_id, model_type: latest.model_type || "", versions,
        ...versionPatch(latest),
      };
      _metaCache = { at: Date.now(), model };
      return model;
    });
  return _metaWait;
}

const TsubakiEditBar = forwardRef(function TsubakiEditBar({ item, member, phone }, ref) {
  const [words, setWords] = useState("");
  const [model, setModel] = useState(_metaCache ? _metaCache.model : null);
  const [line, setLine] = useState(null);          // {kind, text} -- the last send's answer
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const costRef = useRef(null);
  const inputRef = useRef(null);
  const prefs = useAccountPrefs();

  useImperativeHandle(ref, () => ({
    focus() { if (inputRef.current) inputRef.current.focus(); },
    get focused() { return !!inputRef.current && document.activeElement === inputRef.current; },
  }), []);

  useEffect(() => {
    let live = true;
    if (!model) loadTsubakiMeta().then((mm) => { if (live && mm) setModel(mm); });
    return () => { live = false; };
  }, [model]);

  // a new picture: its own words, its own answer line
  useEffect(() => { setWords(""); setLine(null); }, [item && item.media_id]);

  // The dock's profile, when Tsubaki.3 offers it and this account may run it; else auto.
  const dock = stateFromPrefs(prefs.get(GEN_PREFS_KEY, null));
  const rows = profileRows(model);
  const row = rows && rows.find((r) => r.name === dock.mode);
  const mode = row && !profileLocked(row, member) ? row.name : "auto";

  const w = Number(item && item.w) || 0;
  const h = Number(item && item.h) || 0;
  const state = useMemo(() => tsubakiEditState({
    model, member, mode, tier: dock.tier || "",
    image: item ? { media_id: item.media_id, thumb: item.thumb, w, h } : null,
    prompt: words,
  }), [model, member, mode, dock.tier, item, w, h, words]);

  const ready = !!(model && model.version_id && w > 0 && h > 0);
  const build = useCallback(() => {
    if (!ready) return { payload: null, idle: model ? "Can't read this picture's size" : "Reading Tsubaki.3…" };
    return { payload: buildPayload(state), idle: null };
  }, [ready, model, state]);
  const probe = usePriceProbe({ build, costRef, enabled: !!words.trim() });
  // a change that prices (the picture, the profile, the tier) re-prices; words alone do not
  useEffect(() => { if (words.trim()) probe.refresh(); },     // eslint-disable-line react-hooks/exhaustive-deps
    [ready, mode, dock.tier, item && item.media_id, model && model.version_id, words.trim() ? 1 : 0]);

  const gate = !words.trim() ? "Describe your edits" : !ready ? "Not ready yet" : goGate(state, null);
  const canSend = !gate && !busy && probe.canSubmit;

  const send = useCallback(async () => {
    if (busyRef.current) return;                     // the latch, before anything async
    if (!words.trim() || !ready) return;
    const g = goGate(state, null);
    if (g) { setLine({ kind: "err", text: g }); return; }
    if (!probe.canSubmit) { probe.refresh(); return; }
    busyRef.current = true;
    setBusy(true);
    let last = null;
    const tid = await submitTask("/api/generate", buildPayload(state), {
      label: "Tsubaki edit",
      emit: (patch) => { last = patch; setLine({ kind: patch.kind || "run", text: patch.text }); },
    });
    busyRef.current = false;
    setBusy(false);
    probe.refresh({ force: true });
    if (tid) setWords("");
    else if (last && last.kind !== "err") setLine(null);
  }, [words, ready, state, probe]);

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (e.repeat || (e.nativeEvent && e.nativeEvent.isComposing)) return;
      if (canSend) send(); else if (!busy) probe.refresh();
      return;
    }
    if (e.key === "Escape") {
      // Esc leaves the bar first; the next Esc is the Lightbox's
      e.preventDefault();
      e.stopPropagation();
      e.currentTarget.blur();
    }
  };

  if (!item || !item.tsubaki_edit) return null;
  return (
    <div className={"mgteb" + (phone ? " phone" : "")} onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()} onTouchStart={(e) => e.stopPropagation()}>
      <div className="mgteb-pill">
        <input ref={inputRef} className="mgteb-input" value={words} placeholder="Describe your edits…"
          aria-label="Describe your edits — sends a Tsubaki.3 run with this picture as @image1"
          onChange={(e) => setWords(e.target.value)} onKeyDown={onKeyDown} maxLength={10000} />
        {words.trim() ? <CostBadge ref={costRef} compact className="mgteb-cost" hint="" /> : null}
        <button type="button" className="mgteb-go" disabled={!canSend} onClick={send}
          aria-label="Send the edit" title={busy ? "Sending…" : gate || "Send — this spends credits or a card"}>↑</button>
      </div>
      {line && line.text ? <div className={"mgteb-line " + line.kind}>{line.text}</div> : null}
    </div>
  );
});

export default TsubakiEditBar;
