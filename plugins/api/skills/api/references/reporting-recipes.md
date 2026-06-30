# StackHawk API Reporting Recipes

Pre-built compositions for common security reporting questions using `hawk op`.
Run `hawk op status` first to confirm authentication; set `HAWK_API_KEY` for
CI/CD pipelines.

**Setup (run once per shell session for CI/CD):**

```bash
export HAWK_API_KEY="hawk.xxxxxxxxxxxx"   # from app.stackhawk.com → Settings → API Keys
```

---

## Recipe 1: Org Security Posture

**Question:** Across all my apps, what is the current security situation?

**What it produces:** One row per app showing latest-scan finding counts by
severity, sorted by High findings descending.

### Step 1 — Fetch all apps and recent scans

```bash
apps=$(hawk op app list --format json)
scans=$(hawk op scan list --limit 500 --format json)
```

### Step 2 — Build the posture table

```bash
# Join latest scan per app to get severity counts
printf '%s\n%s' "${apps}" "${scans}" | jq -rs '
  .[0] as $apps | .[1] as $scans |

  # Build app name lookup: applicationId -> name
  ($apps.data | map({(.id): .name}) | add // {}) as $names |

  # Find latest completed scan per app
  ($scans.data
    | group_by(.applicationId)
    | map(
        sort_by(.startedTimestamp) | reverse |
        map(select(.status == "COMPLETED")) | .[0]
      )
    | map(select(. != null))
  ) as $latest |

  # Output sorted by High desc
  ($latest | sort_by(.highAlertCount // 0 | . * -1))
  | ["APP", "ENVIRONMENT", "HIGH", "MEDIUM", "LOW", "LAST_SCAN"],
    (.[] | [
      ($names[.applicationId] // .applicationId),
      (.environmentName // "—"),
      (.highAlertCount   // 0 | tostring),
      (.mediumAlertCount // 0 | tostring),
      (.lowAlertCount    // 0 | tostring),
      (.startedTimestamp // "never")
    ])
  | @tsv
' | column -t -s $'\t'
```

### Output format

```
APP            ENVIRONMENT   HIGH  MEDIUM  LOW  LAST_SCAN
payment-api    Production    5     12      8    2024-01-15T10:30:00Z
auth-service   Staging       3     4       1    2024-01-10T09:00:00Z
admin-portal   Development   0     0       0    2023-11-01T08:00:00Z
```

> **Note:** `hawk op scan list` returns per-scan alert totals. For live untriaged
> counts, use `hawk op scan get <SCAN_ID> --detail full --format json` and filter
> on `triageStatus`.

---

## Recipe 2: App Deep Dive

**Question:** What did the last scan of a specific app find?

**What it produces:** All alerts from the most recent scan, grouped by severity,
with affected URIs expanded for High and Medium findings.

### Step 1 — Get the latest scan for the app

```bash
APP_NAME="<your-app-name>"

# Full findings in one command
hawk op scan get --app "${APP_NAME}" --detail full --format json > /tmp/scan.json

SCAN_ID=$(jq -r '.scanId' /tmp/scan.json)
SCAN_TS=$(jq -r '.startedTimestamp' /tmp/scan.json)

echo "Latest scan: ${SCAN_ID} (started ${SCAN_TS})"
echo "Platform URL: https://app.stackhawk.com/scans/${SCAN_ID}"
```

### Step 2 — Print alert summary

```bash
jq -r '
  def sev_rank: if . == "High" then 0 elif . == "Medium" then 1 else 2 end;

  .alerts
  | sort_by(.severity | sev_rank)
  | ["SEVERITY", "PLUGIN_ID", "ALERT_NAME", "CWE", "AFFECTED_URIS"],
    (.[] | [
      .severity,
      (.pluginId | tostring),
      .alertName,
      (.cweId // "—"),
      (.affectedUriCount | tostring)
    ])
  | @tsv
' /tmp/scan.json | column -t -s $'\t'
```

### Step 3 — Expand affected paths for High and Medium alerts

```bash
jq -r '
  .findings[]
  | select(.severity == "High" or .severity == "Medium")
  | "=== [\(.severity)] \(.alertName) (plugin \(.pluginId)) ===",
    (
      ["METHOD", "URI", "PARAMETER", "TRIAGE_STATUS"],
      (.uris[] | [
        .method,
        .uri,
        (.parameter // "—"),
        (.triageStatus // "New")
      ])
      | @tsv
    )
' /tmp/scan.json | column -t -s $'\t'
```

