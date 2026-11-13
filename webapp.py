#!/usr/bin/env python3
"""SD-WAN collector – web page (Python standard library only).

  python webapp.py                 # opens http://127.0.0.1:5050 in your browser
  python webapp.py --port 8080     # different port
  python webapp.py --host 0.0.0.0  # allow other machines (NOT recommended: credentials cross the network)

The password is used once to log in, kept only in memory, and never written anywhere.
The live page is shared with the assessor web app (`sdwan_core/live_ui.py`).
"""
from __future__ import annotations

import argparse
import html
import json
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from collect import OUT_DIR, VERSION, collector, live_ui, run_collection

JOBS: dict[str, dict] = {}
TITLE = "SD-WAN Health Check Collector"
describe, CAT = live_ui.describe, live_ui.CAT  # re-exported for tests


def page(body: str, refresh: bool = False, script: str = "") -> bytes:
    return live_ui.page(TITLE, body, VERSION, refresh, script)


FORM = f"""<div class=card><form method=post action=/start autocomplete=off>
<label>Customer name</label><input type=text name=customer required>
{live_ui.connection_fields()}
<button>▶ Start collection</button></form>
<div class=note>Only read (GET) requests are sent – nothing on the Manager is changed. The password is used to log in and is never stored.
Passwords, keys and tokens are replaced with “[redacted]” before anything is saved. A read-only Manager account is enough.</div></div>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "sdwan-collector"

    def log_message(self, *a):  # keep the console quiet (and never log form data)
        pass

    def _send(self, body: bytes, code=200, ctype="text/html; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            return self._send(page(FORM))
        if self.path.startswith("/status/"):
            j = JOBS.get(self.path.split("/")[2])
            if not j:
                return self._send(b'{"state":"unknown"}', 404, "application/json")
            return self._send(json.dumps(live_ui.status(j)).encode(), 200, "application/json")
        if self.path.startswith("/job/"):
            jid = self.path.split("/")[2]
            j = JOBS.get(jid)
            if not j:
                return self._send(page("<div class=card><p>Unknown job. <a class=btn href=/>Start again</a></p></div>"), 404)
            st, err, out = j["state"], j["error"], j.get("file", "")
            log = html.escape("\n".join(live_ui.status(j)["log"]))
            if st == "done":
                name = html.escape(Path(out).name)
                body = (f"<div class=card><h2 class=ok>✔ Collection complete</h2>{live_ui.summary_html(j)}"
                        f"<p>File: <b>{name}</b><br><small>Saved in {html.escape(str(OUT_DIR))}</small></p>"
                        f"<a class=btn href=/download/{html.escape(jid)}>⬇ Download the zip</a> "
                        f"<a class='btn alt' href=/>New collection</a>"
                        f"<div class=note><b>Next:</b> send this zip to your Cisco Customer Success Specialist (CSS) engineer, using the secure method they "
                        f"give you. Please don't post it in public places or chat rooms. You can open it first to review exactly what is inside "
                        f"(README.txt and raw/*.json); passwords and keys are already replaced with [redacted].</div>"
                        f"<h3>Console</h3><div class=log>{log}</div></div>")
                return self._send(page(body))
            if st == "failed":
                return self._send(page(f"<div class=card><h2 class=err>✖ Collection failed</h2><p>{html.escape(err)}</p>"
                                       f"<a class=btn href=/>Try again</a><h3>Console</h3><div class=log>{log}</div></div>"))
            return self._send(page(live_ui.running_html(j), refresh=True, script=live_ui.script(jid)))
        if self.path.startswith("/download/"):
            j = JOBS.get(self.path.split("/")[2])
            if not j or j["state"] != "done":
                return self._send(b"not found", 404, "text/plain")
            p = Path(j["file"]).resolve()
            if OUT_DIR.resolve() not in p.parents:  # only files the collector wrote
                return self._send(b"not found", 404, "text/plain")
            return self._send(p.read_bytes(), 200, "application/zip",
                              {"Content-Disposition": f'attachment; filename="{p.name}"'})
        self._send(b"not found", 404, "text/plain")

    def do_POST(self):
        if self.path != "/start":
            return self._send(b"not found", 404, "text/plain")
        n = int(self.headers.get("Content-Length") or 0)
        f = {k: v[0] for k, v in parse_qs(self.rfile.read(min(n, 65536)).decode()).items()}
        try:
            url = live_ui.manager_url(f.get("host") or f.get("url", ""), f.get("port") or 443)
        except ValueError as e:
            return self._send(page(f"<div class=card><p class=err>{html.escape(str(e))}</p><a class=btn href=/>Back</a></div>"), 400)
        jid = uuid.uuid4().hex[:10]
        JOBS[jid] = live_ui.new_job(live_ui.COLLECTOR_PHASES, file="")
        args = (jid, url, f.get("username", ""), f.get("password", ""), f.get("customer", "customer"),
                not f.get("insecure"), int(f.get("max_edges") or 100), int(f.get("workers") or 20))
        threading.Thread(target=worker, args=args, daemon=True).start()
        self.send_response(303)
        self.send_header("Location", f"/job/{jid}")
        self.end_headers()


def worker(jid, url, user, pw, customer, verify, max_edges, workers):
    j = JOBS[jid]
    log, progress = live_ui.hooks(j)
    try:
        path = run_collection(url, user, pw, customer, verify, None, max_edges, workers, progress, log,
                              lambda n: live_ui.expect(j, n))
        live_ui.finish(j, "done", file=str(path))
    except collector.LoginError as e:
        live_ui.finish(j, "failed", f"Login failed: {e}")
    except Exception as e:
        msg = str(e)
        if "CERTIFICATE_VERIFY_FAILED" in msg:
            msg = "The Manager's TLS certificate is not trusted by this computer. Tick 'Skip TLS certificate check'."
        live_ui.finish(j, "failed", f"{type(e).__name__}: {msg[:300]}")
    finally:
        pw = None  # drop the password reference


def main():
    import logging
    logging.basicConfig(level=logging.ERROR, format="%(message)s")
    ap = argparse.ArgumentParser(description="SD-WAN collector web page")
    ap.add_argument("--host", default="127.0.0.1", help="Listen address (default 127.0.0.1 = this computer only)")
    ap.add_argument("--port", type=int, default=5050)
    ap.add_argument("--no-browser", action="store_true", help="Don't open the browser automatically")
    a = ap.parse_args()
    if a.host not in ("127.0.0.1", "localhost"):
        print("WARNING: listening on", a.host, "– other machines can reach this page and credentials would cross the network without TLS.")
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = f"http://{'127.0.0.1' if a.host in ('0.0.0.0', '') else a.host}:{a.port}"
    print(f"SD-WAN Health Check Collector v{VERSION} running at {url}  (Ctrl+C to stop)")
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
