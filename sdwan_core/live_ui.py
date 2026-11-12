"""Shared live-collection UI: the futuristic progress page used by BOTH the assessor web app and the
standalone collector (`collector_app/webapp.py`). Standard library only, and it imports nothing from the
assessor except `endpoints` – it is shipped to customers as part of `sdwan_core`.

Usage: job = new_job(phases); log, progress = hooks(job); feed them to the collection; serve
status(job) as JSON at /status/<id> and page(title, running_html(job, log_text), script(id)) at /job/<id>.
"""
from __future__ import annotations

import html
import json
import threading
import time
from collections import deque

from . import endpoints

LOCK = threading.Lock()

# ---- what is being collected: key -> (category, API path) --------------------------------------
COLLECTOR_PHASES = ["Secure login", "Fabric-wide data", "Per-device data", "Templates", "Packaging"]
ASSESSOR_PHASES = ["Secure login", "Fabric-wide data", "Per-device data", "Templates", "Checks & scoring"]
SPAN = [(0, 3), (3, 35), (35, 85), (85, 95), (95, 100)]  # share of the overall ring per phase (start %, end %)
# messages that start each phase (both apps log these exact phrases)
PHASE_MARKERS = [("Logging in", 0), ("Logged in", 1), ("devices found", 2), ("Reading", 3), ("Collected", 4)]

CAT: dict[str, str] = {k: c for k, c, _ in endpoints.ENDPOINTS}
CAT.update({e[0]: e[1] for e in endpoints.PER_DEVICE})
PATH: dict[str, str] = {k: p for k, _, p in endpoints.ENDPOINTS}
PATH.update({e[0]: e[2].split("|")[0] for e in endpoints.PER_DEVICE})
BULK_KEY = {st: k for k, (sts, _) in endpoints.BULK.items() for st in sts}
for _k, _p in endpoints.PER_TEMPLATE:
    CAT[_k], PATH[_k] = "design", _p
CATEGORIES = sorted(set(CAT.values()))


def manager_url(host: str, port: int | str | None = 443) -> str:
    """'vmanage.x' / '10.1.1.1' / 'https://h:8443/' + port field -> 'https://host[:port]'.
    A port typed into the host field wins; port 443 is left out (it is the https default)."""
    h = (host or "").strip()
    for p in ("https://", "http://"):
        if h.lower().startswith(p):
            h = h[len(p):]
    h = h.split("/")[0]
    if h.count(":") > 1 and not h.startswith("["):  # bare IPv6 address
        h = f"[{h}]"
    if not h.rsplit("]", 1)[-1].count(":"):  # no port in the host field
        try:
            port = int(port or 443)
        except ValueError:
            raise ValueError("Port must be a number (default 443)")
        if not 1 <= port <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        if port != 443:
            h = f"{h}:{port}"
    if not h:
        raise ValueError("Enter the Manager name or IP address")
    return "https://" + h


def describe(label: str) -> tuple[str, str, str]:
    """Progress label -> (category, friendly text, API path)."""
    head, _, rest = label.partition(" ")
    if head == "bulk":
        key = BULK_KEY.get(rest, rest)
        return CAT.get(key, "health"), f"{key.replace('_', ' ').capitalize()} · all devices (bulk)", PATH.get(key, "")
    text = head.replace("_", " ").capitalize() + (f" · {rest}" if rest else "")
    return CAT.get(head, "other"), text, PATH.get(head, "")


# ---- job state ---------------------------------------------------------------------------------
def new_job(phases: list[str] = COLLECTOR_PHASES, **extra) -> dict:
    now = time.monotonic()
    return {"log": [], "pct": 0, "state": "running", "error": "", "phase": 0, "phases": list(phases),
            "done": 0, "total": 0, "calls": 0, "t0": now, "pt0": now, "current": "", "feed": deque(maxlen=12),
            "cats": dict.fromkeys(CATEGORIES, 0), "t_end": None, **extra}