### Output format

```
SEVERITY  PLUGIN_ID  ALERT_NAME                         CWE     AFFECTED_URIS
High      40012      Cross-Site Scripting (Reflected)   CWE-79  3
High      90022      Application Error Disclosure       —       1
Medium    10038      Content Security Policy (CSP)      —       8
Low       10096      Timestamp Disclosure               —       2

=== [High] Cross-Site Scripting (Reflected) (plugin 40012) ===
METHOD  URI                  PARAMETER  TRIAGE_STATUS
POST    /api/users/search    q          New
GET     /api/products        name       New
GET     /api/items/filter    category   Reopened
```

**Platform link** (always include when presenting results):

```
https://app.stackhawk.com/scans/${SCAN_ID}
```

---

## Recipe 3: Stale Apps

**Question:** Which apps have not been scanned recently?

**What it produces:** All apps where the last completed scan is either missing or
older than 30 days, sorted by staleness (longest gap first).

### Step 1 — Fetch apps and recent scans

```bash
apps=$(hawk op app list --format json)
scans=$(hawk op scan list --limit 500 --format json)
```

### Step 2 — Find stale apps

```bash
STALE_DAYS=30

printf '%s\n%s' "${apps}" "${scans}" | jq -rs --argjson threshold "${STALE_DAYS}" '
  .[0] as $apps | .[1] as $scans |

  ($apps.data | map({(.id): .name}) | add // {}) as $names |

  ($scans.data
    | group_by(.applicationId)
    | map(
        sort_by(.startedTimestamp) | reverse |
        map(select(.status == "COMPLETED")) | .[0]
      )
    | map(select(. != null))
    | map({
        appId: .applicationId,
        env:   .environmentName,
        ts:    .startedTimestamp
      })
  ) as $latest_scans |

  [
    ($latest_scans[] |
      . as $s |
      (if $s.ts == null then 999999
       else (now - ($s.ts | sub("\\.[0-9]+Z$"; "Z") | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime)) / 86400 | floor
       end) as $days |
      select($days > $threshold) |
      {
        app:  ($names[$s.appId] // $s.appId),
        env:  ($s.env // "—"),
        last: ($s.ts // "never"),
        days: (if $s.ts == null then "never scanned" else ($days | tostring) + " days ago" end)
      }
    )
  ]
  | sort_by(.days | if . == "never scanned" then "zzz" else . end) | reverse

  | ["APP", "ENVIRONMENT", "LAST_SCAN", "STALENESS"],
    (.[] | [.app, .env, .last, .days])
  | @tsv
' | column -t -s $'\t'
```

### Output format

```
APP            ENVIRONMENT   LAST_SCAN             STALENESS
admin-portal   QA            never                 never scanned
auth-service   Development   2023-09-01T08:00:00Z  116 days ago
payment-api    Staging       2023-11-20T14:00:00Z  55 days ago
```

### Recommendation

For each stale environment, present the following action:

> **Action required:** App `<name>` (`<environmentName>`) has not been scanned in
> `<N>` days. Run a HawkScan against this environment to refresh the security
> posture data. See the `hawkscan` plugin for scan configuration and invocation
> instructions.

---

## Recipe 4: What Changed Since Last Scan

**Question:** What is new or resolved compared to the previous scan of this app?

**What it produces:** Two sections — "New findings" (alerts in the latest scan but
not in the previous) and "Resolved findings" (alerts in the previous scan but not in
the latest), diffed by `pluginId`.

### Step 1 — Get the two most recent scans and their alerts

```bash
APP_NAME="<your-app-name>"

# List last 2 scans
hawk op scan list --app "${APP_NAME}" --limit 2 --format json > /tmp/last2.json

SCAN_A=$(jq -r '.data[0].scanId' /tmp/last2.json)
SCAN_B=$(jq -r '.data[1].scanId' /tmp/last2.json)
TS_A=$(jq -r '.data[0].startedTimestamp' /tmp/last2.json)
TS_B=$(jq -r '.data[1].startedTimestamp' /tmp/last2.json)

echo "Latest scan : ${SCAN_A} (${TS_A})"
echo "Previous scan: ${SCAN_B} (${TS_B})"

# Guard: need at least 2 scans
if [[ "${SCAN_A}" == "null" || "${SCAN_B}" == "null" ]]; then
  echo "ERROR: Need at least 2 completed scans to compute a diff." >&2
  exit 1
fi

# Fetch alerts for each
hawk op scan get "${SCAN_A}" --format json | jq '.alerts' > /tmp/alerts_a.json
hawk op scan get "${SCAN_B}" --format json | jq '.alerts' > /tmp/alerts_b.json
```

