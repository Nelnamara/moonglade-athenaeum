import React from "react";
import "../styles/claim-modal.css";

/* Daily-claim popup -- see useClaimModal.js's own header comment for cadence/
   dismiss reasoning. Structurally modeled on PowerModal (ControlPanelOverlay.jsx):
   scrim + host + centered card + mascot-in-a-halo, same shell shape -- but its
   own class namespace (mgclaim-*, claim-modal.css) since this is an app-wide
   overlay, not a Control-Panel one, and unlike Power modal this one IS
   dismissible by backdrop click (a missed free reward is not a mid-restart
   action -- nothing to protect against an accidental close). */

export default function ClaimModal({ credits, exiting, claiming, error, onClaim, onDismiss }) {
  return (
    <>
      <div className={"mgclaim-scrim" + (exiting ? " exiting" : "")} onClick={onDismiss} />
      <div className="mgclaim-host">
        <div className={"mgclaim-card" + (exiting ? " exiting" : "")} role="dialog" aria-label="Claim your free credits">
          <button type="button" className="mgclaim-x" onClick={onDismiss} aria-label="Not now">×</button>

          <div className="mgclaim-mascotwrap">
            <div className="mgclaim-halo" />
            <img className="mgclaim-mascot" src="/branding/mascots/nel_redeem.webp" alt=""
              data-fb="0"
              onError={(e) => {
                const img = e.currentTarget;
                const tried = Number(img.dataset.fb || 0);
                // webp -> still png -> the general narrator, same fallback-ladder
                // shape LoginPage.jsx's MASCOT_FALLBACKS already establishes.
                const ladder = ["/branding/mascots/nel_redeem.png", "/branding/mascots/nel_narrator.png"];
                if (tried < ladder.length) { img.dataset.fb = String(tried + 1); img.src = ladder[tried]; }
                else img.style.display = "none";
              }} />
            {exiting && <div className="mgclaim-coin" aria-hidden="true" />}
          </div>

          <div className="mgclaim-title">Free credits, waiting</div>
          <div className="mgclaim-amount">+{Number(credits || 0).toLocaleString()}</div>
          <div className="mgclaim-line">Ready to claim — free, no cost, no catch.</div>

          {error && <div className="mgclaim-err">{error}</div>}

          <button type="button" className="mgclaim-primary" onClick={onClaim} disabled={claiming || exiting}>
            {claiming ? "Claiming…" : "Claim now"}
          </button>
          <div className="mgclaim-hint">or close this — the credits stay ready, no rush</div>
        </div>
      </div>
    </>
  );
}
