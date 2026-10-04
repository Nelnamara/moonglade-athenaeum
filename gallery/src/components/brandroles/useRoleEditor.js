import { useCallback, useEffect, useRef, useState } from "react";
import { apiPost, apiUpload } from "../../api.js";
import { measureBlob, refusalText, specFailures, ticks } from "../../lib/brandRolesCore.js";

/* One role's editor state, shared by the desktop row (BrandRoles.jsx) and the phone's role screen
   (BrandRolesPhone.jsx): which image is being changed, the candidate file, what it measured,
   the live ticks, and the two writes -- Use this (upload) and Use default (restore).

   Nothing is written until the candidate has passed every rule HERE; the server then measures the
   file again and may still refuse (its words are shown the same way). A refused or unreadable file
   never touches what is on disk, and the row's art does not change. On the desktop the pick waits
   for Use this; the phone's photo picker passes `{ commit: true }`, so a pick that clears every
   rule uploads itself and one that does not shows its ticks and refusal and sends nothing.
   `csrf` is the session's token (summary.csrf); `onSaved()` re-reads the Branding payload. */
export default function useRoleEditor({ role, csrf, onSaved }) {
  const [key, setKey] = useState(role.images[0].key);
  const [cand, setCand] = useState(null);       // {name, url, facts, ticks, failed, source:{file|mediaId}} | null
  const [measuring, setMeasuring] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");        // a server refusal / transport error, in its own words
  const urlRef = useRef("");
  // The rule THIS image's override must meet (the server's role_image_spec, in the Branding payload).
  const specRef = useRef(null);
  specRef.current = (role.images.find((i) => i.key === key) || role.images[0]).spec;

  const drop = useCallback(() => {
    if (urlRef.current) { URL.revokeObjectURL(urlRef.current); urlRef.current = ""; }
    setCand(null); setError("");
  }, []);
  useEffect(() => () => { if (urlRef.current) URL.revokeObjectURL(urlRef.current); }, []);

  const select = useCallback((k) => { setKey(k); drop(); }, [drop]);

  const keyRef = useRef(key);
  keyRef.current = key;
  // The one upload: a picture (a File from this device, or a library media id) becomes the override
  // of the selected image. The server measures it again and may refuse in its own words.
  const send = useCallback(async (source) => {
    setBusy(true); setError("");
    const fd = new FormData();
    fd.append("csrf", csrf || ""); fd.append("slot", role.slot); fd.append("key", keyRef.current);
    if (source.file) fd.append("file", source.file); else fd.append("media_id", source.mediaId);
    const d = await apiUpload("/api/branding/role", fd);
    setBusy(false);
    if (d.error) { setError(d.error); return false; }
    drop(); await onSaved(); return true;
  }, [csrf, role.slot, drop, onSaved]);

  // Measure a File/Blob on this device and keep the result as the candidate; with `commit`, a
  // candidate that clears every rule is sent at once.
  const consider = useCallback(async (blob, name, source, commit) => {
    if (urlRef.current) { URL.revokeObjectURL(urlRef.current); urlRef.current = ""; }
    setError(""); setMeasuring(true);
    const facts = await measureBlob(blob);
    setMeasuring(false);
    if (facts.unreadable) {
      setCand({ name, url: "", facts, ticks: [], failed: [], unreadable: true, source });
      return;
    }
    const failed = specFailures(specRef.current, facts);
    urlRef.current = failed.length ? "" : URL.createObjectURL(blob);
    setCand({ name, url: urlRef.current, facts, ticks: ticks(specRef.current, facts), failed, source });
    if (commit && !failed.length) await send(source);
  }, [send]);

  const pickFile = useCallback((file, { commit = false } = {}) => {
    if (file) consider(file, file.name, { file }, commit);
  }, [consider]);

  // From the gallery: the picture is already in this library, so the server measures it
  // (check_only: nothing is written) and the SAME rules tick the facts it reports.
  const pickGallery = useCallback(async (mediaId) => {
    if (urlRef.current) { URL.revokeObjectURL(urlRef.current); urlRef.current = ""; }
    setError(""); setMeasuring(true);
    const fd = new FormData();
    fd.append("csrf", csrf || ""); fd.append("slot", role.slot); fd.append("key", key);
    fd.append("media_id", mediaId); fd.append("check", "1");
    const d = await apiUpload("/api/branding/role", fd);
    setMeasuring(false);
    if (d.error || !d.facts) {
      setCand({ name: "", url: "", facts: {}, ticks: [], failed: [], unreadable: true, source: { mediaId },
        message: d.error || "" });
      return;
    }
    const failed = specFailures(specRef.current, d.facts);
    setCand({ name: "", url: failed.length ? "" : "/full/" + encodeURIComponent(mediaId), facts: d.facts,
      ticks: ticks(specRef.current, d.facts), failed, source: { mediaId } });
  }, [csrf, role.slot, key]);

  const ok = !!cand && !cand.unreadable && cand.failed.length === 0;
  const roleName = role.name;
  // The loud refusal's words: the local rules' sentence, or the server's own when it refused.
  const refusal = error
    ? error
    : cand && cand.unreadable
      ? (cand.message || "Refused: that picture couldn't be read. Your current art is unchanged.")
    : cand && cand.failed.length ? refusalText(roleName, cand.failed)
    : "";

  const useThis = useCallback(async () => {
    if (!ok || busy) return false;
    return send(cand.source);
  }, [ok, busy, cand, send]);

  const restore = useCallback(async (imageKey) => {
    setBusy(true); setError("");
    const d = await apiPost("/api/branding/role/restore", { csrf: csrf || "", slot: role.slot, key: imageKey });
    setBusy(false);
    if (d.error) { setError(d.error); return false; }
    drop(); await onSaved(); return true;
  }, [csrf, role.slot, drop, onSaved]);

  return { key, select, cand, measuring, busy, ok, refusal, pickFile, pickGallery, useThis, restore, drop, error };
}