def _set_phase(j: dict, ph: int) -> None:
    if ph != j["phase"]:
        j["phase"], j["done"], j["total"], j["pt0"], j["current"] = ph, 0, 0, time.monotonic(), ""
    j["pct"] = max(j["pct"], SPAN[ph][0])


def hooks(j: dict):
    """(log, progress) callbacks that update job `j`; safe to call from worker threads."""
    def log(m: str) -> None:
        with LOCK:
            j["log"].append(m)
            for mark, ph in PHASE_MARKERS:
                if mark in m:
                    _set_phase(j, ph)

    def progress(i: int, n: int, key: str) -> None:
        cat, text, path = describe(key)
        with LOCK:
            if i == 1 and j["done"] >= j["total"]:  # a new batch inside the same phase
                j["pt0"] = time.monotonic()
            j["done"], j["total"] = i, n
            j["calls"] += 1
            j["cats"][cat] = j["cats"].get(cat, 0) + 1
            j["current"] = f"{text}  {path}".strip()
            j["feed"].appendleft((cat, text, path))
            lo, hi = SPAN[j["phase"]]
            j["pct"] = max(j["pct"], int(lo + (hi - lo) * i / max(n, 1)))
            if i == n or i % 25 == 0:
                j["log"].append(f"  {i}/{n} {key}")
    return log, progress


def finish(j: dict, state: str, error: str = "", **extra) -> None:
    with LOCK:
        j.update(extra)
        j["state"], j["error"], j["t_end"] = state, error, time.monotonic()
        if state == "done":
            j["pct"], j["phase"] = 100, len(j["phases"])


def status(j: dict) -> dict:
    """JSON-ready snapshot of a job for the live page."""
    with LOCK:
        now = j["t_end"] or time.monotonic()
        el, pel = now - j["t0"], now - j["pt0"]
        rate = j["done"] / pel if pel > 0 and j["done"] else 0
        eta = (j["total"] - j["done"]) / rate if rate and j["total"] else None
        return {"state": j["state"], "pct": j["pct"], "phase": j["phase"], "phases": j["phases"], "done": j["done"],
                "total": j["total"], "calls": j["calls"], "rate": round(j["calls"] / el, 1) if el > 0 else 0,
                "elapsed": round(el), "eta": None if eta is None else round(eta), "current": j["current"],
                "feed": list(j["feed"]), "cats": dict(j["cats"]), "log": j["log"][-200:]}


