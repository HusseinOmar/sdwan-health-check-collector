"""Collection bundle: the zip a standalone collector produces and the assessor imports.

Layout (format 'sdwan-assessor-collection', schema 1):
    manifest.json        customer, manager, user (never the password), collected_utc,
                         endpoints[{key,path,ok,status,seconds,error}], format, schema, collector{name,version}
    raw/<key>.json       one redacted JSON file per data set (same layout as runs/<customer>/<ts>/raw)
    README.txt           plain-language list of what is inside, for the customer's privacy review

Shared by the assessor and the standalone collector so both always agree on the format.
"""
from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .redact import redact

FORMAT = "sdwan-assessor-collection"
SCHEMA = 3  # 2: adds device_template_objects; 3: adds licence lists (msla) + config-group devices/profiles/features
MAX_FILE = 512 * 1024 * 1024          # per file, uncompressed
MAX_TOTAL = 2 * 1024 * 1024 * 1024    # whole bundle, uncompressed
_SAFE_NAME = re.compile(r"^(manifest\.json|README\.txt|raw/[A-Za-z0-9_.-]+\.json)$")


class BundleError(ValueError):
    """The zip isn't a valid collection bundle (wrong format, unsafe paths, too large)."""


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", s).strip("-") or "customer"


def build_manifest(customer, base_url, username, results, collector=None, ts=None) -> dict:
    return {
        "format": FORMAT, "schema": SCHEMA,
        "collector": collector or {"name": "sdwan-assessor", "version": "embedded"},
        "customer": customer, "manager": base_url,
        "user": username,  # username only, never the password
        "collected_utc": ts or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
        "endpoints": [{"key": r.key, "path": r.path, "ok": r.ok, "status": r.status,
                       "seconds": round(r.seconds, 2), "error": r.error} for r in results],
    }


README = """SD-WAN assessment data collection
===================================

Customer:        {customer}
SD-WAN Manager:  {manager}
Collected (UTC): {collected}
Collector:       {cname} {cver}

What this file contains
- Read-only data from SD-WAN Manager APIs (GET requests only; nothing was changed):
  inventory, device status, control/data-plane state, statistics summaries, templates,
  configuration groups, policies and device running configurations.
- {ok} of {total} data sets were collected successfully (see manifest.json).

What it does NOT contain
- Your password (it was only used to log in and was never stored).
- Session tokens, passwords, keys, SNMP communities or password hashes:
  these were replaced with "[redacted]" before anything was written.

Review raw/*.json if you want to see exactly what is shared. Send this zip to your
Cisco team; they will import it into the assessment tool.
"""


def write_bundle(out_dir: Path, customer: str, base_url: str, username: str, results, collector: dict) -> Path:
    """Write the collection zip (data redacted before it is written)."""
    m = build_manifest(customer, base_url, username, results, collector)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"sdwan_collection_{slug(customer)}_{m['collected_utc']}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("manifest.json", json.dumps(m, indent=1))
        for r in results:
            if r.ok:
                z.writestr(f"raw/{slug(r.key)}.json", json.dumps(redact(r.data), indent=1))
        z.writestr("README.txt", README.format(
            customer=customer, manager=base_url, collected=m["collected_utc"], cname=collector.get("name"),
            cver=collector.get("version"), ok=sum(r.ok for r in results), total=len(results)))
    return path


def read_manifest(zip_path: Path) -> dict:
    """Validate a bundle and return its manifest. Raises BundleError with a plain-language reason."""
    try:
        z = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise BundleError("This file is not a valid zip archive.") from e
    with z:
        total = 0
        for i in z.infolist():
            if i.is_dir():
                continue
            if not _SAFE_NAME.match(i.filename):
                raise BundleError(f"Unexpected file in the bundle: {i.filename!r} (only manifest, README and raw/*.json are allowed).")
            if i.file_size > MAX_FILE:
                raise BundleError(f"{i.filename} is larger than allowed.")
            total += i.file_size
        if total > MAX_TOTAL:
            raise BundleError("The bundle is larger than allowed.")
        if "manifest.json" not in z.namelist():
            raise BundleError("manifest.json is missing – this is not a collection bundle.")
        try:
            m = json.loads(z.read("manifest.json"))
        except ValueError as e:
            raise BundleError("manifest.json is not valid JSON.") from e
    if m.get("format") != FORMAT:
        raise BundleError("This zip was not produced by the SD-WAN collector (unknown format).")
    if int(m.get("schema", 0)) > SCHEMA:
        raise BundleError(f"Bundle schema {m.get('schema')} is newer than this assessor supports ({SCHEMA}); please update the assessor.")
    for k in ("customer", "manager", "collected_utc", "endpoints"):
        if k not in m:
            raise BundleError(f"manifest.json is missing '{k}'.")
    return m


def extract_bundle(zip_path: Path, runs_dir: Path) -> Path:
    """Validate and unpack into runs/<customer>/<collected_utc>[-n]/ ; data is re-redacted on the way in."""
    m = read_manifest(zip_path)
    ts = slug(str(m["collected_utc"]))
    dest = runs_dir / slug(str(m["customer"])) / ts
    n = 1
    while dest.exists():
        n += 1
        dest = runs_dir / slug(str(m["customer"])) / f"{ts}-{n}"
    (dest / "raw").mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if name.startswith("raw/") and name.endswith(".json"):
                try:
                    data = json.loads(z.read(name))
                except ValueError:
                    continue  # skip a damaged file; the check that needs it becomes N/A
                (dest / "raw" / Path(name).name).write_text(json.dumps(redact(data), indent=1), encoding="utf-8")
    m["imported_from"] = Path(zip_path).name
    (dest / "manifest.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
    return dest
