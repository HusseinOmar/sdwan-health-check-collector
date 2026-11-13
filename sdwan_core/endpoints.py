"""Phase-1 endpoint catalogue: (key, category, GET path under /dataservice).

Grows in Phase 2/4 from the official 26.2 OpenAPI specs in
../API Structure/sdwan-api/. Keys are stable names used by checks.
"""

ENDPOINTS: list[tuple[str, str, str]] = [
    # 1 Inventory & baseline
    ("about", "inventory", "/dataservice/client/about"),
    ("server_info", "inventory", "/dataservice/client/server"),
    ("tenancy_mode", "inventory", "/dataservice/clusterManagement/tenancy/mode"),
    ("devices", "inventory", "/dataservice/device"),
    ("controllers", "inventory", "/dataservice/system/device/controllers"),
    ("vedges", "inventory", "/dataservice/system/device/vedges"),
    ("device_monitor", "inventory", "/dataservice/device/monitor"),
    # 2/3 Design & policy
    ("device_templates", "design", "/dataservice/template/device"),
    ("feature_templates", "design", "/dataservice/template/feature"),
    ("config_groups", "design", "/dataservice/v1/config-group"),
    ("policy_vsmart", "policy", "/dataservice/template/policy/vsmart"),
    ("policy_vedge", "policy", "/dataservice/template/policy/vedge"),
    ("policy_security", "policy", "/dataservice/template/policy/security"),
    ("policy_definitions_approute", "policy", "/dataservice/template/policy/definition/approute"),
    ("policy_definitions_data", "policy", "/dataservice/template/policy/definition/data"),
    ("policy_definitions_control", "policy", "/dataservice/template/policy/definition/control"),
    ("sla_classes", "policy", "/dataservice/template/policy/list/sla"),
    ("site_lists", "policy", "/dataservice/template/policy/list/site"),
    ("vpn_lists", "policy", "/dataservice/template/policy/list/vpn"),
    # 5 Security
    ("users", "security", "/dataservice/admin/user"),
    ("user_groups", "security", "/dataservice/admin/usergroup"),
    ("cert_summary", "security", "/dataservice/certificate/stats/summary"),
    ("cert_vedge_list", "security", "/dataservice/certificate/vedge/list"),
    ("cert_controllers", "security", "/dataservice/certificate/vsmart/list"),
    # 6 Health
    ("control_status", "health", "/dataservice/device/control/count"),
    ("bfd_summary", "health", "/dataservice/device/bfd/sites/summary"),
    ("alarms_count", "health", "/dataservice/alarms/count"),
    ("device_health", "health", "/dataservice/device/hardwarehealth/summary"),
    ("reboot_count", "health", "/dataservice/network/issues/rebootcount"),
    ("connections_summary", "health", "/dataservice/network/connectionssummary"),
    # 9 Lifecycle
    ("software_images", "lifecycle", "/dataservice/device/action/software"),
    # 10 Operability
    ("settings_org", "operability", "/dataservice/settings/configuration/organization"),
    ("cluster_health", "operability", "/dataservice/clusterManagement/health/status"),
    ("dr_status", "operability", "/dataservice/disasterrecovery/details"),
    ("sync_status", "operability", "/dataservice/template/device/syncstatus"),
]

ENDPOINTS += [
    # UX 2.0 (configuration groups / policy groups / feature profiles)
    ("policy_groups", "policy", "/dataservice/v1/policy-group"),
    ("topology_groups", "policy", "/dataservice/v1/topology-group"),
    ("fp_system", "design", "/dataservice/v1/feature-profile/sdwan/system"),
    ("fp_transport", "design", "/dataservice/v1/feature-profile/sdwan/transport"),
    ("fp_service", "design", "/dataservice/v1/feature-profile/sdwan/service"),
    ("fp_app_priority", "policy", "/dataservice/v1/feature-profile/sdwan/application-priority"),
    ("fp_topology", "policy", "/dataservice/v1/feature-profile/sdwan/topology"),
    # More UX 1.0 policy objects
    ("policy_definitions_qosmap", "policy", "/dataservice/template/policy/definition/qosmap"),
    ("policy_definitions_zbfw", "policy", "/dataservice/template/policy/definition/zonebasedfw"),
    ("policy_definitions_ips", "policy", "/dataservice/template/policy/definition/intrusionprevention"),
    ("policy_definitions_url", "policy", "/dataservice/template/policy/definition/urlfiltering"),
    ("policy_definitions_dns", "policy", "/dataservice/template/policy/definition/dnssecurity"),
    ("policy_definitions_hubspoke", "policy", "/dataservice/template/policy/definition/hubandspoke"),
    ("policy_definitions_mesh", "policy", "/dataservice/template/policy/definition/mesh"),
    ("policy_definitions_cflowd", "policy", "/dataservice/template/policy/definition/cflowd"),
    ("class_maps", "policy", "/dataservice/template/policy/list/class"),
    ("region_lists", "design", "/dataservice/template/policy/list/region"),
    # Fabric-wide state
    ("device_counters", "health", "/dataservice/device/counters"),
    ("device_status", "health", "/dataservice/device/status"),
    ("alarms", "health", "/dataservice/alarms"),
    ("unreachable", "health", "/dataservice/device/unreachable"),
    ("reboot_history", "health", "/dataservice/device/reboothistory/details"),
    ("cluster_list", "resilience", "/dataservice/clusterManagement/list"),
    ("aaa_manager", "security", "/dataservice/admin/aaa"),
    ("maintenance_window", "operability", "/dataservice/settings/configuration/maintenanceWindow"),
]