# ---- look & feel -------------------------------------------------------------------------------
CSS = """:root{--bg:#050d1a;--c:#02C8FF;--g:#1FB86A;--m:#FF007F;--t:#B4B9C0;--d:#7D8794;--glass:rgba(10,30,55,.55)}
*{box-sizing:border-box}body{font-family:-apple-system,'Segoe UI',Arial,sans-serif;background:var(--bg);color:var(--t);margin:0;min-height:100vh;overflow-x:hidden}
body:before{content:"";position:fixed;inset:-50%;background-image:linear-gradient(rgba(2,200,255,.07) 1px,transparent 1px),linear-gradient(90deg,rgba(2,200,255,.07) 1px,transparent 1px);
background-size:44px 44px;transform:perspective(600px) rotateX(60deg);animation:grid 12s linear infinite;z-index:-2}
body:after{content:"";position:fixed;inset:0;background:radial-gradient(ellipse at 50% 0%,rgba(2,200,255,.18),transparent 60%),radial-gradient(ellipse at 100% 100%,rgba(255,0,127,.10),transparent 50%);z-index:-1}
@keyframes grid{to{background-position:0 44px}}
.wrap{max-width:980px;margin:34px auto;padding:0 20px}a{color:var(--c)}
h1{color:#fff;font-weight:300;letter-spacing:.18em;text-transform:uppercase;margin:0;font-size:26px}h1 b{color:var(--c);font-weight:600;text-shadow:0 0 18px rgba(2,200,255,.7)}
h2{color:#fff;font-weight:400;letter-spacing:.06em;margin-top:0}h3{color:var(--c);font-size:11px;letter-spacing:.25em;text-transform:uppercase;font-weight:600;margin:22px 0 10px}
.sub{color:var(--d);margin:6px 0 26px;font-size:13px;letter-spacing:.05em}.sub i{color:var(--g);font-style:normal}
.card{background:var(--glass);backdrop-filter:blur(10px);border:1px solid rgba(2,200,255,.25);border-radius:16px;padding:24px;box-shadow:0 0 40px rgba(2,200,255,.08),inset 0 0 30px rgba(2,200,255,.04)}
label{display:block;margin:14px 0 5px;color:#fff;font-size:12px;letter-spacing:.12em;text-transform:uppercase}
input[type=text],input[type=password],input[type=number]{width:100%;padding:11px;border-radius:8px;border:1px solid rgba(2,200,255,.3);background:rgba(3,15,30,.8);color:#fff;font-size:14px;transition:.2s}
input:focus{outline:0;border-color:var(--c);box-shadow:0 0 0 3px rgba(2,200,255,.18),0 0 18px rgba(2,200,255,.3)}
.row{display:flex;gap:14px}.row>div{flex:1}.row>.port{flex:0 0 120px}
button,.btn{margin-top:20px;background:linear-gradient(90deg,#02C8FF,#0aa0ff);color:#04101f;border:0;border-radius:8px;padding:12px 22px;font-weight:700;font-size:13px;letter-spacing:.12em;
text-transform:uppercase;cursor:pointer;text-decoration:none;display:inline-block;box-shadow:0 0 22px rgba(2,200,255,.45);transition:.2s}button:hover,.btn:hover{box-shadow:0 0 34px rgba(2,200,255,.8);transform:translateY(-1px)}
.btn.alt{background:transparent;color:var(--c);border:1px solid var(--c);box-shadow:none}small{color:var(--d)}
.log{font-family:Menlo,Consolas,monospace;font-size:12px;background:rgba(0,8,18,.85);border:1px solid rgba(2,200,255,.15);border-radius:8px;padding:12px;max-height:220px;overflow:auto;white-space:pre-wrap;color:#8fe6ff}
.ok{color:var(--g)}.err{color:var(--m)}.note{border-left:2px solid var(--c);padding-left:12px;margin-top:20px;font-size:13px}
.steps{display:flex;gap:8px;margin-bottom:24px}.step{flex:1;position:relative;padding:10px 8px 10px 30px;border:1px solid rgba(255,255,255,.1);border-radius:8px;font-size:12px;color:var(--d);transition:.4s}
.step:before{content:"";position:absolute;left:11px;top:50%;width:9px;height:9px;margin-top:-5px;border-radius:50%;background:#2a3a4f}
.step.done{color:var(--g);border-color:rgba(31,184,106,.4)}.step.done:before{background:var(--g);box-shadow:0 0 8px var(--g)}
.step.act{color:#fff;border-color:var(--c);box-shadow:0 0 18px rgba(2,200,255,.35)}.step.act:before{background:var(--c);animation:pulse 1s infinite}
@keyframes pulse{50%{box-shadow:0 0 0 6px rgba(2,200,255,0)}0%{box-shadow:0 0 0 0 rgba(2,200,255,.8)}}
.hud{display:grid;grid-template-columns:210px 1fr;gap:26px;align-items:center}
.ring{position:relative;width:200px;height:200px}.ring svg{transform:rotate(-90deg)}.ring circle{fill:none;stroke-width:10}
.ring .bgc{stroke:rgba(2,200,255,.12)}.ring .fg{stroke:url(#gr);stroke-linecap:round;transition:stroke-dashoffset .8s ease;filter:drop-shadow(0 0 6px #02C8FF)}
.ring .spin{position:absolute;inset:-6px;border-radius:50%;border:1px dashed rgba(2,200,255,.35);animation:spin 14s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
.ring .val{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}.ring .val b{font-size:44px;color:#fff;font-weight:200}
.ring .val span{font-size:10px;letter-spacing:.25em;color:var(--c);text-transform:uppercase}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.stat{background:rgba(0,10,22,.6);border:1px solid rgba(2,200,255,.15);border-radius:10px;padding:12px}
.stat b{display:block;font-size:22px;color:#fff;font-weight:300;font-variant-numeric:tabular-nums}.stat span{font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:var(--d)}
.now{margin-top:12px;font-family:Menlo,Consolas,monospace;font-size:12px;color:var(--c);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.now:before{content:"▸ ";animation:blink 1s steps(2) infinite}
@keyframes blink{50%{opacity:0}}
.pbar{height:4px;background:rgba(255,255,255,.08);border-radius:2px;margin-top:10px;overflow:hidden}.pbar i{display:block;height:100%;background:linear-gradient(90deg,#02C8FF,#1FB86A);transition:width .6s}
.tiles{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}.tile{background:rgba(0,10,22,.6);border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:10px;transition:.3s}
.tile b{display:block;color:#fff;font-size:18px;font-weight:300}.tile span{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--d)}
.tile.hot{border-color:var(--c);box-shadow:0 0 14px rgba(2,200,255,.4)}.tile .pbar{height:3px}
.feed{list-style:none;margin:0;padding:0;font-size:12px}.feed li{display:flex;gap:10px;padding:6px 8px;border-bottom:1px solid rgba(255,255,255,.05);animation:in .4s ease}
.feed li:first-child{background:rgba(2,200,255,.07)}.feed .tag{flex:0 0 86px;font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--c)}
.feed .txt{flex:1;color:#dfe7ef;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.feed .path{color:var(--d);font-family:Menlo,Consolas,monospace;font-size:11px;max-width:40%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
@keyframes in{from{opacity:0;transform:translateX(-8px)}}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:22px}
@media(max-width:760px){.hud,.cols{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}.tiles{grid-template-columns:repeat(2,1fr)}.steps{flex-wrap:wrap}}"""


