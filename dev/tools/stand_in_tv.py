"""A stand-in Apple TV for walking "Pair a TV" before the real TV app exists.

It does what the TV client will do, over the gallery's real pairing routes, and shows the
result as a page another device can open:

  1. POST /api/pair/start  -> a six-letter code, shown big on the page (like the TV's screen)
  2. GET  /api/pair/poll   -> every 2 s until someone approves the code in Control Panel
  3. with the key it was handed: GET /api/gallery-images (Authorization: Bearer), and the
     thumbnails, so the page shows your newest pictures the way the TV would
  4. a 401 means the TV was revoked: it drops the key and asks for a new code

Run it on the PC that runs the gallery, from the app folder (stdlib only):

    pythonw dev\\tools\\stand_in_tv.py [--server https://10.0.0.49:5057] [--port 5058]

then open http://<this PC's address>:5058 on the device you walk with. It talks to the
gallery over https:// on the PC's own network address (pairing refuses plain http from
another device, and this PC's loopback is never allowed a TV key), and it trusts only the
app's own certificate authority, local\\tls_ca_cert.pem. The key lives in memory only: stop
the stand-in and it is gone (revoke the row it left in Control Panel > Accounts).
"""
import argparse
import html
import json
import os
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(os.path.dirname(HERE))

state = {"phase": "starting", "code": "", "pair_id": "", "expires": 0.0, "token": "",
         "total": None, "images": [], "note": "", "paired_at": None}
lock = threading.Lock()


def _ctx(ca):
    c = ssl.create_default_context(cafile=ca)
    return c


def _call(server, ctx, method, path, body=None, token=""):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(server + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            raw = r.read()
            return r.status, raw, r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "")


def _json(raw):
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def tv_loop(server, ctx, label):
    while True:
        with lock:
            phase = state["phase"]
        try:
            if phase in ("starting", "expired", "revoked"):
                st, raw, _ = _call(server, ctx, "POST", "/api/pair/start", {})
                j = _json(raw)
                if st == 200 and j.get("code"):
                    with lock:
                        state.update(phase="waiting", code=j["code"], pair_id=j["pair_id"],
                                     expires=time.time() + float(j.get("expires_in") or 600),
                                     note="" if phase == "starting" else (
                                         "The last code ran out." if phase == "expired"
                                         else "This TV was revoked, so it asks to pair again."))
                else:
                    with lock:
                        state["note"] = "Couldn't get a code (%s): %s" % (st, j.get("error", ""))
                    time.sleep(30)
                    continue
            elif phase == "waiting":
                st, raw, _ = _call(server, ctx, "GET",
                                   "/api/pair/poll?pair_id=" + state["pair_id"])
                j = _json(raw)
                if st == 200 and j.get("status") == "approved" and j.get("token"):
                    with lock:
                        state.update(phase="paired", token=j["token"], code="", pair_id="",
                                     paired_at=time.time(), note="")
                    continue
                if st == 200 and j.get("status") == "expired":
                    with lock:
                        state["phase"] = "expired"
                    continue
                if st == 429:
                    time.sleep(10)
            elif phase == "paired":
                st, raw, _ = _call(server, ctx, "GET", "/api/gallery-images?limit=6",
                                   token=state["token"])
                if st == 401:
                    with lock:
                        state.update(phase="revoked", token="", total=None, images=[])
                    continue
                j = _json(raw)
                if st == 200:
                    with lock:
                        state["total"] = j.get("total")
                        state["images"] = [i.get("media_id") for i in j.get("images", [])][:6]
                        state["note"] = ""
                else:
                    with lock:
                        state["note"] = "The gallery answered %s: %s" % (st, j.get("error", ""))
                time.sleep(5)
                continue
        except Exception as e:  # network blips: say so on the page, keep going
            with lock:
                state["note"] = "Can't reach the gallery: %s" % e
            time.sleep(5)
            continue
        time.sleep(2)


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="2"><title>Stand-in TV</title>
<style>
body{margin:0;background:#0b0d18;color:#e6e4f0;font:16px/1.5 system-ui,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:40px 20px;text-align:center}
.tag{font:500 12px/1 ui-monospace,monospace;letter-spacing:.14em;text-transform:uppercase;color:#b9a8ff}
h1{font-weight:400;font-size:28px;margin:14px 0}
.code{display:flex;justify-content:center;gap:10px;margin:28px 0;flex-wrap:wrap}
.code span{display:inline-grid;place-items:center;width:64px;height:84px;border:1px solid #3a3e60;
 border-radius:10px;background:#171a2e;font:500 44px ui-monospace,monospace}
.code i{align-self:center;color:#6f6d8c;font-style:normal;font-size:32px}
.muted{color:#a3a1bd}.note{color:#f2c46d;margin-top:18px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px;margin-top:24px}
.grid img{width:100%;aspect-ratio:1;object-fit:cover;border-radius:8px;background:#171a2e}
</style></head><body><div class="wrap"><div class="tag">Stand-in TV &middot; walk only</div>
%s</div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_url = ""
    ctx = None

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/thumb/"):
            mid = "".join(ch for ch in self.path[7:] if ch.isalnum() or ch in "-_")
            with lock:
                tok = state["token"]
            if not tok or not mid:
                self.send_error(404)
                return
            st, raw, ctype = _call(self.server_url, self.ctx, "GET", "/thumbs/%s.jpg" % mid,
                                   token=tok)
            if st != 200:
                self.send_error(st)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype or "image/jpeg")
            self.send_header("Cache-Control", "max-age=300")
            self.end_headers()
            self.wfile.write(raw)
            return
        with lock:
            s = dict(state)
        if s["phase"] == "waiting":
            c = s["code"]
            cells = "".join("<span>%s</span>" % html.escape(ch) for ch in c[:3]) + "<i>&ndash;</i>" + \
                "".join("<span>%s</span>" % html.escape(ch) for ch in c[3:])
            left = max(0, int(s["expires"] - time.time()))
            body = ("<h1>Pair this TV</h1><p class='muted'>On your phone or computer: Control Panel "
                    "&rsaquo; Accounts &rsaquo; Pair a TV&hellip;, and type this code.</p>"
                    "<div class='code'>%s</div><p class='muted'>This code lasts %d:%02d more.</p>"
                    % (cells, left // 60, left % 60))
        elif s["phase"] == "paired":
            imgs = "".join("<img alt='' src='/thumb/%s'>" % html.escape(m) for m in s["images"])
            total = "" if s["total"] is None else "%s pictures in your library." % s["total"]
            body = ("<h1>Paired</h1><p class='muted'>The TV is reading your gallery with its own key. "
                    "%s Your newest:</p><div class='grid'>%s</div>" % (html.escape(str(total)), imgs))
        else:
            body = "<h1>Getting a code&hellip;</h1>"
        if s["note"]:
            body += "<p class='note'>%s</p>" % html.escape(s["note"])
        out = (PAGE % body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--server", default="https://10.0.0.49:5057")
    ap.add_argument("--port", type=int, default=5058)
    ap.add_argument("--ca", default=os.path.join(APP, "local", "tls_ca_cert.pem"))
    ap.add_argument("--label", default="Apple TV")
    a = ap.parse_args()
    ctx = _ctx(a.ca)
    Handler.server_url = a.server.rstrip("/")
    Handler.ctx = ctx
    threading.Thread(target=tv_loop, args=(Handler.server_url, ctx, a.label), daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
