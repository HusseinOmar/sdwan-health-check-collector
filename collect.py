#!/usr/bin/env python3
"""SD-WAN collector – command line.

Collects read-only data from Cisco Catalyst SD-WAN Manager and writes one zip for the
SD-WAN assessor. Nothing on the Manager is changed (GET requests only).

Examples
  python collect.py --url https://vmanage.example.com -u readonly-user --customer "ACME"
  python collect.py --url https://10.1.1.1:8443 -u admin --customer ACME --insecure      (lab / self-signed)
The password is asked for (hidden), or read from the SDWAN_PW environment variable.
"""
from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
import time
from pathlib import Path

try:  # packaged collector: core modules are shipped in ./sdwan_core
    from sdwan_core import bundle, collector, endpoints, live_ui
except ImportError:  # running inside the assessor repo during development
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from sdwan_assessor import bundle, collector, endpoints, live_ui  # type: ignore

HERE = Path(__file__).resolve().parent
VERSION = (HERE / "VERSION").read_text().strip() if (HERE / "VERSION").exists() else "dev"
OUT_DIR = HERE / "output"


def run_collection(url: str, username: str, password: str, customer: str, verify_tls: bool = True,
                   ca_bundle: str | None = None, max_edges: int = 100, workers: int = 20,
                   progress=None, log=None) -> Path:
    """Login once, collect everything, write the bundle zip, log out. Returns the zip path."""
    say = log or (lambda m: None)
    c = collector.Collector(url, username, password, verify_tls=verify_tls, workers=workers)
    if ca_bundle:  # corporate CA bundle for TLS verification
        c.verify_tls = ca_bundle
        c.session.verify = ca_bundle
    t0 = time.monotonic()
    try:
        say("Logging in…")
        c.login()
        say("Logged in. Collecting fabric-wide data…")
        res = c.collect(endpoints.ENDPOINTS, progress)
        devs = next((r.data.get("data", []) for r in res if r.key == "devices" and r.ok), [])
        say(f"{len(devs)} devices found. Collecting per-device data…")
        res += c.collect_per_device(devs, endpoints.PER_DEVICE, max_edges, progress, bulk=endpoints.BULK)
        ids = endpoints.template_ids(res)
        say(f"Reading {len(ids)} device templates…")
        res += [c.collect_per_id(k, t, ids, progress) for k, t in endpoints.PER_TEMPLATE]
        jobs = endpoints.config_group_jobs(res)
        say(f"Reading {len(jobs[0][1])} configuration groups and {len(jobs[1][1])} feature profiles…")
        res += [c.collect_paths(k, p, progress) for k, p in jobs]
        res.append(c.collect_paths("feature_parcels", endpoints.parcel_jobs(res), progress))
    finally:
        c.logout()
    ok = sum(r.ok for r in res)
    say(f"Collected {ok}/{len(res)} data sets in {time.monotonic() - t0:.0f} s. Writing the bundle…")
    path = bundle.write_bundle(OUT_DIR, customer, c.base_url, username, res,
                               {"name": "sdwan-collector", "version": VERSION})
    say(f"Done: {path}")
    return path


def main() -> int:
    logging.basicConfig(level=logging.ERROR, format="%(message)s")  # keep the console clean for end users
    ap = argparse.ArgumentParser(description="Read-only SD-WAN data collector for the SD-WAN assessor.")
    ap.add_argument("--url", "--host", dest="url", required=True, help="SD-WAN Manager name or IP (https is implied)")
    ap.add_argument("--port", default=443, help="Manager HTTPS port (default 443)")
    ap.add_argument("-u", "--username", required=True)
    ap.add_argument("--customer", required=True, help="Customer name (used in the file name)")
    ap.add_argument("--verify-tls", action="store_true", help="Check the Manager's TLS certificate (default: skipped)")
    ap.add_argument("--insecure", action="store_true", help=argparse.SUPPRESS)  # old flag; skipping is now the default
    ap.add_argument("--ca-bundle", help="Path to a corporate CA bundle (.pem) for TLS verification")
    ap.add_argument("--max-edges", type=int, default=100, help="Edges sampled for per-device data (default 100)")
    ap.add_argument("--workers", type=int, default=20, help="Parallel API calls (default 20; lower for busy Managers)")
    a = ap.parse_args()

    url = live_ui.manager_url(a.url, a.port)
    pw = os.environ.get("SDWAN_PW") or getpass.getpass(f"Password for {a.username}@{url}: ")
    last = [0.0]

    def progress(i, n, key):
        if time.monotonic() - last[0] > 0.5 or i == n:
            last[0] = time.monotonic()
            print(f"\r  {i}/{n}  {key[:60]:<60}", end="", flush=True)
            if i == n:
                print()

    try:
        path = run_collection(url, a.username, pw, a.customer, a.verify_tls or bool(a.ca_bundle), a.ca_bundle,
                              a.max_edges, a.workers, progress, log=print)
    except collector.LoginError as e:
        print(f"\nLogin failed: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # plain-language error, no stack trace for end users
        msg = str(e)
        if "CERTIFICATE_VERIFY_FAILED" in msg:
            msg = "TLS certificate not trusted. Use --ca-bundle <your-ca.pem>, or leave out --verify-tls."
        print(f"\nCollection failed: {type(e).__name__}: {msg}", file=sys.stderr)
        return 1
    print(f"\nSend this file to your Cisco team:\n  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