def page(title: str, body: str, version: str = "", refresh: bool = False, script: str = "",
         sub: str = "Read-only data collection for the Cisco Catalyst SD-WAN Health Check") -> bytes:
    """Full HTML page. `title` like 'SD-WAN Collector': the last word is highlighted."""
    meta = '<noscript><meta http-equiv="refresh" content="2"></noscript>' if refresh else ""
    first, _, last = html.escape(title).rpartition(" ")
    ver = f" · v{html.escape(version)}" if version else ""
    return (f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>{meta}"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
            f"<body><div class=wrap><h1>{first} <b>{last}</b></h1><div class=sub><i>●</i> {html.escape(sub)}{ver}</div>"
            f"{body}</div>{script}</body></html>").encode()


def connection_fields() -> str:
    """Form fields shared by both apps: host/IP + port (default 443); https is implied; TLS check skipped by default."""
    return """<div class=row><div><label>SD-WAN Manager name or IP</label><input type=text name=host placeholder="vmanage.example.com or 10.1.1.1" required></div>
<div class=port><label>Port</label><input type=number name=port value=443 min=1 max=65535 required></div></div>
<div class=row><div><label>Username</label><input type=text name=username required autocomplete=off></div>
<div><label>Password</label><input type=password name=password required autocomplete=off></div></div>
<div class=row><div><label>Max edges for per-device data</label><input type=number name=max_edges value=100 min=1 max=5000></div>
<div><label>Parallel API calls</label><input type=number name=workers value=20 min=1 max=50></div></div>
<label style="text-transform:none;letter-spacing:0"><input type=checkbox name=insecure checked> Skip TLS certificate check</label>"""


