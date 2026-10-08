import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import useLayerHistory from "../hooks/useLayerHistory.js";
import { apiGet } from "../api.js";
import { getUpdate, subscribe as subscribeUpdate } from "../notify/updateStore.js";
import { requestUpdateOpen } from "../notify/bannerStore.js";
import { highlightsOf } from "./helpCore.js";
import { useAbout } from "./helpData.js";
import { closeAbout, closeWhatsNew, openAbout, openHelp, requestSurface, subscribeAbout } from "./helpStore.js";
import "../styles/help.css";

/* ABOUT AND WHAT'S NEW, SIZED TO THE RELEASE (Session I decision 3; the handoff's
   section C).

     AboutCard       the About content: Nel, the name, "app x.y.z · art pack vN · date", this
                     version's CHANGELOG entry, "Earlier versions ›", Guide / Report an issue ↗
                     / Releases ↗. With a release out it LEADS with the update card.
     AboutLayer      AboutCard as the 400 px modal (the Control Panel's version stamp, the
                     phone Control tab's About row, a patch release's toast). Help's last
                     page renders the same card inline.
     WhatsNewSheet   the one-time 440 px sheet for a minor or major release: the entry's
                     first four items, each with "Show me ›" to its surface, "Full changelog
                     in About ›" and "Continue".

   The content is the server's cut of CHANGELOG.md for the RUNNING version (/api/help/about);
   whether a newer release is out is the updater's answer, read from the standing
   announcement (notify/updateStore.js) and, when About is asked to lead with it, the cached
   /api/update/check. Nothing here can apply an update: the card's button opens the Control
   Panel's own update confirm (bannerStore.requestUpdateOpen), exactly like the strip's. */

const NEL = "/branding/mascots/gen_nel.png";
const nelStyle = { backgroundImage: "url('" + NEL + "')" };

function useUpdatePayload(ask) {
  const [u, setU] = useState(() => getUpdate());
  useEffect(() => subscribeUpdate((p) => setU(p)), []);
  useEffect(() => {
    if (!ask || u) return undefined;
    let live = true;
    apiGet("/api/update/check").then((d) => { if (live && d && d.behind) setU(d); });
    return () => { live = false; };
  }, [ask, u]);
  return u && u.behind ? u : null;
}

function packLabel(pack) {
  if (!pack || !pack.installed) return "art pack not installed";
  return pack.version ? "art pack v" + pack.version : "art pack installed";
}

