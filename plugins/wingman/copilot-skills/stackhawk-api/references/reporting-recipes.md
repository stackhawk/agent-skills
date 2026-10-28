# StackHawk API Reporting Recipes

Pre-built compositions for common security reporting questions using `hawk op`.
Run `hawk op status` first to confirm authentication; set `HAWK_API_KEY` in any
non-interactive session (CI, containers, headless agents).

**Setup (run once per shell session when non-interactive):**

```bash
export HAWK_API_KEY="hawk.xxxxxxxxxxxx"   # from app.stackhawk.com → Settings → API Keys
```

## Contents
- [What `hawk op` emits](#what-hawk-op-emits)
- [Recipe 1: Org Security Posture](#recipe-1-org-security-posture)
- [Recipe 2: App Deep Dive](#recipe-2-app-deep-dive)
- [Recipe 3: Stale Apps](#recipe-3-stale-apps)
- [Recipe 4: What Changed Since Last Scan](#recipe-4-what-changed-since-last-scan)

---

## What `hawk op` emits

Every recipe below reads only these fields. Do not reach for others — `hawk op scan
list` does not emit raw API fields such as `applicationId` or `highAlertCount`.

**`hawk op scan list --format json`** → `{"data": [...], "meta": {...}}`, one row per scan:

| Field | Example | Meaning |
|---|---|---|
| `id` | `"aaa-bbb-ccc"` | Scan UUID |
| `app` | `"payment-api"` | App **name** (no app UUID in this output) |
| `env` | `"Production"` | Environment name |
| `status` | `"Complete"` | `Complete`, `Failed`, or `Running` |
| `findings` | `"4H0 47M2 41L0"` | Per severity, `{new}{H\|M\|L}{triaged}`; `--` when none |
| `duration` | `"11s"` | Human-readable; `--` when absent |
| `started` | `"3w ago"` / `"2025-08-26"` | Relative under 4 weeks, else a `YYYY-MM-DD` date (UTC) |

`4H0 47M2` reads "4 new High, 0 triaged High; 47 new Medium, 2 triaged Medium".
"New" counts findings not yet triaged; "triaged" counts promoted, risk-accepted,
and false-positive findings. A severity with zero of both is omitted.

**`hawk op scan list` flags that matter for reporting:**

- Without `--limit`, it returns only **10** scans. Pass `--limit 10000` for the whole org.
- Page order is not guaranteed across pages. Add `--sort-by started --sort-dir desc`
  to get a true newest-first list (sorted client-side by the exact timestamp,
  up to 10,000 scans).
- `--status complete` keeps completed scans only. `--app` takes an app **UUID**, not
  a name; `--env` takes an environment name.

**`hawk op scan get <SCAN_ID> --format json`** (no `--detail`): the raw scan
record — `.scan.id`, `.scan.applicationId`, `.scan.applicationName`, `.scan.env`,
`.scan.status` (`COMPLETED`), `.scan.timestamp` (epoch ms, as a string), and
`.severityStats` (number of alert types per severity, e.g. `{"High": 4, "Medium": 5}`
— complete). Its `.applicationAlerts` holds a single sample alert, not the list.

**`hawk op scan get … --detail full --format json`**: `.scan` (`id`,
`application_name`, `environment`, `status`, `completed_at`), `.summary`
(`by_severity`, `by_status`), and `.findings[]` — one entry per alert type, with
`plugin_id`, `plugin_name`, `severity`, `cwe_id`, `total_paths`, and `paths[]`
(`method`, `uri`, `param`, `status`; `status` `UNKNOWN` means new).

**`hawk op scan get <SCAN_ID> --plugin-id <PLUGIN_ID> --format json`**:
`.alert.uriCount` is the true number of affected paths for that alert type.

**10-row caps:** `hawk op` returns at most **10 alert types per scan** (highest
severity first) and at most **10 paths per alert type** — in `--detail full` and
in the default pretty output. So `total_paths` never exceeds 10; read the true
count from `.alert.uriCount`. Compare `.findings | length` against
`.severityStats | add` to detect a truncated alert list, and say so when it
happens. The complete lists are in the scanner's `hawk scan --json-output` file or
on the platform scan page.

**Not available from `hawk op` yet:** more than 10 alert types per scan or 10 paths
per alert type (above),
an exact scan start time in `scan list` (only the relative/date `started` string),
app UUIDs in `scan list` (join to `hawk op app list` by name), team ownership or
env counts in `hawk op app list` (it emits `id`, `name`, `cloud` only), and scans of
cloud-type apps in the default `scan list` output. Say so when a user asks for any
of these.

---

## Recipe 1: Org Security Posture

**Question:** Across all my apps, what is the current security situation?

**What it produces:** One row per app + environment from its latest completed
scan, showing new (untriaged) findings by severity, sorted by High then Medium.

```bash
hawk op scan list --status complete --sort-by started --sort-dir desc \
    --limit 10000 --format json \
| jq -r '
  def counts: [.findings | scan("([0-9]+)([HML])([0-9]+)")]
    | map({(.[1]): {new: (.[0] | tonumber), triaged: (.[2] | tonumber)}})
    | add // {};

  # Rows are newest-first, so the first row per app + env is its latest scan
  .data
  | reduce .[] as $s ({}; .[$s.app + "\u0000" + $s.env] //= $s)
  | [.[] | . + {c: counts}]
  | sort_by(-(.c.H.new // 0), -(.c.M.new // 0), .app)
  | ["APP", "ENVIRONMENT", "HIGH", "MEDIUM", "LOW", "TRIAGED", "LAST_SCAN"],
    (.[] | [
      .app, .env,
      (.c.H.new // 0), (.c.M.new // 0), (.c.L.new // 0),
      ([.c[].triaged] | add // 0),
      .started
    ] | map(tostring))
  | @tsv
' | column -t -s $'\t'
```

### Output format

```
APP            ENVIRONMENT   HIGH  MEDIUM  LOW  TRIAGED  LAST_SCAN
payment-api    Production    5     12      8    3        1d ago
auth-service   Staging       3     4       1    0        2w ago
admin-portal   Development   0     0       0    0        2025-11-01
```

> **Note:** these are per-scan counts from each app + env's latest completed scan.
> HIGH/MEDIUM/LOW are new (untriaged) findings; TRIAGED sums all triaged findings.
> For per-finding triage detail, use Recipe 2.

---

## Recipe 2: App Deep Dive

**Question:** What did the last scan of a specific app find?

**What it produces:** The alerts from the most recent scan, highest severity first
(up to 10 alert types — see the cap above), with affected paths expanded for High
and Medium findings.

### Step 1 — Get the latest scan for the app

```bash
APP_NAME="<your-app-name>"   # --app takes a name or a UUID

# Full findings in one command
hawk op scan get --app "${APP_NAME}" --detail full --format json > /tmp/scan.json

SCAN_ID=$(jq -r '.scan.id' /tmp/scan.json)
SCAN_TS=$(jq -r '.scan.completed_at' /tmp/scan.json)
# Total alert types in the scan, to detect the 10-type cap
TOTAL_TYPES=$(hawk op scan get "${SCAN_ID}" --format json | jq '.severityStats | add // 0')

echo "Latest scan: ${SCAN_ID} (${SCAN_TS})"
echo "Platform URL: https://app.stackhawk.com/scans/${SCAN_ID}"
```

### Step 2 — Print the alert summary

```bash
# True affected-path count per alert type (total_paths stops at 10)
for pid in $(jq -r '.findings[].plugin_id' /tmp/scan.json); do
  hawk op scan get "${SCAN_ID}" --plugin-id "${pid}" --format json \
    | jq -c '{(.alert.pluginId): .alert.uriCount}'
done | jq -s 'add // {}' > /tmp/uri_counts.json

jq -r --argjson total "${TOTAL_TYPES}" --slurpfile counts /tmp/uri_counts.json '
  .findings
  | ["SEVERITY", "PLUGIN_ID", "ALERT_NAME", "CWE", "AFFECTED_PATHS"],
    (.[] | [
      .severity,
      .plugin_id,
      .plugin_name,
      (if .cwe_id then "CWE-\(.cwe_id)" else "—" end),
      ($counts[0][.plugin_id] // .total_paths | tostring)
    ]),
    (if length < $total
     then ["NOTE: showing \(length) of \($total) alert types; see the platform for the rest"]
     else empty end)
  | @tsv
' /tmp/scan.json | column -t -s $'\t'
```

### Step 3 — Expand affected paths for High and Medium alerts

Lists up to 10 paths per alert type; when Step 2 shows more, point the user to the
platform scan page for the rest.

```bash
jq -r '
  # Empty cells collapse in `column`, so print a dash instead
  def dash: if . == null or . == "" then "—" else . end;

  ["SEVERITY", "PLUGIN_ID", "METHOD", "URI", "PARAMETER", "TRIAGE_STATUS"],
  (.findings[]
    | select(.severity == "High" or .severity == "Medium")
    | . as $f
    | .paths[]
    | [
        $f.severity,
        $f.plugin_id,
        (.method | dash),
        (.uri | dash),
        (.param | dash),
        (if .status == "UNKNOWN" then "New" else .status end)
      ])
  | @tsv
' /tmp/scan.json | column -t -s $'\t'
```

### Output format

```
SEVERITY  PLUGIN_ID  ALERT_NAME                         CWE     AFFECTED_PATHS
High      40012      Cross Site Scripting (Reflected)   CWE-79  3
High      90022      Application Error Disclosure       CWE-200 1
Medium    10038      Content Security Policy (CSP)      —       8
Low       10096      Timestamp Disclosure               —       2

SEVERITY  PLUGIN_ID  METHOD  URI                PARAMETER  TRIAGE_STATUS
High      40012      POST    /api/users/search  q          New
High      40012      GET     /api/products      name       New
High      40012      GET     /api/items/filter  category   RISK_ACCEPTED
```

**Platform link** (always include when presenting results):

```
https://app.stackhawk.com/scans/${SCAN_ID}
```

---

## Recipe 3: Stale Apps

**Question:** Which apps have not been scanned recently?

**What it produces:** Every app + environment whose latest completed scan is older
than the threshold, plus apps with no completed scan at all, longest gap first.

### Step 1 — Fetch apps and completed scans

```bash
apps=$(hawk op app list --format json)
scans=$(hawk op scan list --status complete --sort-by started --sort-dir desc \
    --limit 10000 --format json)
```

### Step 2 — Find stale apps

```bash
STALE_DAYS=30

printf '%s\n%s' "${apps}" "${scans}" | jq -rs --argjson threshold "${STALE_DAYS}" '
  # Age in whole days from the `started` string ("3w ago" counts as 21)
  def age_days:
    if test("^[0-9]{4}-[0-9]{2}-[0-9]{2}$") then
      (now - (. + "T00:00:00Z" | fromdateiso8601)) / 86400 | floor
    elif test("^[0-9]+d ago$") then (capture("^(?<n>[0-9]+)").n | tonumber)
    elif test("^[0-9]+w ago$") then (capture("^(?<n>[0-9]+)").n | tonumber * 7)
    elif . == "--" then null
    else 0 end;

  .[0].data as $apps | .[1].data as $scans |

  # Latest completed scan per app + env (rows are newest-first)
  ($scans | reduce .[] as $s ({}; .[$s.app + "\u0000" + $s.env] //= $s) | [.[]])
    as $latest |
  ($latest | map({(.app): true}) | add // {}) as $scanned |

  [
    ($latest[]
      | (.started | age_days) as $d
      | select($d != null and $d > $threshold)
      | {app, env, last: .started, days: $d}),
    # Cloud-type apps are left out: their scans are not in the default scan list
    ($apps[]
      | select(.cloud == "" and ($scanned[.name] | not))
      | {app: .name, env: "—", last: "never", days: null})
  ]
  | sort_by(.days // 1e9) | reverse
  | ["APP", "ENVIRONMENT", "LAST_SCAN", "DAYS_AGO"],
    (.[] | [.app, .env, .last, (.days // "no completed scan" | tostring)])
  | @tsv
' | column -t -s $'\t'
```

### Output format

```
APP            ENVIRONMENT   LAST_SCAN    DAYS_AGO
admin-portal   —             never        no completed scan
auth-service   Development   2025-09-01   116
payment-api    Staging       2025-11-20   55
```

> **Precision:** `started` is a `YYYY-MM-DD` date once a scan is 4 weeks old, so
> ages are exact to the day for any threshold of 28 days or more. Below that,
> `Nw ago` is rounded down to whole weeks. `hawk op scan list` has no app UUID, so
> the never-scanned check matches apps by name.

### Recommendation

For each stale environment, present the following action:

> **Action required:** App `<name>` (`<environment>`) has not been scanned in
> `<N>` days. Run a HawkScan against this environment to refresh the security
> posture data. See the `hawkscan` plugin for scan configuration and invocation
> instructions.

---

## Recipe 4: What Changed Since Last Scan

**Question:** What is new or resolved compared to the previous scan of this app?

**What it produces:** Two sections — "New findings" (alerts in the latest scan but
not in the previous) and "Resolved findings" (alerts in the previous scan but not in
the latest), diffed by plugin ID across the two latest completed scans of one
environment.

### Step 1 — Get the two most recent scans and their alerts

```bash
APP_ID="<app-uuid>"     # scan list --app takes a UUID; get it from hawk op app list
ENV_NAME="<env-name>"   # e.g. Production

# Last 2 completed scans of this app + env, newest first
hawk op scan list --app "${APP_ID}" --env "${ENV_NAME}" --status complete \
    --sort-by started --sort-dir desc --limit 2 --format json > /tmp/last2.json

SCAN_A=$(jq -r '.data[0].id // empty' /tmp/last2.json)
SCAN_B=$(jq -r '.data[1].id // empty' /tmp/last2.json)
TS_A=$(jq -r '.data[0].started // empty' /tmp/last2.json)
TS_B=$(jq -r '.data[1].started // empty' /tmp/last2.json)

# Guard: need at least 2 completed scans
if [[ -z "${SCAN_A}" || -z "${SCAN_B}" ]]; then
  echo "ERROR: Need at least 2 completed scans to compute a diff." >&2
  exit 1
fi

echo "Latest scan : ${SCAN_A} (${TS_A})"
echo "Previous scan: ${SCAN_B} (${TS_B})"

# Fetch the alert types for each (at most 10 per scan) and each scan's total
hawk op scan get "${SCAN_A}" --detail full --format json | jq '.findings // []' > /tmp/alerts_a.json
hawk op scan get "${SCAN_B}" --detail full --format json | jq '.findings // []' > /tmp/alerts_b.json
TOTAL_A=$(hawk op scan get "${SCAN_A}" --format json | jq '.severityStats | add // 0')
TOTAL_B=$(hawk op scan get "${SCAN_B}" --format json | jq '.severityStats | add // 0')
```

### Step 2 — Diff the alert sets by plugin ID

```bash
diff_result=$(jq -n \
  --slurpfile latest /tmp/alerts_a.json \
  --slurpfile prev   /tmp/alerts_b.json \
  --argjson total_a "${TOTAL_A}" --argjson total_b "${TOTAL_B}" '
  ($latest[0]) as $l | ($prev[0]) as $p |
  {
    latest_ids: ($l | map(.plugin_id) | unique),
    prev_ids:   ($p | map(.plugin_id) | unique),
    latest_map: ($l | map({(.plugin_id): .}) | add // {}),
    prev_map:   ($p | map({(.plugin_id): .}) | add // {})
  } as $data |
  {
    new_findings: (
      $data.latest_ids - $data.prev_ids
      | map($data.latest_map[.])
      | sort_by(.severity | if . == "High" then 0 elif . == "Medium" then 1 else 2 end)
    ),
    resolved_findings: (
      $data.prev_ids - $data.latest_ids
      | map($data.prev_map[.])
      | sort_by(.severity | if . == "High" then 0 elif . == "Medium" then 1 else 2 end)
    ),
    unchanged_count: (
      [$data.latest_ids[], $data.prev_ids[]] | group_by(.) | map(select(length == 2)) | length
    ),
    # true when either scan has more than the 10 alert types hawk op returns
    partial: (($l | length) < $total_a or ($p | length) < $total_b)
  }
')
```

### Step 3 — Present the diff

```bash
echo "======================================================================"
echo "SCAN DIFF: ${APP_ID} / ${ENV_NAME}"
echo "  Latest:   ${SCAN_A}  (${TS_A})"
echo "  Previous: ${SCAN_B}  (${TS_B})"
echo "======================================================================"

echo ""
echo "--- NEW FINDINGS (appeared in latest scan) ---"
printf '%s' "${diff_result}" | jq -r '
  if (.new_findings | length) == 0 then "  (none)"
  else
    ["SEVERITY", "PLUGIN_ID", "ALERT_NAME", "CWE"],
    (.new_findings[] | [
      .severity,
      .plugin_id,
      .plugin_name,
      (if .cwe_id then "CWE-\(.cwe_id)" else "—" end)
    ])
    | @tsv
  end
' | column -t -s $'\t'

echo ""
echo "--- RESOLVED FINDINGS (present in previous scan, gone in latest) ---"
printf '%s' "${diff_result}" | jq -r '
  if (.resolved_findings | length) == 0 then "  (none)"
  else
    ["SEVERITY", "PLUGIN_ID", "ALERT_NAME", "CWE"],
    (.resolved_findings[] | [
      .severity,
      .plugin_id,
      .plugin_name,
      (if .cwe_id then "CWE-\(.cwe_id)" else "—" end)
    ])
    | @tsv
  end
' | column -t -s $'\t'

echo ""
printf '%s' "${diff_result}" | jq -r \
  '"Summary: \(.new_findings | length) new, \(.resolved_findings | length) resolved, \(.unchanged_count) unchanged",
   (if .partial then "WARNING: a scan has more than 10 alert types; hawk op returns only the top 10, so this diff is partial" else empty end)'

echo ""
echo "Platform links:"
echo "  Latest scan:   https://app.stackhawk.com/scans/${SCAN_A}"
echo "  Previous scan: https://app.stackhawk.com/scans/${SCAN_B}"
```

### Output format

```
======================================================================
SCAN DIFF: 0b3c… / Production
  Latest:   aaa-bbb-ccc  (1d ago)
  Previous: ddd-eee-fff  (2w ago)
======================================================================

--- NEW FINDINGS (appeared in latest scan) ---
SEVERITY  PLUGIN_ID  ALERT_NAME                        CWE
High      40012      Cross Site Scripting (Reflected)  CWE-79
Medium    10038      Content Security Policy (CSP)     —

--- RESOLVED FINDINGS (present in previous scan, gone in latest) ---
SEVERITY  PLUGIN_ID  ALERT_NAME                        CWE
Medium    10021      X-Content-Type-Options Header     —

Summary: 2 new, 1 resolved, 4 unchanged

Platform links:
  Latest scan:   https://app.stackhawk.com/scans/aaa-bbb-ccc
  Previous scan: https://app.stackhawk.com/scans/ddd-eee-fff
```

> **Note:** The diff is based on plugin ID (vulnerability type). An alert counted
> as "resolved" means the scanner no longer detected that vulnerability class — it
> does not guarantee the underlying issue was fixed in code. Always verify remediation
> through the platform before closing findings.
