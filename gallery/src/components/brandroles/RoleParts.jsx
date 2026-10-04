import React from "react";
import { RESTORE_BODY, imageUrl, restoreAsk } from "../../lib/brandRolesCore.js";

/* The small pieces the Roles section draws on the desktop row and the phone's role screen alike
   (Branding Roles Handoff). All of them are plain markup over brand-roles.css. */

/** One image's art at `size` px (34 current, 28 default, 64 yours on the phone's screen...). `src`
    is a URL; with none the tile is an empty dashed square. */
export function RoleArt({ src, size = 34, yours = false, def = false, title, onClick }) {
  const style = { width: size, height: size, backgroundImage: src ? 'url("' + src + '")' : undefined };
  const cls = "mgcp-rl-art" + (yours ? " yours" : "") + (def ? " def" : "") + (src ? "" : " none");
  if (onClick) {
    return <button type="button" className={cls} style={style} title={title} aria-label={title} onClick={onClick} />;
  }
  return <span className={cls} style={style} title={title} aria-hidden={title ? undefined : "true"} />;
}

/** The pair for one image: the pack's default (dimmed, smaller) then yours (outlined) when it is
    overridden; just the current art, at full strength, when it is not. `big` is the phone's
    44 -> 64 px pair. `onAskDefault` makes the dimmed default tappable (the one-time ask). */
export function RolePair({ img, big = false, onAskDefault }) {
  const cur = big ? 64 : 34, def = big ? 44 : 28;
  if (!img.yours) return <RoleArt src={imageUrl(img)} size={big ? 64 : 34} title={img.label} />;
  return (
    <>
      {img.default_url
        ? <RoleArt src={img.default_url} size={def} def title={"Use the default " + img.label.toLowerCase()}
            onClick={onAskDefault} />
        : null}
      {img.default_url ? <span className="mgcp-rl-arrow" aria-hidden="true">→</span> : null}
      <RoleArt src={imageUrl(img)} size={cur} yours title={"Your " + img.label.toLowerCase()} />
    </>
  );
}

/** The live rule line once a file has landed: ✓ emerald, ✕ peach, one per rule. */
export function RoleTicks({ list }) {
  return (
    <span className="mgcp-rl-ticks">
      {list.map((t) => (
        <span key={t.rule} className={t.ok ? "ok" : "bad"}>{(t.ok ? "✓ " : "✕ ") + t.text}</span>
      ))}
    </span>
  );
}

/** The loud peach refusal (the Branding Workshop's): the rule and the measured value. */
export function RoleLoud({ children }) {
  return children ? <div className="mgcp-rl-loud" role="alert">{children}</div> : null;
}

/** The one-time ask before the pack's default comes back. */
export function RestoreAsk({ role, img, busy, onKeep, onUse, big = false }) {
  return (
    <div className={"mgcp-rl-ask" + (big ? " big" : "")} role="alertdialog" aria-label={restoreAsk(role, img)}>
      <div>{restoreAsk(role, img)}</div>
      <div>{RESTORE_BODY}</div>
      <div className="mgcp-rl-askbtns">
        <button type="button" className="mgcp-rl-ghost" onClick={onKeep} disabled={busy}>Keep mine</button>
        <button type="button" className="mgcp-rl-primary" onClick={onUse} disabled={busy}>Use default</button>
      </div>
    </div>
  );
}

/** The role in its real home (the handoff's preview): a mini sign-in card, the tracker's rows in
    each state with the spinner turning, the toast ribbon and header gift box, the power modal.
    `cand` is the candidate's object URL once every rule passed, else null (the current art). */
export function RolePreview({ role, candKey, candUrl }) {
  const url = (img) => (candUrl && img.key === candKey ? candUrl : imageUrl(img));
  const by = (k) => role.images.find((i) => i.key === k);
  const bg = (img) => ({ backgroundImage: 'url("' + url(img) + '")' });
  let body = null, note = "";
  if (role.slot === "login_companion") {
    note = "Preview · the sign-in page";
    body = (
      <div className="mgcp-rl-pv login"><span className="mgcp-rl-pvnel" style={bg(by("companion"))} /></div>
    );
  } else if (role.slot === "tracker_mascots") {
    note = "Preview · the job tracker";
    body = (
      <div className="mgcp-rl-pv tracker">
        {[["spinner", "Running", true], ["done", "Done"], ["failed", "Failed"], ["empty", "Nothing yet"]].map(([k, label, spin]) => (
          <div className="mgcp-rl-trow" key={k}>
            <span className={"mgcp-rl-tnel" + (spin ? " spin" : "")} style={bg(by(k))} />
            <span>{label}</span>
          </div>
        ))}
      </div>
    );
  } else if (role.slot === "reward_icons") {
    note = "Preview · the toast ribbon and the header";
    body = (
      <div className="mgcp-rl-pv rewards">
        <div className="mgcp-rl-ribbon"><span className="mgcp-rl-ico" style={bg(by("gift"))} /> Reward: 500 credits</div>
        <div className="mgcp-rl-chip"><span className="mgcp-rl-ico" style={bg(by("claim"))} /> Claim</div>
      </div>
    );
  } else if (role.slot === "power_poses") {
    note = "Preview · the power screen";
    body = (
      <div className="mgcp-rl-pv power">
        {[["restart", "Restarting the Athenaeum"], ["shutdown", "The Athenaeum is dark"]].map(([k, label]) => (
          <div className="mgcp-rl-pcard" key={k}>
            <span className={"mgcp-rl-pnel" + (k === "shutdown" ? " off" : "")} style={bg(by(k))} />
            <span>{label}</span>
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="mgcp-rl-previewrow">
      {body}
      <div className="mgcp-rl-pvnote">{note}{"\n"}{candUrl ? "(your picture)" : "(shows your picture once it passes every check)"}</div>
    </div>
  );
}
