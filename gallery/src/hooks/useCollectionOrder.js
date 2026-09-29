import { useCallback, useEffect, useState } from "react";
import { fetchCollectionOrder, fetchPictureFacts, saveCollectionOrder } from "../api.js";
import { moveBy, moveItem, orderChanged } from "../curation/collectionOrderCore.js";
import { planCastSend, planShotsSend } from "../curation/loomSend.js";

/* THE ORDER EDITOR'S STATE (Session P, P6 + P5) -- shared by the desktop panel
   (CollectionOrderEditor) and the phone sheet (CollectionOrderMobile). It READS the collection's
   order on open (GET /api/collections/order: nothing is written by opening it), keeps the owner's
   moves locally, and writes once, on Save (POST, the session's CSRF token). The two Loom sends
   navigate away with the order as it is on screen; neither prices or renders anything. */
export default function useCollectionOrder(name, csrf) {
  const [ids, setIds] = useState(null);          // the order on screen
  const [saved, setSaved] = useState([]);        // the order as the server holds it
  const [manual, setManual] = useState(false);
  const [facts, setFacts] = useState({});        // id -> {prompt, created_at, is_video}
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState({ text: "", err: false });

  const load = useCallback(async () => {
    const d = await fetchCollectionOrder(name);
    if (!d || d.error || !Array.isArray(d.media_ids)) {
      setIds([]); setSaved([]);
      setMsg({ text: (d && d.error) || "The collection's order didn't load.", err: true });
      return;
    }
    setIds(d.media_ids); setSaved(d.media_ids); setManual(!!d.manual);
    setFacts(await fetchPictureFacts(d.media_ids));
  }, [name]);
  useEffect(() => { load(); }, [load]);

  const dirty = ids ? orderChanged(ids, saved) : false;
  const move = (from, to) => setIds((l) => moveItem(l || [], from, to));
  const nudge = (i, delta) => setIds((l) => moveBy(l || [], i, delta));
  const save = async () => {
    if (!ids || busy) return;
    setBusy(true);
    const d = await saveCollectionOrder(csrf, name, ids);
    setBusy(false);
    if (d.error) { setMsg({ text: d.error, err: true }); return; }
    setIds(d.media_ids); setSaved(d.media_ids); setManual(!!d.manual);
    setMsg({ text: "Order saved.", err: false });
  };
  const go = async (plan) => {
    if (busy) return;
    setBusy(true);
    const r = await plan();
    setBusy(false);
    if (!r.ok) { setMsg({ text: r.error, err: true }); return; }
    window.location.href = r.href;
  };
  const sendShots = () => go(() => planShotsSend({ ids: ids || [], collection: name, ordered: ids || [] }));
  const sendCast = () => go(() => planCastSend(ids || []));
  return { ids, facts, manual, dirty, busy, msg, move, nudge, save, sendShots, sendCast };
}

/** A row's label: the picture's prompt, first line, cut short; else its id. */
export function pictureLabel(facts, id) {
  const p = String(((facts || {})[id] || {}).prompt || "").split(/\r?\n/).map((l) => l.trim()).find((l) => l) || "";
  return p ? (p.length > 48 ? p.slice(0, 47).trimEnd() + "…" : p) : id;
}
