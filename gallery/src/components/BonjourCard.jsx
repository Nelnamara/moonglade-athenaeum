import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api.js";
import qrcode from "qrcode-generator";

/* The Control Panel's Bonjour / LAN-discovery chip -- one home for "how is my server exposed":
   broadcast on/off, bind IP, port, the advertised name, a live status line, and Copy/QR of the
   reachable address. Self-contained: it reads /api/bonjour/status and writes
   /api/bonjour/settings (see moonglade_gallery.py). Editable controls show only for a localhost
   session, because the write route is LOCALHOST-tier -- a LAN device may SEE the broadcast state
   but only the server box changes the bind. Fail-soft: on an older server without the route the
   fetch fails and the whole card just stays hidden. */

const NAME_CHOICES = ["Moonglade", "Athenaeum", "Moonglade Athenaeum", "The Library"];

function qrDataUrl(text) {
  try {
    const qr = qrcode(0, "M");        // type 0 = smallest version that fits; error-correction M
    qr.addData(text);
    qr.make();
    return qr.createDataURL(4, 8);    // cell 4px, quiet-zone margin 8px -> a data: image URL
  } catch {
    return null;
  }
}

export default function BonjourCard({ isLocal }) {
  const [st, setSt] = useState(null);        // last /api/bonjour/status
  const [draft, setDraft] = useState(null);  // editable form, seeded from status
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");        // save result / restart-needed note
  const [copied, setCopied] = useState(false);
  const [showQr, setShowQr] = useState(false);

  async function load() {
    try {
      const d = await apiGet("/api/bonjour/status");
      setSt(d);
      setDraft((cur) => cur || {
        enabled: !!d.enabled,
        name: d.name || "Moonglade",
        host: d.host || "127.0.0.1",
        port: d.port || 5000,
      });
    } catch {
      /* fail-soft: leave st null -> card stays hidden (e.g. a server without the route) */
    }
  }
  useEffect(() => { load(); }, []);

  if (!st) return null;
  const d = draft || {};
  const setD = (patch) => setDraft({ ...d, ...patch });

  const url = (st.reachable_urls && st.reachable_urls[0]) || "";

  async function save() {
    setSaving(true);
    setMsg("");
    try {
      const r = await apiPost("/api/bonjour/settings", {
        enabled: !!d.enabled, name: d.name, host: d.host, port: Number(d.port),
      });
      if (r && r.error) {
        setMsg(r.error);
      } else {
        setMsg(r && r.restart_needed ? "Saved — restart to apply the new reach/port." : "Saved.");
        setShowQr(false);
        setDraft(null);       // re-seed from the fresh status
        await load();
      }
    } catch {
      setMsg("Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked (non-secure context / permissions) -- the URL is on screen to type */
    }
  }

  const qr = showQr && url ? qrDataUrl(url) : null;

  return (
    <div className="mgcp-bonjour">
      <div className="mgcp-sidekick">LAN discovery</div>

      <div className="mgcp-bjstatus">
        <span className={"mgcp-bjdot" + (st.broadcasting ? " on" : "")} />
        {st.broadcasting ? (
          <span>Broadcasting as <b>{st.hostname}</b></span>
        ) : st.zeroconf_available ? (
          <span className="off">{st.lan_bind ? "Off — not broadcasting" : "Localhost only — not on the network"}</span>
        ) : (
          <span className="off">mDNS unavailable — <code>pip install zeroconf</code></span>
        )}
      </div>

      {st.broadcasting && url ? (
        <>
          <div className="mgcp-bjurls">
            <span className="mgcp-bjurl" title={url}>{url}</span>
            <button type="button" className="mgcp-chip" onClick={copy}>{copied ? "✓ Copied" : "Copy"}</button>
            <button type="button" className="mgcp-chip" onClick={() => setShowQr((v) => !v)}>{showQr ? "Hide QR" : "QR"}</button>
          </div>
          {qr ? (
            <div className="mgcp-bjqr">
              <img src={qr} alt={"QR code for " + url} width={132} height={132} />
              <div className="mgcp-tilenote">Scan with the iPad's camera to open it.</div>
            </div>
          ) : null}
        </>
      ) : null}

      {isLocal ? (
        <div className="mgcp-bjform">
          <div className="mgcp-bjrow">
            <span>Broadcast</span>
            <button type="button" className={"mgcp-bjtoggle" + (d.enabled ? " on" : "")}
              aria-pressed={!!d.enabled} onClick={() => setD({ enabled: !d.enabled })}>
              {d.enabled ? "On" : "Off"}
            </button>
          </div>
          <div className="mgcp-bjrow">
            <span>Reach</span>
            <span className="mgcp-bjseg">
              <button type="button" className={d.host === "127.0.0.1" ? "on" : ""}
                onClick={() => setD({ host: "127.0.0.1" })}>This PC</button>
              <button type="button" className={d.host === "0.0.0.0" ? "on" : ""}
                onClick={() => setD({ host: "0.0.0.0" })}>LAN</button>
            </span>
          </div>
          <div className="mgcp-bjrow">
            <span>Port</span>
            <input type="number" className="mgcp-bjport" min="1" max="65535" value={d.port}
              onChange={(e) => setD({ port: e.target.value })} />
          </div>
          <div className="mgcp-bjrow">
            <span>Name</span>
            <select className="mgcp-bjname" value={d.name} onChange={(e) => setD({ name: e.target.value })}>
              {NAME_CHOICES.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          <div className="mgcp-bjrow">
            <button type="button" className="mgcp-chip" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save"}</button>
            {msg ? <span className="mgcp-tilenote">{msg}</span> : null}
          </div>
          <div className="mgcp-tilenote">
            Changing Reach or Port restarts the server. Installing as an iPad app (HTTPS) is a later add.
          </div>
        </div>
      ) : (
        <div className="mgcp-tilenote">Bonjour settings are changed from the server machine.</div>
      )}
    </div>
  );
}