# Per-device calls. {sip} = system-ip, {uuid} = device uuid.
# scope: "controllers" (vsmart+vbond+vmanage), "edges", "all".
PER_DEVICE: list[tuple[str, str, str, str]] = [
    ("running_config", "security", "/dataservice/template/config/running/{uuid}"
     "|/dataservice/device/config?deviceId={sip}|/dataservice/device/config/html?deviceId={sip}", "all"),
    ("control_connections", "health", "/dataservice/device/control/connections?deviceId={sip}", "all"),
    ("system_status", "health", "/dataservice/device/system/status?deviceId={sip}", "all"),
    ("omp_summary", "health", "/dataservice/device/omp/summary?deviceId={sip}", "all"),
    ("omp_peers", "health", "/dataservice/device/omp/peers?deviceId={sip}", "edges"),
    ("bfd_sessions", "health", "/dataservice/device/bfd/sessions?deviceId={sip}", "edges"),
    ("wan_interfaces", "design", "/dataservice/device/control/waninterface?deviceId={sip}", "edges"),
    ("interfaces", "design", "/dataservice/device/interface?deviceId={sip}", "edges"),
    ("ntp_assoc", "operability", "/dataservice/device/ntp/associations?deviceId={sip}", "all"),
    ("crashlog", "health", "/dataservice/device/crashlog?deviceId={sip}", "all"),
    ("software", "lifecycle", "/dataservice/device/software?deviceId={sip}", "edges"),
]

import json as _json
import re
from urllib.parse import quote as _q


def _agg(hours: int, fields: list[str], metrics: list[str]) -> str:
    return _q(_json.dumps({
        "query": {"condition": "AND", "rules": [
            {"value": [str(hours)], "field": "entry_time", "type": "date", "operator": "last_n_hours"}]},
        "aggregation": {"field": [{"property": f, "sequence": i + 1} for i, f in enumerate(fields)],
                        "metrics": [{"property": m, "type": "avg"} for m in metrics]}}))


ENDPOINTS += [
    # 7 Performance (24 h tunnel quality, aggregated on the Manager – one call for the whole fabric)
    ("approute_24h", "performance", "/dataservice/statistics/approute/aggregation?query="
     + _agg(24, ["name", "local_color", "remote_color"], ["loss_percentage", "latency", "jitter"])),
    ("approute_color_24h", "performance", "/dataservice/statistics/approute/aggregation?query="
     + _agg(24, ["local_color"], ["loss_percentage", "latency", "jitter"])),
    ("tloc_util", "performance", "/dataservice/device/tlocutil"),
]
PER_DEVICE += [
    ("tunnel_stats", "performance", "/dataservice/device/tunnel/statistics?deviceId={sip}", "edges"),
]


# Bulk state API per key: (state types, fields the checks need).
# Tried first; if bulk fails or a required field is missing (bulk schemas differ by
# release and are a cached subset), the key falls back to its PER_DEVICE path.
# SystemStatus/Interface are NOT bulk: their bulk rows lack CPU/memory and bandwidth fields.
BULK: dict[str, tuple[list[str], list[str]]] = {
    "control_connections": (["ControlConnection"], ["state", "peer-type"]),
    "bfd_sessions": (["BFDSessions"], ["state", "transitions", "tx-interval", "detect-multiplier", "local-color", "color"]),
    "omp_peers": (["OMPPeer"], ["peer", "state"]),
    "software": (["Software"], ["version", "active"]),
}

ENDPOINTS += [
    # Lifecycle stage (Use / Optimize) inputs
    ("tags", "operability", "/dataservice/v1/tags"),
    ("cloudservices", "adoption", "/dataservice/settings/configuration/cloudservices"),
]

# ---- Extended checks (gap closure vs old projects) ----
ENDPOINTS += [
    ("licensing", "lifecycle", "/dataservice/msla/monitoring/licensedDeviceCount"),
    ("smart_licensing", "lifecycle", "/dataservice/smartLicensing/getUserSettings"),
    ("license_devices", "lifecycle", "/dataservice/msla/devices"),
    ("license_pools", "lifecycle", "/dataservice/msla/licenses"),
    ("license_distribution", "lifecycle", "/dataservice/msla/monitoring/licensedDistributionDetails"),
    ("auditlog", "security", "/dataservice/auditlog?query=" + _q(_json.dumps({"query": {"condition": "AND", "rules": [
        {"value": ["7"], "field": "entry_time", "type": "date", "operator": "last_n_days"}]}, "size": 5000}))),
    ("sig_tunnels", "security", "/dataservice/device/sig/getSigTunnelList"),
    ("if_24h", "performance", "/dataservice/statistics/interface/aggregation?query="
     + _agg(24, ["vdevice_name", "interface"], ["rx_kbps", "tx_kbps"]).replace("%22type%22%3A%20%22avg%22", "%22type%22%3A%20%22max%22")),
]
PER_DEVICE += [
    ("bgp_neighbors", "health", "/dataservice/device/bgp/neighbors?deviceId={sip}", "edges"),
    ("ospf_neighbors", "health", "/dataservice/device/ospf/neighbor?deviceId={sip}", "edges"),
    ("control_history", "health", "/dataservice/device/control/connectionshistory?deviceId={sip}", "edges"),
    ("ipsec_outbound", "security", "/dataservice/device/ipsec/outbound?deviceId={sip}", "edges"),
    ("attached_config", "operability", "/dataservice/template/config/attached/{uuid}?type=CFS", "edges"),
]
BULK.update({
    "bgp_neighbors": (["BGPNeighbor"], ["peer-addr"]),
    "ospf_neighbors": (["OSPFNeighbor"], ["neighbor-id"]),
})