export function AboutCard({ inline, lead, onClose }) {
  const about = useAbout(true);
  const update = useUpdatePayload(lead === "update");
  const [showing, setShowing] = useState(null);     // an earlier entry, or null for this one
  const [earlierOpen, setEarlierOpen] = useState(false);
  if (!about) return <div className="mghelp-loading">Reading this install…</div>;
  const entry = showing || about;
  const items = (entry.items || []).filter((i) => !i.section);
  const under = (entry.items || []).filter((i) => i.section);
  const ver = showing ? showing.version : about.display_version;
  const done = () => { if (onClose) onClose(); };
  return (
    <div className={"mgab" + (inline ? " inline" : "")}>
      {update ? (
        <div className="mgab-upd">
          <div className="mgab-updtxt">
            <b className="mgab-mono">{update.latest}</b> is out{update.title ? " · " + update.title : ""}
          </div>
          <button type="button" className="mgab-updgo"
            onClick={() => { done(); requestUpdateOpen(); }}>View the update ›</button>
        </div>
      ) : null}
      <div className="mgab-id">
        <span className="mgab-nel" style={nelStyle} aria-hidden="true" />
        <div className="mgab-idtxt">
          <div className="mgab-name">Moonglade Athenaeum</div>
          <div className="mgab-stamp">
            app {about.version} · {packLabel(about.pack)}{about.date ? " · " + about.date : ""}
          </div>
        </div>
      </div>
      <div className="mgab-kick">CHANGELOG · {ver}</div>
      {earlierOpen && !showing ? (
        <div className="mgab-earlier">
          {(about.earlier || []).map((e) => (
            <button type="button" key={e.version} onClick={() => setShowing(e)}>
              <span className="mgab-mono">{e.version}</span> {e.title}<span className="d">{e.date}</span>
            </button>
          ))}
          {!(about.earlier || []).length ? <div className="mgab-none">No earlier versions in this install's changelog.</div> : null}
        </div>
      ) : (
        <ul className="mgab-items">
          {items.map((i, k) => <li key={k}>{i.lead}</li>)}
          {under.length ? <li className="under">Under the hood: {under.map((i) => clip(i.lead, 64)).join(" · ")}</li> : null}
          {!items.length && !under.length ? <li className="under">This version has no changelog entry in this install.</li> : null}
        </ul>
      )}
      {showing ? (
        <button type="button" className="mgab-link" onClick={() => setShowing(null)}>‹ This version</button>
      ) : (
        <button type="button" className="mgab-link" onClick={() => setEarlierOpen((v) => !v)}>
          {earlierOpen ? "‹ This version" : "Earlier versions ›"}
        </button>
      )}
      <div className="mgab-btns">
        {inline ? null : (
          <button type="button" onClick={() => { done(); openHelp({ slug: "Home" }); }}>Guide</button>
        )}
        <a href={about.issues_url} target="_blank" rel="noopener noreferrer">Report an issue ↗</a>
        <a href={about.releases_url} target="_blank" rel="noopener noreferrer">Releases ↗</a>
      </div>
    </div>
  );
}

function useAboutState() {
  const [s, setS] = useState({ about: { open: false, closing: false, lead: "" }, sheet: { open: false, closing: false, about: null } });
  useEffect(() => subscribeAbout((about, sheet) => setS({ about: { ...about }, sheet: { ...sheet } })), []);
  return s;
}

export function AboutLayer({ phone }) {
  const { about } = useAboutState();
  const up = about.open || about.closing;
  useLayerHistory(!!(phone && about.open), closeAbout);
  if (!up) return null;
  const cls = about.closing ? " closing" : "";
  return createPortal(
    <>
      <div className={"mgab-scrim" + cls} onMouseDown={closeAbout} data-keeps-dock="1" />
      <div className={"mgab-host" + (phone ? " phone" : "") + cls} data-keeps-dock="1">
        <div className={"mgab-modal" + (phone ? " phone" : "") + cls} role="dialog" aria-modal="true" aria-label="About Moonglade Athenaeum">
          <button type="button" className="mghelp-x mgab-x" onClick={closeAbout} aria-label="Close">×</button>
          <AboutCard key={about.nonce} lead={about.lead} onClose={closeAbout} />
        </div>
      </div>
    </>,
    document.body,
  );
}

export function WhatsNewSheet({ phone }) {
  const { sheet } = useAboutState();
  const up = sheet.open || sheet.closing;
  useLayerHistory(!!(phone && sheet.open), closeWhatsNew);
  if (!up || !sheet.about) return null;
  const a = sheet.about;
  const cls = sheet.closing ? " closing" : "";
  const hl = highlightsOf(a.items, 4);
  return createPortal(
    <>
      <div className={"mgwn-scrim" + cls} onMouseDown={closeWhatsNew} data-keeps-dock="1" />
      <div className={"mgwn-host" + (phone ? " phone" : "") + cls} data-keeps-dock="1">
        <div className={"mgwn" + (phone ? " phone" : "") + cls} role="dialog" aria-modal="true" aria-label={"New in " + a.display_version}>
          <div className="mgwn-head">
            <div className="mgwn-title">New in {a.display_version}</div>
            <span className="mgwn-nel" style={nelStyle} aria-hidden="true" />
          </div>
          <div className="mgwn-grid">
            {hl.map((h, i) => (
              <div className="mgwn-card" key={i}>
                <div className="mgwn-t">{clip(h.lead, 72)}</div>
                {h.text ? <div className="mgwn-d">{firstSentence(h.text)}</div> : null}
                {h.surface ? (
                  <button type="button" className="mgwn-show"
                    onClick={() => { closeWhatsNew(); requestSurface(h.surface); }}>Show me ›</button>
                ) : null}
              </div>
            ))}
          </div>
          <div className="mgwn-foot">
            <button type="button" className="mgwn-full"
              onClick={() => { closeWhatsNew(); openAbout(""); }}>Full changelog in About ›</button>
            <button type="button" className="mgwn-go" onClick={closeWhatsNew} autoFocus>Continue</button>
          </div>
        </div>
      </div>
    </>,
    document.body,
  );
}

/* A line cut at a word before `n` characters. */
function clip(text, n) {
  const s = String(text || "");
  return s.length <= n ? s : s.slice(0, n - 1).replace(/\s+\S*$/, "") + "…";
}

/* A highlight card's line: the item's first sentence, kept short. */
function firstSentence(text) {
  const s = String(text || "");
  const m = /^(.{12,200}?[.!?])(\s|$)/.exec(s);
  const one = m ? m[1] : s;
  return one.length > 140 ? one.slice(0, 137).replace(/\s+\S*$/, "") + "…" : one;
}
