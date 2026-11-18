/* "Connect from PixAI" -- the bookmark the Mirror to PixAI tile offers (2026-11-18).

   PixAI keeps its sign-in where no outside program can read it, so the Mirror's Connect can no
   longer fetch it from this machine's browser. Instead the user drags this link to the
   bookmarks bar and clicks it on a signed-in pixai.art tab. There it:
     1. refuses to run anywhere but https://pixai.art;
     2. opens THIS Moonglade's /mirror/connect page (the origin is baked in when the tile
        renders, so a bookmark made from the Mac on the PC's LAN address points back there) --
        opened first, while the click still counts, so no pop-up blocker objects;
     3. asks pixai.art for the tab's current sign-in, exactly as the page itself does;
     4. answers the page's ready ping -- only from that window, only from that origin -- with
        postMessage to that exact origin, never "*";
     5. gives up cleanly after ten minutes (the page may sit behind a Moonglade sign-in), and
        says so; and stops at once, saying why, if the window could not open at all.
   The page then checks the sign-in on the server (same PixAI account as the API key, or it is
   refused) and shows the result. */

const BODY = `(function(){var M=__ORIGIN__,P="https://pixai.art";
if(location.origin!==P){alert("Click this bookmark on a pixai.art tab, signed in to PixAI.");return}
var w=window.open(M+"/mirror/connect","moonglade_connect","popup,width=480,height=640");
if(!w||w.closed){alert("Moonglade's window couldn't open. If your browser blocked a pop-up, allow pop-ups for pixai.art, then click the bookmark again.");return}
var t=null,sent=0,k;
function stop(){clearTimeout(k);removeEventListener("message",h)}
function h(e){if(sent||!t||e.source!==w||e.origin!==M||!e.data||e.data.type!=="moonglade-mirror-ready")return;
sent=1;stop();w.postMessage({type:"moonglade-mirror-token",token:t},M);t=null}
addEventListener("message",h);
k=setTimeout(function(){stop();if(!sent)alert("Moonglade didn't answer. Check that it is running and you are signed in to it, then click the bookmark again.")},600000);
fetch("https://api.pixai.art/v2/auth/refresh-token",{method:"POST",credentials:"include",headers:{"content-type":"application/json"},body:"{}"})
.then(function(r){if(!r.ok)throw r.status;return r.json()})
.then(function(d){if(!d||typeof d.token!=="string"||!d.token)throw 0;t=d.token})
.catch(function(s){stop();try{w.close()}catch(e){}alert("Sign in to PixAI in this tab first"+(typeof s==="number"&&s?" (PixAI answered "+s+")":"")+".")})})();`;

/** The bookmark's href for a Moonglade reached at `origin` (window.location.origin). */
export function mirrorBookmarklet(origin) {
  const code = BODY.replace("__ORIGIN__", JSON.stringify(String(origin || ""))).replace(/\n/g, "");
  return "javascript:" + encodeURIComponent(code);
}