### Step 2 — Diff the alert sets by pluginId

```bash
diff_result=$(jq -n \
  --slurpfile latest /tmp/alerts_a.json \
  --slurpfile prev   /tmp/alerts_b.json '
  ($latest[0]) as $l | ($prev[0]) as $p |
  {
    latest_ids: ($l | map(.pluginId | tostring) | unique),
    prev_ids:   ($p | map(.pluginId | tostring) | unique),
    latest_map: ($l | map({((.pluginId | tostring)): .}) | add // {}),
    prev_map:   ($p | map({((.pluginId | tostring)): .}) | add // {})
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
    )
  }
')
```

### Step 3 — Present the diff

```bash
echo "======================================================================"
echo "SCAN DIFF: ${APP_NAME}"
echo "  Latest:   ${SCAN_A}  (${TS_A})"
echo "  Previous: ${SCAN_B}  (${TS_B})"
echo "======================================================================"

echo ""
echo "--- NEW FINDINGS (appeared in latest scan) ---"
printf '%s' "${diff_result}" | jq -r '
  if (.new_findings | length) == 0 then "  (none)"
  else
    ["SEVERITY", "PLUGIN_ID", "ALERT_NAME", "CWE", "AFFECTED_URIS"],
    (.new_findings[] | [
      .severity,
      (.pluginId | tostring),
      .alertName,
      (.cweId // "—"),
      (.affectedUriCount | tostring)
    ])
    | @tsv
  end
' | column -t -s $'\t'

echo ""
echo "--- RESOLVED FINDINGS (present in previous scan, gone in latest) ---"
printf '%s' "${diff_result}" | jq -r '
  if (.resolved_findings | length) == 0 then "  (none)"
  else
    ["SEVERITY", "PLUGIN_ID", "ALERT_NAME", "CWE", "AFFECTED_URIS_PREV"],
    (.resolved_findings[] | [
      .severity,
      (.pluginId | tostring),
      .alertName,
      (.cweId // "—"),
      (.affectedUriCount | tostring)
    ])
    | @tsv
  end
' | column -t -s $'\t'

echo ""
printf '%s' "${diff_result}" | jq -r \
  '"Summary: \(.new_findings | length) new, \(.resolved_findings | length) resolved, \(.unchanged_count) unchanged"'

echo ""
echo "Platform links:"
echo "  Latest scan:   https://app.stackhawk.com/scans/${SCAN_A}"
echo "  Previous scan: https://app.stackhawk.com/scans/${SCAN_B}"
```

### Output format

```
======================================================================
SCAN DIFF: payment-api
  Latest:   aaa-bbb-ccc  (2024-01-15T10:00:00Z)
  Previous: ddd-eee-fff  (2024-01-10T09:00:00Z)
======================================================================

--- NEW FINDINGS (appeared in latest scan) ---
SEVERITY  PLUGIN_ID  ALERT_NAME                        CWE     AFFECTED_URIS
High      40012      Cross-Site Scripting (Reflected)  CWE-79  3
Medium    10038      Content Security Policy (CSP)     —       8

--- RESOLVED FINDINGS (present in previous scan, gone in latest) ---
SEVERITY  PLUGIN_ID  ALERT_NAME                        CWE     AFFECTED_URIS_PREV
Medium    10021      X-Content-Type-Options Header      —       1

Summary: 2 new, 1 resolved, 4 unchanged

Platform links:
  Latest scan:   https://app.stackhawk.com/scans/aaa-bbb-ccc
  Previous scan: https://app.stackhawk.com/scans/ddd-eee-fff
```

> **Note:** The diff is based on `pluginId` (vulnerability type). An alert counted
> as "resolved" means the scanner no longer detected that vulnerability class — it
> does not guarantee the underlying issue was fixed in code. Always verify remediation
> through the platform before closing findings.