# Per device template detail (feature templates it is built from, policy, CLI text) – needed for
# the device template view (router/block diagrams, duplicates). All device templates are read.
PER_TEMPLATE: list[tuple[str, str]] = [
    ("device_template_objects", "/dataservice/template/device/object/{id}"),
]

# Per configuration group: attached devices; per unique feature profile: its features (parcels) with settings.
# The shared policy-object profile is skipped (thousands of objects; listed with its count only).
CG_SKIP_PROFILE_TYPES = {"policy-object"}
_TYPE_OK = re.compile(r"[a-z][a-z-]{0,40}")
_ID_OK = re.compile(r"[A-Za-z0-9_.:-]{1,80}")


def config_group_jobs(results) -> list[tuple[str, dict[str, str]]]:
    """[(key, {id: GET path})] for config-group devices and feature-profile details, from 'config_groups'."""
    r = next((r for r in results if r.key == "config_groups" and r.ok), None)
    rows = ((r.data.get("data") if isinstance(r.data, dict) else r.data) or []) if r else []
    groups = [g for g in rows if isinstance(g, dict) and _ID_OK.fullmatch(str(g.get("id") or "")) and ".." not in str(g["id"])]
    devs = {g["id"]: f"/dataservice/v1/config-group/{g['id']}/device/associate" for g in groups}
    profs = {}
    for g in groups:
        for p in g.get("profiles") or []:
            t, sol = str(p.get("type") or ""), str(p.get("solution") or g.get("solution") or "sdwan")
            if _ID_OK.fullmatch(str(p.get("id") or "")) and ".." not in str(p["id"]) and _TYPE_OK.fullmatch(t) and _TYPE_OK.fullmatch(sol) and t not in CG_SKIP_PROFILE_TYPES:
                profs[p["id"]] = f"/dataservice/v1/feature-profile/{sol}/{t}/{p['id']}?details=true"
    return [("config_group_devices", devs), ("feature_profiles", profs)]


# Keys collected per id outside ENDPOINTS (config groups); counted by collection_count().
PER_ID_KEYS = ["config_group_devices", "feature_profiles", "feature_parcels"]


def collection_count() -> int:
    """Number of distinct data sets the collector reads; a change means a new collector version (see live_ui.CHANGELOG)."""
    return len(ENDPOINTS) + len(PER_DEVICE) + len(PER_TEMPLATE) + len(PER_ID_KEYS)


_PARCEL_OK = re.compile(r"[a-z0-9][a-z0-9/-]{0,60}")


def parcel_jobs(results) -> dict[str, str]:
    """{parcel id: GET path} for features whose settings were not included in the profile details."""
    r = next((r for r in results if r.key == "feature_profiles" and r.ok), None)
    out = {}
    for pid, body in ((r.data or {}).get("per_id") or {}).items() if r else []:
        if not isinstance(body, dict):
            continue
        sol, typ = str(body.get("solution") or "sdwan"), str(body.get("profileType") or "")
        for x in body.get("associatedProfileParcels") or []:
            pt, xid = str(x.get("parcelType") or ""), x.get("parcelId")
            if xid and _ID_OK.fullmatch(str(xid)) and ".." not in str(xid) and _ID_OK.fullmatch(str(pid)) and not (x.get("payload") or {}).get("data") and _TYPE_OK.fullmatch(sol) and _TYPE_OK.fullmatch(typ) \
                    and _PARCEL_OK.fullmatch(pt) and ".." not in pt:
                if sol == "sd-routing":  # SD-Routing features are typed "ntp-sd-routing" but addressed as ".../ntp/{id}"
                    pt = pt.removesuffix("-sd-routing")
                out[xid] = f"/dataservice/v1/feature-profile/{sol}/{typ}/{pid}/{pt}/{xid}"
    return out


def template_ids(results) -> list[str]:
    """Ids of all device templates, from the collected 'device_templates' result."""
    r = next((r for r in results if r.key == "device_templates" and r.ok), None)
    rows = ((r.data.get("data") if isinstance(r.data, dict) else r.data) or []) if r else []
    return [t["templateId"] for t in rows if isinstance(t, dict) and t.get("templateId")]
