# StackHawk API Endpoint Catalog

Base URL: `https://api.stackhawk.com`

All requests (except `/auth/login`) require:
```
Authorization: Bearer <jwt>
```

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Applications](#2-applications)
3. [Environments](#3-environments)
4. [Scan Results — Drill-Down Chain](#4-scan-results--drill-down-chain)
5. [Organization-Wide](#5-organization-wide)
6. [Teams](#6-teams)
7. [Pagination Patterns](#7-pagination-patterns)

---

## 1. Authentication

### Login — exchange API key for JWT

```
GET /api/v1/auth/login
```

**Required header:**
```
X-ApiKey: <your-api-key>
```

**Key response fields:**
```json
{
  "token": "<jwt>",
  "expiresIn": 3600
}
```

Store `token` and use it as the Bearer JWT for all subsequent requests. Tokens expire; refresh before expiry using the endpoint below.

---

### Refresh JWT

```
GET /api/v1/auth/refresh-token
```

**Required header:**
```
Authorization: Bearer <current-jwt>
```

**Key response fields:**
```json
{
  "token": "<new-jwt>",
  "expiresIn": 3600
}
```

Call this before the current token expires to avoid a full re-login. Replace the stored `token` with the new value.

---

## 2. Applications

### List applications (V2 — paginated)

```
GET /api/v2/org/{orgId}/apps
```

**Path params:**
- `orgId` — organization UUID

**Query filters (all optional):**

| Param | Type | Description |
|-------|------|-------------|
| `query` | string | Name search substring |
| `appIds` | string[] | Filter to specific app UUIDs |
| `teamIds` | string[] | Filter to apps owned by these teams |
| `applicationStatus` | string | `ACTIVE` or `ENV_INCOMPLETE` |
| `applicationTypes` | string[] | `STANDARD` or `CLOUD` |

Also accepts V2 pagination params: `pageSize`, `page`, `pageToken` (see [Section 7](#7-pagination-patterns)).

**Key response fields:**
```json
{
  "applications": [
    {
      "applicationId": "<uuid>",
      "name": "My API",
      "applicationStatus": "ACTIVE",
      "applicationType": "STANDARD"
    }
  ],
  "currentPage": "p_0",
  "hasNext": true,
  "hasPrev": false,
  "totalCount": 42
}
```

`applicationStatus` values: `ACTIVE` (fully configured), `ENV_INCOMPLETE` (missing environment config).
`applicationType` values: `STANDARD` (self-hosted), `CLOUD` (cloud-hosted target).

---

### Get single application

```
GET /api/v1/app/{appId}
```

**Path params:**
- `appId` — application UUID

Returns the full application object including settings and configuration details.

---

### Create application

```
POST /api/v1/org/{orgId}/app
```

**Path params:**
- `orgId` — organization UUID

**Request body:** application creation payload (name, type, team assignment).

---

### Update application

```
POST /api/v1/app/{appId}
```

**Path params:**
- `appId` — application UUID

**Request body:** fields to update on the application.

---

### Delete application

```
DELETE /api/v1/app/{appId}
```

**Path params:**
- `appId` — application UUID

---

## 3. Environments

### List environments (V2 — paginated)

```
GET /api/v2/org/{orgId}/envs
```

**Path params:**
- `orgId` — organization UUID

**Query filters (all optional):**

| Param | Type | Description |
|-------|------|-------------|
| `query` | string | Name search substring |
| `appIds` | string[] | Filter to envs belonging to these apps |
| `envIds` | string[] | Filter to specific environment UUIDs |
| `teamIds` | string[] | Filter to envs owned by these teams |
| `lastScanDate` | string | ISO 8601 date filter on last scan timestamp |
| `lastScanStatus` | string | Filter by last scan result status |
| `applicationTypes` | string[] | `STANDARD` or `CLOUD` |
| `sortField` | string | Field to sort by |
| `sortDir` | string | `ASC` or `DESC` |

Also accepts V2 pagination params: `pageSize`, `page`, `pageToken`.

**Key response fields:**
```json
{
  "environments": [
    {
      "environmentId": "<uuid>",
      "environmentName": "Production",
      "applicationId": "<uuid>",
      "lastScanId": "<uuid>",
      "lastScanTimestamp": "2024-01-15T10:30:00Z",
      "lastScanStatus": "COMPLETED",
      "lastScanHighUntriaged": 3,
      "lastScanMediumUntriaged": 7,
      "lastScanLowUntriaged": 12,
      "repositoriesCount": 2,
      "thirtyDayCommitActivity": 45
    }
  ],
  "currentPage": "p_0",
  "hasNext": true,
  "hasPrev": false,
  "totalCount": 15
}
```

`lastScanHighUntriaged`, `lastScanMediumUntriaged`, `lastScanLowUntriaged` — untriaged finding counts by severity from the most recent scan. Use these for at-a-glance posture assessment without fetching full scan results.

---

### Create environment

```
POST /api/v1/app/{appId}/env
```

**Path params:**
- `appId` — application UUID

**Request body:** environment creation payload (name, configuration).

---

### Update environment

```
POST /api/v1/app/{appId}/env/{envId}
```

**Path params:**
- `appId` — application UUID
- `envId` — environment UUID

**Request body:** fields to update on the environment.

---

### Delete environment

```
DELETE /api/v1/app/{appId}/env/{envId}
```

**Path params:**
- `appId` — application UUID
- `envId` — environment UUID

---

## 4. Scan Results — Drill-Down Chain

This is the primary chain for investigating security findings. Follow the steps in order — each step produces the identifier needed for the next step.

```
Step 1: List scans for org   →  extract scanId
Step 2: List alerts for scan →  extract pluginId
Step 3: List findings (URIs) for alert
Step 4: Get detailed evidence for alert
```

---

### Step 1 — List scan results for org

```
GET /api/v1/scan/{orgId}
```

**Path params:**
- `orgId` — organization UUID

Accepts V1 pagination params: `pageSize`, `pageToken`.

**Key response fields:**
```json
{
  "applicationScanResults": [
    {
      "scanId": "<uuid>",
      "applicationId": "<uuid>",
      "environmentId": "<uuid>",
      "environmentName": "Production",
      "status": "COMPLETED",
      "startedTimestamp": "2024-01-15T10:00:00Z",
      "completedTimestamp": "2024-01-15T10:28:00Z",
      "duration": 1680,
      "highAlertCount": 2,
      "mediumAlertCount": 5,
      "lowAlertCount": 8,
      "policyName": "Default",
      "tags": [
        { "name": "Branch", "value": "main" }
      ]
    }
  ],
  "nextPageToken": 1,
  "totalCount": 87
}
```

**Connecting field:** Extract `scanId` from each result. Pass it to Step 2.

---

### Step 2 — List alerts for a scan

```
GET /api/v1/scan/{scanId}/alerts
```

**Path params:**
- `scanId` — scan UUID from Step 1

Accepts V1 pagination params: `pageSize`, `pageToken`.

**Key response fields:**
```json
{
  "applicationAlert": [
    {
      "pluginId": "40012",
      "alertName": "Cross-Site Scripting (Reflected)",
      "severity": "High",
      "affectedUriCount": 3,
      "cweId": "CWE-79",
      "externalReferences": [
        { "name": "OWASP", "url": "https://owasp.org/..." }
      ]
    }
  ],
  "nextPageToken": 1,
  "totalCount": 15
}
```

`severity` values: `High`, `Medium`, `Low`.

**Connecting field:** Extract `pluginId` from each alert. Pass it to Step 3.

---

### Step 3 — List findings (URIs) for an alert

```
GET /api/v1/scan/{scanId}/alert/{pluginId}
```

**Path params:**
- `scanId` — scan UUID from Step 1
- `pluginId` — alert plugin ID from Step 2

Accepts V1 pagination params: `pageSize`, `pageToken`.

**Key response fields:**
```json
{
  "applicationScanAlertUris": [
    {
      "uri": "/api/users/search",
      "method": "POST",
      "triageStatus": "New",
      "parameter": "q"
    }
  ],
  "nextPageToken": 1,
  "totalCount": 3
}
```

`triageStatus` values: `New`, `Accepted`, `False Positive`, `Reopened`.

Use this step to identify which specific endpoints are affected before pulling full evidence.

---

### Step 4 — Get detailed alert message and evidence

```
GET /api/v1/scan/{scanId}/alert/{alertId}/message
```

**Path params:**
- `scanId` — scan UUID from Step 1
- `alertId` — alert identifier (use `pluginId` from Step 2)

**Key response fields:**
```json
{
  "description": "Cross-site Scripting (XSS) attack description...",
  "solution": "Validate and encode all user-supplied input...",
  "evidence": "Attack string used: <script>alert(1)</script>",
  "request": "POST /api/users/search HTTP/1.1\n...",
  "response": "HTTP/1.1 200 OK\n...<script>alert(1)</script>..."
}
```

Use `evidence`, `request`, and `response` to construct reproduce-able `curl` commands for the coding agent's fix tasks.

---

## 5. Organization-Wide

### Query findings across entire org

```
GET /api/v1/org/{orgId}/findings
```

**Path params:**
- `orgId` — organization UUID

Use this for broad posture reporting (e.g., "how many High findings does the org have today?") without needing to iterate through individual scans.

Accepts V1 pagination params: `pageSize`, `pageToken`.

---

### List org members

```
GET /api/v1/org/{orgId}/members
```

**Path params:**
- `orgId` — organization UUID

**Key response fields:**
```json
{
  "members": [
    {
      "stackhawkId": "<uuid>",
      "provider": "google",
      "external": false,
      "createdTimestamp": "2023-06-01T12:00:00Z"
    }
  ]
}
```

---

### Get audit log

```
GET /api/v1/org/{orgId}/audit
```

**Path params:**
- `orgId` — organization UUID

**Key response fields:**
```json
{
  "auditLog": [
    {
      "userActivityType": "SCAN_STARTED",
      "organizationActivityType": "MEMBER_INVITED",
      "userId": "<uuid>",
      "userName": "Jane Smith",
      "userEmail": "jane@example.com",
      "payload": {},
      "timestamp": "2024-01-15T10:00:00Z"
    }
  ]
}
```

---

## 6. Teams

### List teams

```
GET /api/v1/org/{orgId}/teams
```

**Path params:**
- `orgId` — organization UUID

Returns an array of teams with their IDs and names.

---

### Get team details

```
GET /api/v1/org/{orgId}/team/{teamId}
```

**Path params:**
- `orgId` — organization UUID
- `teamId` — team UUID

Returns team name, list of associated applications, and list of member users.

---

### Create team

```
POST /api/v1/org/{orgId}/team
```

**Path params:**
- `orgId` — organization UUID

**Request body:** team creation payload (name, initial members).

---

### Update team

```
PUT /api/v1/org/{orgId}/team/{teamId}
```

**Path params:**
- `orgId` — organization UUID
- `teamId` — team UUID

**Request body:** fields to update on the team (name, members).

---

### Delete team

```
DELETE /api/v1/org/{orgId}/team/{teamId}
```

**Path params:**
- `orgId` — organization UUID
- `teamId` — team UUID

---

### Reassign application to team

```
PUT /api/v1/org/{orgId}/team/{teamId}/application
```

**Path params:**
- `orgId` — organization UUID
- `teamId` — team UUID (the destination team)

**Request body:** application UUID(s) to assign to this team.

---

## 7. Pagination Patterns

StackHawk uses two pagination schemes. Check the endpoint version (`/api/v1/` vs `/api/v2/`) to determine which to use.

---

### V1 Pagination (integer token)

Used by: scan results, alerts, findings, members, audit log, and most v1 endpoints.

**Request params:**

| Param | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `pageSize` | integer | 10 | 1–1000 | Number of results per page |
| `pageToken` | integer | 0 | ≥ 0 | Zero-based page index |

**Response fields:**

| Field | Type | Description |
|-------|------|-------------|
| `nextPageToken` | integer or null | Token for the next page. `null` when on the last page |
| `totalCount` | integer | Total number of results across all pages |

**Iteration pattern:**
```
pageToken = 0
loop:
  response = GET /api/v1/... ?pageSize=100&pageToken={pageToken}
  process response.items
  if response.nextPageToken is null → stop
  pageToken = response.nextPageToken
```

---

### V2 Pagination (string key)

Used by: `/api/v2/org/{orgId}/apps`, `/api/v2/org/{orgId}/envs`.

**Request params:**

| Param | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `pageSize` | integer | 10 | 1–1000 | Number of results per page |
| `page` | string | — | `p_*` format | Opaque page key returned by prior response |
| `pageToken` | integer | — | ≥ 0 | Numeric offset within the page key |

**Response fields:**

| Field | Type | Description |
|-------|------|-------------|
| `currentPage` | string | Opaque key for the current page (e.g., `p_0`) |
| `hasNext` | boolean | `true` if there is a next page |
| `hasPrev` | boolean | `true` if there is a previous page |
| `totalCount` | integer | Total number of results across all pages |

**Iteration pattern:**
```
page = undefined (omit on first request)
loop:
  response = GET /api/v2/... ?pageSize=100&page={page}
  process response.items
  if not response.hasNext → stop
  page = response.currentPage  (advance by incrementing numeric suffix or use next key if provided)
```

For V2, start with no `page` param. If `hasNext` is `true`, re-request with the next `page` key. The exact key format is `p_<N>` where N is a zero-based page index — increment `N` on each request to walk forward.
