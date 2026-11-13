"""Read-only SD-WAN Manager collector.

Safety rules enforced in code:
- Only GET requests to /dataservice are allowed. The single exception is the
  login form POST to /j_security_check (required by Manager to authenticate).
- Credentials live only in memory for the session; never logged or saved.
- Requests are rate-limited so we don't load the customer's controllers.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests
import urllib3

log = logging.getLogger(__name__)
_SAFE_ID = re.compile(r"[A-Za-z0-9_.:-]+")


class ReadOnlyViolation(RuntimeError):
    """Raised if anything tries to send a non-GET API request."""


class LoginError(RuntimeError):
    pass


@dataclass
class EndpointResult:
    key: str
    path: str
    ok: bool
    status: int | None
    seconds: float
    data: Any = None
    error: str | None = None


@dataclass
class Collector:
    base_url: str
    username: str
    password: str = field(repr=False)
    verify_tls: bool = True
    workers: int = 20          # parallel API calls
    max_retries: int = 3       # on HTTP 429/503 (Manager busy) with exponential back-off
    timeout: tuple[int, int] = (10, 90)
    session: requests.Session = field(default_factory=requests.Session, repr=False)
    _token: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if not self.base_url.startswith("https://"):
            raise ValueError("Manager URL must start with https://")
        self.session.verify = self.verify_tls
        from requests.adapters import HTTPAdapter
        ad = HTTPAdapter(pool_connections=4, pool_maxsize=max(self.workers, 10))
        self.session.mount("https://", ad)
        if not self.verify_tls:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # --- auth -----------------------------------------------------------
    def login(self) -> None:
        for attempt in range(self.max_retries + 1):
            r = self.session.post(
                f"{self.base_url}/j_security_check",
                data={"j_username": self.username, "j_password": self.password},
                timeout=self.timeout,
                allow_redirects=False,
                verify=self.verify_tls,
            )
            if r.status_code not in (429, 503) or attempt == self.max_retries:
                break
            time.sleep(min(2 ** (attempt + 1), 10))  # Manager busy/starting: back off
        # Successful login returns 200 with empty body; failure returns HTML.
        if r.status_code != 200 or "<html" in r.text.lower():
            msg = ("Manager is busy or unavailable (HTTP 503) – try again in a few minutes."
                   if r.status_code in (429, 503) else "Check URL and credentials.")
            raise LoginError(f"Login failed (HTTP {r.status_code}). {msg}")
        t = self.session.get(f"{self.base_url}/dataservice/client/token", timeout=self.timeout,
                             verify=self.verify_tls)
        if t.status_code == 200 and t.text and "<html" not in t.text.lower():
            self._token = t.text.strip()
            self.session.headers["X-XSRF-TOKEN"] = self._token
        self.password = ""  # drop it from memory once we are in

    def logout(self) -> None:
        try:  # GET logout is read-only and ends the session on the Manager
            self.session.get(f"{self.base_url}/logout", timeout=(5, 15), allow_redirects=False,
                             verify=self.verify_tls)
        except requests.RequestException:
            pass

    # --- read-only request ---------------------------------------------
    def request(self, method: str, path: str, **kw: Any) -> requests.Response:
        if method.upper() != "GET":
            raise ReadOnlyViolation(f"Blocked {method} {path}: collector is read-only")
        if not path.startswith("/dataservice/"):
            raise ReadOnlyViolation(f"Blocked path outside /dataservice: {path}")
        # verify passed explicitly: env REQUESTS_CA_BUNDLE would otherwise override session.verify
        for attempt in range(self.max_retries + 1):
            r = self.session.get(f"{self.base_url}{path}", timeout=self.timeout, verify=self.verify_tls, **kw)
            if r.status_code not in (429, 503) or attempt == self.max_retries:
                return r
            ra = r.headers.get("Retry-After", "")
            time.sleep(min(float(ra), 30) if ra.replace(".", "", 1).isdigit() else min(2 ** attempt, 8))  # Manager busy
        return r

    def get(self, key: str, path: str) -> EndpointResult:
        t0 = time.monotonic()
        try:
            r = self.request("GET", path)
            dt = time.monotonic() - t0
            if r.status_code != 200:
                return EndpointResult(key, path, False, r.status_code, dt, error=r.text[:200])
            try:
                body = r.json()
            except ValueError:
                # Some endpoints (device config) return text/HTML: keep it as text.
                body = {"text": r.text, "content_type": r.headers.get("content-type", "")}
            return EndpointResult(key, path, True, 200, dt, data=body)
        except ReadOnlyViolation:
            raise
        except requests.RequestException as e:
            return EndpointResult(key, path, False, None, time.monotonic() - t0, error=str(e)[:200])

    def collect(
        self,
        endpoints: list[tuple[str, str, str]],
        progress: Callable[[int, int, str], None] | None = None,
    ) -> list[EndpointResult]:
        jobs = [(key, path) for key, _cat, path in endpoints]
        res = self._parallel(jobs, lambda j: self.get(*j), progress, lambda j: j[0])
        for r in res:
            log.info("%s %s %s", "OK " if r.ok else "ERR", r.status, r.path)
        return res

    def _parallel(self, jobs, fn, progress=None, label=lambda j: str(j)):
        """Run fn(job) for every job on `workers` threads; results keep the job order."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        out = [None] * len(jobs)
        done = 0
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futs = {ex.submit(fn, j): i for i, j in enumerate(jobs)}
            for f in as_completed(futs):
                i = futs[f]
                out[i] = f.result()
                done += 1
                if progress:
                    progress(done, len(jobs), label(jobs[i]))
        return out

    def collect_paths(self, key: str, paths: dict[str, str],
                      progress: Callable[[int, int, str], None] | None = None) -> EndpointResult:
        """One GET per id with its own path ({id: path}); data = {"per_id": {id: body}}. Unsafe ids are skipped."""
        items = [(i, p) for i, p in paths.items() if i and _SAFE_ID.fullmatch(str(i)) and p.startswith("/dataservice/")]
        t0 = time.monotonic()
        res = self._parallel(items, lambda ip: self.get(key, ip[1]), progress, lambda ip: f"{key} {ip[0]}")
        got = {i: r.data for (i, _), r in zip(items, res) if r.ok}
        errs = [f"{i}: {r.status}" for (i, _), r in zip(items, res) if not r.ok]
        ok = bool(got) or not items
        return EndpointResult(key, "per-id paths", ok, 200 if ok else None, time.monotonic() - t0,
                              data={"per_id": got, "requested": len(items)} if ok else None,
                              error=(f"{len(errs)}/{len(items)} not read: " + "; ".join(errs))[:200] if errs else None)

    def collect_per_id(self, key: str, tmpl: str, ids: list[str],
                       progress: Callable[[int, int, str], None] | None = None) -> EndpointResult:
        """One GET per id (tmpl has {id}); data = {"per_id": {id: body}}. One failure is recorded, not fatal."""
        ids = [i for i in dict.fromkeys(ids) if i and _SAFE_ID.fullmatch(str(i))]
        t0 = time.monotonic()
        res = self._parallel(ids, lambda i: self.get(key, tmpl.format(id=i)), progress, lambda i: f"{key} {i}")
        got = {i: r.data for i, r in zip(ids, res) if r.ok}
        errs = [f"{i}: {r.status}" for i, r in zip(ids, res) if not r.ok]
        ok = bool(got) or not ids
        return EndpointResult(key, tmpl, ok, 200 if ok else None, time.monotonic() - t0,
                              data={"per_id": got, "requested": len(ids)} if ok else None,
                              error="; ".join(errs)[:200] or None)

    def get_bulk(self, key: str, state_type: str, page: int = 1000) -> EndpointResult:
        """Bulk state API: one data type for ALL devices, paged by startId/moreEntries."""
        t0, rows, start = time.monotonic(), [], None
        for _ in range(1000):  # safety cap: 1M rows
            q = f"?count={page}" + (f"&startId={start}" if start else "")
            r = self.get(key, f"/dataservice/data/device/state/{state_type}{q}")
            if not r.ok or not isinstance(r.data, dict) or "data" not in r.data:
                return EndpointResult(key, f"bulk:{state_type}", False, r.status, time.monotonic() - t0, error=r.error)
            rows += r.data["data"]
            pi = r.data.get("pageInfo") or {}
            nxt = pi.get("endId")
            if not pi.get("moreEntries") or not nxt or nxt == start:
                break  # no further page, or the Manager did not advance the cursor
            start = nxt
        return EndpointResult(key, f"bulk:{state_type}", True, 200, time.monotonic() - t0, data=rows)

    def collect_per_device(
        self,
        devices: list[dict],
        per_device: list[tuple[str, str, str, str]],
        max_edges: int = 100,
        progress: Callable[[int, int, str], None] | None = None,
        bulk: dict[str, tuple[list[str], list[str]]] | None = None,
    ) -> list[EndpointResult]:
        """One aggregated result per key: data = {"per_device": {host-name: {"data": rows}}}.

        Keys listed in `bulk` are fetched with the bulk state API (all devices, few calls);
        if bulk fails for a key, it falls back to one call per device.
        """
        bulk = bulk or {}
        ctrl = [d for d in devices if d.get("personality") in ("vsmart", "vbond", "vmanage")]
        edges = [d for d in devices if d.get("personality") == "vedge" and d.get("reachability") == "reachable"]
        edges = sorted(edges, key=lambda d: str(d.get("host-name")))[:max_edges]
        scopes = {"controllers": ctrl, "edges": edges, "all": ctrl + edges}
        host_of = {d.get("system-ip"): d.get("host-name") for d in devices}
        scope_of = {k: sc for k, _c, _t, sc in per_device}

        # 1) bulk keys, in parallel
        bulk_res: dict[str, EndpointResult] = {}
        bjobs = [(k, t) for k, (types, _req) in bulk.items() if k in scope_of for t in types]
        for (k, t), r in zip(bjobs, self._parallel(bjobs, lambda j: self.get_bulk(*j), progress, lambda j: f"bulk {j[1]}")):
            if not r.ok:
                continue
            prev = bulk_res.get(k)
            if prev:
                prev.data += r.data
            else:
                bulk_res[k] = r
        out: dict[str, EndpointResult] = {}
        allowed = {k: {d.get("host-name") for d in scopes[sc]} | {d.get("system-ip") for d in scopes[sc]}
                   for k, sc in scope_of.items()}
        for k, r in bulk_res.items():
            have = {f for row in r.data for f in row}
            missing = [f for f in bulk[k][1] if f not in have]
            if not r.data or missing:  # empty or incomplete bulk -> per-device calls instead
                log.warning("bulk %s empty or lacks %s – falling back to per-device calls", k, missing)
                continue
            agg: dict[str, dict] = {}
            for row in r.data:
                host = row.get("vdevice-host-name") or host_of.get(row.get("vdevice-name")) or row.get("vdevice-name")
                if host not in allowed[k] and row.get("vdevice-name") not in allowed[k]:
                    continue  # keep bulk results inside the key's scope (and the max_edges sample)
                agg.setdefault(host, {"data": []})["data"].append(row)
            out[k] = EndpointResult(k, r.path, True, 200, r.seconds,
                                    data={"per_device": agg, "sampled_edges": len(edges), "source": "bulk"})

        # 2) everything else: one call per device, in parallel
        jobs = [(k, tmpl, d) for k, _c, tmpl, sc in per_device if k not in out for d in scopes[sc]]

        def one(job):
            key, tmpl, d = job
            for alt in tmpl.split("|"):  # alternatives, first success wins
                path = alt.format(sip=d.get("system-ip") or d.get("deviceId"), uuid=d.get("uuid"))
                r = self.get(key, path)
                if r.ok and not (isinstance(r.data, dict) and r.data.get("config") == "No config available"):
                    break
            return r

        t0 = time.monotonic()
        results = self._parallel(jobs, one, progress, lambda j: f"{j[0]} {j[2].get('host-name')}")
        agg2: dict[str, dict] = {}
        errs: dict[str, list[str]] = {}
        for (key, _t, d), r in zip(jobs, results):
            if r.ok:
                agg2.setdefault(key, {})[d.get("host-name") or d.get("system-ip")] = r.data
            else:
                errs.setdefault(key, []).append(f"{d.get('host-name')}: {r.status}")
        dt = time.monotonic() - t0
        for key, _c, tmpl, sc in per_device:
            if key in out:
                continue
            ok = bool(agg2.get(key)) or not scopes[sc]
            out[key] = EndpointResult(key, tmpl, ok, 200 if ok else None, dt,
                                      data={"per_device": agg2.get(key, {}), "sampled_edges": len(edges)} if ok else None,
                                      error="; ".join(errs.get(key, []))[:200] or None)
        return [out[k] for k, *_ in per_device]