def running_html(j: dict, heading: str = "") -> str:
    s = status(j)
    steps = "<div class=steps>" + "".join(
        f"<div class=step id=s{i}>{html.escape(p)}</div>" for i, p in enumerate(s["phases"])) + "</div>"
    tiles = "<div class=tiles>" + "".join(
        f"<div class=tile id=t-{html.escape(c)}><b>0</b><span>{html.escape(c)}</span><div class=pbar><i></i></div></div>"
        for c in s["cats"]) + "</div>"
    head = f"<h2>{html.escape(heading)}</h2>" if heading else ""
    return f"""<div class=card>{head}{steps}
<div class=hud><div class=ring><div class=spin></div>
<svg width=200 height=200><defs><linearGradient id=gr><stop offset=0 stop-color=#02C8FF /><stop offset=1 stop-color=#1FB86A /></linearGradient></defs>
<circle class=bgc cx=100 cy=100 r=88 /><circle class=fg id=arc cx=100 cy=100 r=88 stroke-dasharray=552.9 stroke-dashoffset={552.9 * (1 - s['pct'] / 100):.1f} /></svg>
<div class=val><b id=pct>{s['pct']}</b><span>percent</span></div></div>
<div><div class=stats>
<div class=stat><b id=calls>{s['calls']}</b><span>API calls done</span></div><div class=stat><b id=rate>{s['rate']}</b><span>calls / sec</span></div>
<div class=stat><b id=el>0:00</b><span>elapsed</span></div><div class=stat><b id=eta>–</b><span>step time left</span></div></div>
<div class=now id=now>Starting…</div><div class=pbar><i id=pp style="width:0"></i></div><small id=pc></small></div></div>
<h3>Data collected by area</h3>{tiles}
<div class=cols><div><h3>Live feed</h3><ul class=feed id=feed></ul></div><div><h3>Console</h3><div class=log id=log>{html.escape(chr(10).join(s['log']))}</div></div></div>
<div class=note>Read-only GET requests only. Secrets are redacted before anything is written to disk.</div></div>"""


def summary_html(j: dict) -> str:
    s = status(j)
    return (f"<div class=stats style='margin:16px 0'><div class=stat><b>{s['calls']}</b><span>API calls</span></div>"
            f"<div class=stat><b>{s['elapsed'] // 60}:{s['elapsed'] % 60:02d}</b><span>duration</span></div>"
            f"<div class=stat><b>{s['rate']}</b><span>calls / sec</span></div>"
            f"<div class=stat><b>{sum(s['cats'].values())}</b><span>data items</span></div></div>")


_JS = """<script>
const jid=%s,$=id=>document.getElementById(id),fmt=s=>s==null?'–':Math.floor(s/60)+':'+String(Math.floor(s%%60)).padStart(2,'0');
async function tick(){let r;try{r=await (await fetch('/status/'+jid,{cache:'no-store'})).json()}catch(e){return setTimeout(tick,2000)}
if(r.state!=='running'){location.reload();return}
$('pct').textContent=r.pct;$('arc').style.strokeDashoffset=552.9*(1-r.pct/100);
r.phases.forEach((_,i)=>{$('s'+i).className='step'+(i<r.phase?' done':i===r.phase?' act':'')});
$('calls').textContent=r.calls;$('rate').textContent=r.rate;$('el').textContent=fmt(r.elapsed);$('eta').textContent=fmt(r.eta);
$('now').textContent=r.current||r.phases[r.phase]+'…';$('pp').style.width=(r.total?100*r.done/r.total:0)+'%%';
$('pc').textContent=r.total?r.phases[r.phase]+': '+r.done+' / '+r.total:'';
const mx=Math.max(1,...Object.values(r.cats));
for(const[c,n]of Object.entries(r.cats)){const t=$('t-'+c);if(!t)continue;const b=t.querySelector('b');
if(b.textContent!=String(n)){t.classList.add('hot');setTimeout(()=>t.classList.remove('hot'),600)}b.textContent=n;t.querySelector('i').style.width=100*n/mx+'%%'}
const f=$('feed');f.replaceChildren(...r.feed.map(x=>{const li=document.createElement('li');
for(const[c,v]of[['tag',x[0]],['txt',x[1]],['path',x[2]]]){const s=document.createElement('span');s.className=c;s.textContent=v;li.append(s)}return li}));
const l=$('log');l.textContent=r.log.join('\\n');l.scrollTop=l.scrollHeight;setTimeout(tick,1000)}
tick();
</script>"""


def script(job_id: str) -> str:
    return _JS % json.dumps(job_id).replace("<", "\\u003c")
