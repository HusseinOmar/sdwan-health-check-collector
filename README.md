# SD-WAN Collector

Collects **read-only** data from a Cisco Catalyst SD-WAN Manager (vManage) and writes **one zip file**
for the Cisco SD-WAN assessment (`sdwan-assessor`). Run it at the customer site, then send the zip to your Cisco team.

- **Read-only:** only GET requests are sent. Nothing on the Manager is changed. A read-only Manager account is enough.
- **No secrets kept:** the password is used once to log in and is never stored. Passwords, keys, SNMP communities,
  hashes and session tokens are replaced with `[redacted]` before anything is written.
- **Reviewable:** the zip contains `README.txt`, `manifest.json` and `raw/*.json` (plain JSON) so the customer can check what is shared.
- **Fast:** 20 parallel API calls plus bulk APIs. A small fabric takes about 20 seconds, a large one a few minutes.

## Requirements
- Python **3.9 or newer** ([python.org/downloads](https://www.python.org/downloads/)).
  On Windows, tick **"Add python.exe to PATH"** during install.
- HTTPS access from this computer to the SD-WAN Manager (port 443 or the custom port).
- Internet access on the first run only, to install the single package `requests`. Behind a proxy, set
  `HTTPS_PROXY` first (see Troubleshooting).

---

## Windows

### Option A – web page (easiest)
1. Unzip `sdwan-health-check-collector-<version>.zip`, for example to `C:\sdwan-collector`.
2. Double-click **`run.bat`**. The first run creates a private Python environment, which takes about a minute.
3. Your browser opens **http://127.0.0.1:5050**. If it doesn't, open that address yourself.
4. Enter the customer name, the Manager URL, username and password, then click **Start collection**.
5. When it finishes, click **Download the zip**. The file is also saved in the `output\` folder.

### Option B – command line
Open **Command Prompt** in the collector folder:
```bat
run.bat cli --url vmanage.example.com -u readonly-user --customer "ACME"
```
You are asked for the password; it is hidden while you type. The zip path is printed at the end.

---

## Linux (and macOS)

### Option A – web page (easiest)
```bash
unzip sdwan-health-check-collector-<version>.zip && cd sdwan-collector
./run.sh                     # opens http://127.0.0.1:5050
```
On a server without a desktop, use `./run.sh --no-browser`, then open `http://127.0.0.1:5050` from a browser
on the same machine. Over SSH, forward the port with `ssh -L 5050:127.0.0.1:5050 user@server`.

### Option B – command line
```bash
./run.sh cli --url vmanage.example.com -u readonly-user --customer "ACME"
```

---

## Command-line options
| Option | Meaning |
|---|---|
| `--url` | Manager name or IP, e.g. `vmanage.example.com` or `10.1.1.1` (https is implied) |
| `--port` | Manager HTTPS port (default 443) |
| `-u, --username` | Manager username (a read-only account is enough) |
| `--customer` | Customer name, used in the file name |
| `--ca-bundle FILE` | Your company's CA certificate (`.pem`) if the Manager uses an internal certificate |
| `--verify-tls` | Check the TLS certificate (by default the check is skipped) |
| `--max-edges N` | Edges sampled for per-device data (default 100) |
| `--workers N` | Parallel API calls (default 20; use 5–10 for a busy Manager) |

For scripted runs, set the password in the environment so it isn't typed or kept in shell history:
- Linux: `read -s SDWAN_PW && export SDWAN_PW`
- Windows: `set /p SDWAN_PW=Password: `

## Web-page options
`python webapp.py [--port 5050] [--host 127.0.0.1] [--no-browser]`. By default the page listens on this
computer only. `--host 0.0.0.0` makes it reachable from other machines, but credentials would then cross the
network without TLS, so it isn't recommended.

## Output
`output/sdwan_collection_<customer>_<timestamp>.zip`. Import it in the assessor
(**Import collection** on the home page, or `python -m sdwan_assessor.importer <zip>`).

## Troubleshooting
| Message | What to do |
|---|---|
| `Login failed (HTTP 401/200 html)` | Wrong username or password, or the account is locked. |
| `Manager is busy (HTTP 503)` | Wait a few minutes and try again, or use `--workers 5`. |
| `TLS certificate not trusted` | Use `--ca-bundle your-ca.pem`. Or leave out `--verify-tls` / keep "Skip TLS certificate check" ticked. |
| `pip install failed` | Set your proxy first: Linux `export HTTPS_PROXY=http://proxy:8080`, Windows `set HTTPS_PROXY=http://proxy:8080`. |
| Python not found | Install Python 3.9+ and re-open the terminal (Windows: tick "Add to PATH"). |

## What is collected
Inventory and device status, control and data-plane state (control connections, OMP, BFD, BGP/OSPF neighbours),
24-hour tunnel and interface statistics summaries, alarms (counts and list), certificates (status and expiry
dates), templates, configuration groups, policies, licensing counts, the audit log (7 days) and device running
configurations, all with secrets redacted. The full list is in `sdwan_core/endpoints.py`.

Sample code provided as-is for Cisco assessments; not supported by Cisco TAC.
