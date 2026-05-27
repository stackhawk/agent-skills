# Bootstrap Manifest Schema (Contract B)

`bootstrap/manifest.yaml` is the contract between Skill A (the authoring skill,
"bootstrap"), human reviewers, and the future Runner (Tool C). It is the
authoritative runbook and dependency graph for seed operations: every step,
every file reference, every idempotency predicate, and every emitted credential
lives here. This document describes schema `version: 1`. Backward-compatible
extensions (new optional fields) are allowed within v1; any breaking change
(removing fields, changing semantics of existing fields, reordering required
execution semantics) requires `version: 2`.

## Table of Contents

1. [Top-level structure](#top-level-structure)
2. [prerequisites.env entries](#prerequisitesenv-entries)
3. [prerequisites.services entries](#prerequisitesservices-entries)
4. [Step schema](#step-schema)
5. [Step types](#step-types)
6. [Idempotency primitives](#idempotency-primitives)
7. [Dependency model](#dependency-model)
8. [outputs section](#outputs-section)
9. [Self-validation rules](#self-validation-rules)
10. [Complete example](#complete-example)
11. [Forbidden patterns](#forbidden-patterns)

---

## Top-level structure

```yaml
version: 1                          # REQUIRED. Schema version. Currently 1.
name: <repo>-hawkscan-bootstrap     # REQUIRED. Slug-style identifier; conventionally
                                    #   <target-repo>-hawkscan-bootstrap. No spaces.
description: <one sentence>         # REQUIRED. What this bootstrap creates and why.

prerequisites:                      # REQUIRED. Things that must be true before any step runs.
  env: [ ... ]                      # OPTIONAL. Required env vars. Each entry: name + description.
  services: [ ... ]                 # OPTIONAL. Services that must be reachable before any step.
  notes: |                          # OPTIONAL. Free-form prose for humans. Markdown OK.
    <markdown ok>

targets:                            # REQUIRED. Service-name → connection map. Each step's `target:` field
                                    # (scalar form) references an entry here. Object-form `target:` on a step
                                    # is an inline alternative — but using `targets:` is preferred for DRY.
  <service-name>:
    kind: postgres | mysql | sqlite | mongo | http | grpc | none
    connection: <URL or path; env interpolation supported>

steps: [ ... ]                      # REQUIRED. Ordered list. At least one step.
                                    #   Execution order: topo-sort over depends_on.
                                    #   Absence of depends_on means depends on previous entry.

outputs:                            # REQUIRED. Values the seed produced.
  KEY: value                        #   Skill A writes these to .bootstrap-credentials.env.
```

All seven top-level keys (`version`, `name`, `description`, `prerequisites`,
`targets`, `steps`, `outputs`) are required. The manifest is invalid without any of them.

---

## prerequisites.env entries

Each entry under `prerequisites.env` declares an environment variable that must
be set in the shell before the Runner (Tool C) executes any step.

### Schema

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | string | yes | SCREAMING_SNAKE_CASE. The env var name exactly as it appears in `$VAR` interpolation. |
| `description` | string | yes | Where the value comes from. Free-form; visible to the Runner and to humans reading the manifest. |

### Example

```yaml
prerequisites:
  env:
    - name: AUTH_SERVICE_DB_URL
      description: "Postgres connection string for auth-service — e.g. postgres://user:pass@localhost:5432/auth_dev"
    - name: TEST_PASS
      description: "Sourced from .bootstrap-credentials.env; the seeded user's password"
```

The Runner fails fast if any declared env var is absent or empty at launch time.
It does not attempt to execute steps in a degraded state.

---

## prerequisites.services entries

Each entry under `prerequisites.services` declares a network service that must
be reachable before any step runs. The Runner verifies each service's
`check` before starting the step list.

### Schema

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | string | yes | Logical service name. Matches the subdirectory under `bootstrap/`. |
| `url` | string | yes | Full URL, with env interpolation via `${VAR:default}`. |
| `check` | enum | yes | How the Runner verifies. v1 supports only `http_ready`. |

**`check` values (v1):** `http_ready` — Runner issues a GET to `url` and waits
until it receives any 2xx or 3xx response (or up to a configurable timeout).
`tcp_open` and `command_ok` are reserved for v2.

### Example

```yaml
prerequisites:
  services:
    - name: gateway-api
      url: ${GATEWAY_URL:http://localhost:9000}
      check: http_ready
    - name: auth-service
      url: ${AUTH_SERVICE_URL:http://localhost:8080}
      check: http_ready
```

Env interpolation syntax `${VAR:default}` expands `$VAR` if set; falls back to
`default` if unset. The default must be a complete URL. No default means the
env var is effectively required.

---

## Step schema

A step is one seed operation: one file executed against one target. Steps are
the unit of idempotency checking, dependency tracking, and retry in Tool C.

```yaml
- id: <stable-id>                   # REQUIRED. Slug (lowercase, hyphens). Used in depends_on.
                                    #   Must be unique within the manifest. Stable across reruns —
                                    #   changing an id breaks depends_on references and breaks
                                    #   Runner state tracking.
  description: <one line>           # REQUIRED. Human summary of what the step does.
  service: <service-name>           # REQUIRED. Logical service this step targets.
                                    #   Matches the subdirectory name under bootstrap/.
  type: sql | http | grpc | mongo | shell
                                    # REQUIRED. Drives how the Runner interprets `file`.
  file: <relative/path>             # REQUIRED. Path relative to bootstrap/. Must exist in the
                                    #   emitted tree when the manifest is written.

  # REQUIRED. Two forms supported:
  # (a) Scalar — references an entry in the top-level `targets:` map (preferred for repo seeds
  #     that touch the same service multiple times — DRY).
  target: <service-name>
  # (b) Object — inline target spec for single-use connections.
  #     target:
  #       kind: postgres | mysql | sqlite | mongo | http | grpc | none
  #       connection: <URL or path; env interpolation supported>
  #                   For http: base_url key instead of connection.

  depends_on: [ <id>, ... ]         # OPTIONAL. Explicit ordering. Topo-sorted by Runner.
                                    #   Absence ⇒ implicit dependency on previous step in list.
  creates: [ "<kind>:<name>", ... ] # OPTIONAL (recommended). Documents what the step produces.
                                    #   Examples: "org:example-test-org", "user:test-owner@example.com"
                                    #   v1: documentation only. v2 may enable typed cross-step refs.

  # REQUIRED. Two forms supported:
  # (a) Scalar — names a well-known strategy the runner understands directly:
  #       on_conflict_do_nothing | insert_ignore | insert_or_ignore | upsert |
  #       where_not_exists_and_on_conflict | on_conflict_and_upsert | custom_predicate | none |
  #       check_sql | check_http | check_command
  #     When using a `check_*` scalar, the step must also carry a sibling field of the same
  #     name with the predicate (e.g., `idempotency: check_sql` + `check_sql: "SELECT 1 FROM ..."`).
  idempotency: on_conflict_do_nothing
  # (b) Object — explicit predicate the runner evaluates before running the step:
  #     idempotency:
  #       check_sql: "SELECT 1 FROM ... WHERE ..."
  #       # OR
  #       check_http:
  #         method: GET
  #         path: <path>
  #         expect_status: <int>
  #         expect_jq: <jq expression>
  #       # OR
  #       check_command: "..."
  #       # OR
  #       none: true               # Runner refuses unless --allow-non-idempotent.
```

Both forms are valid v1. The scalar form is more compact and is what the bootstrap skill emits by
default when an entire seed run targets one service per row (matching the top-level `targets:` map).
Use the object form when a single step needs a custom connection target or a predicate that isn't
well-known to the runner.

The `target` sub-object (form b) uses `connection:` for database-style targets and
`base_url:` for HTTP-style targets. Only one of the two is used per step.

---

## Step types

Five types are supported in v1. Each type maps to a distinct execution driver
in Tool C and to a distinct file convention on disk.

### sql

**Description:** Execute SQL against a relational database (Postgres, MySQL, or
SQLite). The most common step type.

**File extension:** `.sql`

**Target shape (either form is valid):**
```yaml
# Scalar form — references top-level targets: map (preferred):
target: auth-service

# Object form — inline spec for single-use connections:
target:
  kind: postgres | mysql | sqlite
  connection: ${DB_URL}
```

**Example — Postgres step creating a test organization:**

Manifest fragment (scalar forms for target and idempotency — preferred):
```yaml
- id: auth-orgs
  description: Create test organization in auth-service
  service: auth-service
  type: sql
  file: auth-service/001-orgs.sql
  target: auth-service
  creates: [ "org:example-test-org" ]
  idempotency: on_conflict_do_nothing
  check_sql: "SELECT 1 FROM organizations WHERE name = 'Example Test Org';"
```

The object form is also accepted:
```yaml
- id: auth-orgs
  description: Create test organization in auth-service
  service: auth-service
  type: sql
  file: auth-service/001-orgs.sql
  target:
    kind: postgres
    connection: ${AUTH_SERVICE_DB_URL}
  creates: [ "org:example-test-org" ]
  idempotency:
    check_sql: "SELECT 1 FROM organizations WHERE name = 'Example Test Org';"
```

Referenced file — `bootstrap/auth-service/001-orgs.sql`:
```sql
-- Seed test organization for scanning.
-- Uses ON CONFLICT DO NOTHING so re-running is safe.
INSERT INTO organizations (id, name, created_at)
VALUES (
  '00000000-0000-0000-0000-000000000001',
  'Example Test Org',
  NOW()
)
ON CONFLICT (id) DO NOTHING;
```

---

### http

**Description:** Execute one or more HTTP requests against a running service,
using REST Client format (`.http` files). Preferred over shell for API-only
services. Use PUT over POST when the service supports it (idempotent by
default).

**File extension:** `.http` (REST Client format, compatible with VS Code REST
Client extension and IntelliJ HTTP Client)

**Target shape (either form is valid):**
```yaml
# Scalar form — references top-level targets: map (preferred):
target: gateway-api

# Object form — inline spec for single-use connections:
target:
  kind: http
  base_url: ${SERVICE_URL:http://localhost:8080}
```

**Example — PUT to link an app to an environment:**

Manifest fragment (scalar target; object idempotency for a bespoke HTTP check):
```yaml
- id: gateway-link
  description: Link app to env via gateway-api REST API
  service: gateway-api
  type: http
  file: gateway-api/001-link-app-to-env.http
  target: gateway-api
  depends_on: [ auth-users, inventory-apps ]
  creates: [ "env-link:target-app-1" ]
  idempotency:
    check_http:
      method: GET
      path: /v1/apps/target-app-1/envs
      expect_status: 200
      expect_jq: ".envs | length > 0"
```

The object form for `target` is also accepted (used when no top-level `targets:` map exists):
```yaml
  target:
    kind: http
    base_url: ${GATEWAY_URL:http://localhost:9000}
```

Referenced file — `bootstrap/gateway-api/001-link-app-to-env.http`:
```http
### Link target-app-1 to the default scan environment

PUT {{$env GATEWAY_URL}}/v1/apps/target-app-1/envs/Development
Content-Type: application/json
Authorization: Bearer {{$env GATEWAY_ADMIN_TOKEN}}

{
  "orgId": "00000000-0000-0000-0000-000000000001",
  "description": "Default scan environment"
}
```

---

### grpc

**Description:** Invoke a gRPC method against a running service. The step file
is a shell-executable script that wraps a `grpcurl` invocation with the
appropriate proto descriptor, address, and JSON payload.

**File extension:** `.sh` (grpcurl wrapper script)

**Target shape (either form is valid):**
```yaml
# Scalar form — references top-level targets: map (preferred):
target: registry

# Object form — inline spec for single-use connections:
target:
  kind: grpc
  connection: ${GRPC_SERVICE_ADDR:localhost:50051}
```

**Example — grpcurl step registering a test tenant:**

Manifest fragment (scalar target; object idempotency with check_command for gRPC):
```yaml
- id: registry-tenant
  description: Register test tenant via gRPC registry service
  service: registry
  type: grpc
  file: registry/001-create-tenant.sh
  target: registry
  creates: [ "tenant:example-test-tenant" ]
  idempotency:
    check_command: >-
      grpcurl -plaintext -proto registry/proto/tenant.proto
      -d '{"name":"example-test-tenant"}'
      ${REGISTRY_GRPC_ADDR:-localhost:50051}
      registry.TenantService/GetTenant
      2>&1 | grep -q 'example-test-tenant'
```

The object form for `target` is also accepted:
```yaml
  target:
    kind: grpc
    connection: ${REGISTRY_GRPC_ADDR:localhost:50051}
```

Referenced file — `bootstrap/registry/001-create-tenant.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

# Create test tenant via gRPC registry service.
# Requires: grpcurl on PATH, REGISTRY_GRPC_ADDR set (or defaults to localhost:50051).

ADDR="${REGISTRY_GRPC_ADDR:-localhost:50051}"

grpcurl \
  -plaintext \
  -proto registry/proto/tenant.proto \
  -d '{
    "name":        "example-test-tenant",
    "displayName": "Example Test Tenant",
    "ownerId":     "00000000-0000-0000-0000-000000000001"
  }' \
  "${ADDR}" \
  registry.TenantService/CreateTenant
```

---

### mongo

**Description:** Execute a Mongo shell script (`.js`) against a MongoDB
instance. Scripts use the `db.*` API available in `mongosh`. Prefer
`findOneAndUpdate` with `{ upsert: true }` for idempotent writes.

**File extension:** `.js` (mongo shell / mongosh compatible)

**Target shape (either form is valid):**
```yaml
# Scalar form — references top-level targets: map (preferred):
target: catalog

# Object form — inline spec for single-use connections:
target:
  kind: mongo
  connection: ${MONGO_URI:mongodb://localhost:27017/appdb}
```

**Example — mongosh step upserting a test user document:**

Manifest fragment (scalar target; object idempotency with check_command for Mongo):
```yaml
- id: mongo-users
  description: Upsert test user document in MongoDB user collection
  service: catalog
  type: mongo
  file: catalog/001-users.js
  target: catalog
  creates: [ "user:test-owner@example.com" ]
  idempotency:
    check_command: >-
      mongosh "${CATALOG_MONGO_URI:-mongodb://localhost:27017/catalog}" --quiet
      --eval 'db.users.countDocuments({email:"test-owner@example.com"})' | grep -q '^[1-9]'
```

The object form for `target` is also accepted:
```yaml
  target:
    kind: mongo
    connection: ${CATALOG_MONGO_URI:mongodb://localhost:27017/catalog}
```

Referenced file — `bootstrap/catalog/001-users.js`:
```js
// Upsert test user for HawkScan scanning.
// findOneAndUpdate with upsert:true is safe to replay.
db.users.findOneAndUpdate(
  { email: "test-owner@example.com" },
  {
    $setOnInsert: {
      _id:       "00000000-0000-0000-0000-000000000020",
      email:     "test-owner@example.com",
      password:  process.env.TEST_PASS || (() => { throw new Error('TEST_PASS not set — source .bootstrap-credentials.env first'); })(),
      orgId:     "00000000-0000-0000-0000-000000000001",
      role:      "SCAN_USER",
      createdAt: new Date(),
    },
  },
  { upsert: true, returnDocument: "after" }
);
```

---

### shell

**Description:** Run a shell script as an escape hatch when no other type
fits — e.g., invoking a CLI binary, calling a proprietary SDK, or executing
a compound setup not expressible as SQL or a single HTTP call. The script
runs with all prerequisite env vars present. Use sparingly; prefer `sql`,
`http`, `grpc`, or `mongo` when the service type is known.

**File extension:** `.sh`

**Target shape:**
```yaml
# Object form — the most common for shell steps, since kind: none has no connection URL
# and is typically not placed in a top-level targets: map:
target:
  kind: none

# Scalar form — valid if the service IS declared in the top-level targets: map
# (uncommon for shell steps but accepted by the Runner):
# target: platform
```

(`kind: none` means there is no discrete connection URL — the script manages
its own connectivity using env vars.)

**Example — shell step calling a CLI to provision an API key:**

Manifest fragment (object idempotency with check_command; object target since kind: none):
```yaml
- id: apikey-provision
  description: Provision a scan API key via the internal admin CLI
  service: platform
  type: shell
  file: platform/001-provision-apikey.sh
  target:
    kind: none
  depends_on: [ auth-users ]
  creates: [ "apikey:bootstrap-scan-key" ]
  idempotency:
    check_command: "platform-admin apikey list --user test-owner@example.com | grep -q bootstrap-scan-key"
```

Referenced file — `bootstrap/platform/001-provision-apikey.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

# Provision a scan API key for the test user.
# Requires: platform-admin CLI on PATH, PLATFORM_ADMIN_TOKEN set.

platform-admin apikey create \
  --user  "test-owner@example.com" \
  --name  "bootstrap-scan-key" \
  --scope "scan:read scan:write" \
  --token "${PLATFORM_ADMIN_TOKEN}"
```

---

## Idempotency primitives

Every step must declare exactly one idempotency primitive. The Runner evaluates
the primitive before running the step: if the check passes (entity already
exists), the step is skipped. If the check fails (entity absent or
unreachable), the step executes. For per-dialect SQL guidance (Postgres
`ON CONFLICT`, MySQL `INSERT IGNORE`, SQLite `INSERT OR IGNORE`), see
`idempotency-patterns.md`.

### Scalar strategy → underlying primitive mapping

When `idempotency:` is a scalar string (the preferred compact form), the Runner
maps it to the underlying primitive described in the subsections below:

| Scalar strategy                      | Underlying primitive                                                    |
|--------------------------------------|-------------------------------------------------------------------------|
| `on_conflict_do_nothing`             | `check_sql` based on unique-key match                                   |
| `insert_ignore`                      | `check_sql`                                                             |
| `insert_or_ignore`                   | `check_sql`                                                             |
| `upsert`                             | `check_sql`                                                             |
| `where_not_exists_and_on_conflict`   | `check_sql`                                                             |
| `on_conflict_and_upsert`             | `check_sql`                                                             |
| `custom_predicate`                   | use the explicit object form (`check_sql` / `check_http` / `check_command`) |
| `none`                               | `none: true`                                                            |

Use the explicit object form (documented below) when the scalar strategies are not sufficient —
for example, to write a bespoke `check_http` or `check_command` predicate, or whenever the step
type (`grpc`, `mongo`, `shell`) requires a command-based check rather than SQL.

### check_sql

**Semantics:** Execute a SQL query. If the query returns ≥1 row, the entity
already exists — skip the step. If it returns 0 rows (or errors), run the step.

```yaml
idempotency:
  check_sql: "SELECT 1 FROM users WHERE email = 'test-owner@example.com';"
```

The query must be a SELECT that returns data when the seed is already present.
Avoid side-effecting queries (INSERT, UPDATE, DELETE) in `check_sql`. The Runner
connects using the same `target.connection` as the step itself.

Multi-line queries are valid YAML scalars:
```yaml
idempotency:
  check_sql: |
    SELECT 1 FROM organizations o
    JOIN users u ON u.org_id = o.id
    WHERE u.email = 'test-owner@example.com'
      AND o.name  = 'Example Test Org';
```

---

### check_http

**Semantics:** Issue an HTTP request to the step's service. If the response
status matches `expect_status` and the response body matches the `expect_jq`
predicate (evaluated via `jq`), the entity already exists — skip the step.
Either condition alone failing causes the step to run.

```yaml
idempotency:
  check_http:
    method: GET
    path: /v1/apps/target-app-1/envs
    expect_status: 200
    expect_jq: ".envs | length > 0"
```

| Sub-field | Type | Required | Notes |
|-----------|------|----------|-------|
| `method` | string | yes | HTTP method. v1 recommends GET for checks. |
| `path` | string | yes | Path appended to `target.base_url`. |
| `expect_status` | int | yes | HTTP status code that indicates the resource exists. |
| `expect_jq` | string | yes | `jq` expression applied to the response body. Must evaluate to a truthy value to indicate existence. |

The Runner uses the same `target.base_url` for the check as for the step.
Authentication headers (if needed) are sourced from the same env vars the
step file uses.

---

### check_command

**Semantics:** Execute a shell command. If the command exits 0, the entity
already exists — skip the step. Any non-zero exit (or stdout/stderr indicating
absence) causes the step to run.

```yaml
idempotency:
  check_command: >-
    psql "${AUTH_SERVICE_DB_URL}" -tAc
    "SELECT 1 FROM users WHERE email='test-owner@example.com'"
    | grep -q 1
```

`check_command` is the most flexible primitive and the escape hatch for step
types where `check_sql` and `check_http` are unavailable (e.g., `grpc`,
`mongo`, `shell`). The command runs in a shell with all prerequisite env vars
present. Use POSIX-compatible shell syntax; do not rely on bash-only features.

---

### none: true

**Semantics:** The step is not idempotent. The Runner will refuse to run a
manifest containing `none: true` unless the flag `--allow-non-idempotent` is
explicitly passed.

```yaml
idempotency:
  none: true   # JUSTIFY: this CLI call is not safe to replay; no query API available
```

**This should be RARE.** Skill A will emit a warning when writing any step
with `none: true` and prompt the user to confirm that no idempotency check is
feasible. The justification comment is mandatory by convention (though not
enforced by schema). In code review, an unjustified `none: true` is a red flag.

---

## Dependency model

### Explicit ordering with `depends_on`

```yaml
depends_on: [ <step-id>, ... ]
```

The Runner topologically sorts all steps by their `depends_on` edges before
execution. A step with multiple `depends_on` entries does not run until all
listed dependencies have completed successfully.

### Implicit ordering

A step with no `depends_on` key implicitly depends on the previous step in the
list. This keeps simple linear sequences readable without repeating IDs.

```yaml
steps:
  - id: auth-orgs       # no depends_on → depends on nothing (first step)
    ...

  - id: auth-users      # no depends_on → implicitly depends on auth-orgs
    ...

  - id: inventory-apps  # no depends_on → implicitly depends on auth-users
    ...
```

### Parallel-eligible steps using explicit depends_on

When two steps are independent (both depend on the same upstream step but not
on each other), declare `depends_on` explicitly on both to signal that to the
Runner. In v1, the Runner executes steps sequentially even when they could
run in parallel; `depends_on` correctness is still required so that the
topo-sort produces a valid schedule for any future parallel Runner.

```yaml
steps:
  - id: auth-orgs
    # ... no depends_on: first step

  - id: auth-users
    depends_on: [ auth-orgs ]      # explicit: requires org to exist first
    # ...

  - id: inventory-apps
    depends_on: [ auth-orgs ]      # explicit: requires org too, but NOT auth-users
                                   #   → parallel-eligible with auth-users in v2 Runner
    # ...

  - id: gateway-link
    depends_on: [ auth-users, inventory-apps ]   # requires both to complete first
    # ...
```

### `creates` — declarative output documentation

```yaml
creates: [ "org:example-test-org", "user:test-owner@example.com" ]
```

`creates` is documentation in v1. It tells humans (and AI assistants) what
entity each step produces. Possible `kind:` prefixes: `org`, `user`, `app`,
`tenant`, `apikey`, `env-link`, or any domain-appropriate noun.

v2 may enable typed cross-step references:
```yaml
# v2 aspirational — NOT valid in v1
depends_on: [ "user:test-owner@example.com" ]
```

---

## outputs section

The `outputs:` block is a flat key-value map of strings. It contains every
credential, ID, or URL that downstream consumers (hawkscan, integration tests,
CI) need after the seed is complete.

```yaml
outputs:
  TEST_USER: test-owner@example.com
  TEST_PASS: ExampleSeedPass1!
  TEST_ORG_ID: 00000000-0000-0000-0000-000000000001
  TEST_APP_ID: 00000000-0000-0000-0000-000000000010
  GATEWAY_LOGIN_URL: ${GATEWAY_URL}/login
```

Values may contain env interpolation (`${VAR}` or `${VAR:default}`); the Runner
expands these at write time. Keys must be SCREAMING_SNAKE_CASE.

### How Skill A writes outputs

Skill A writes each key-value pair to `.bootstrap-credentials.env` in the
target repo root, one pair per line:

```
TEST_USER=test-owner@example.com
TEST_PASS=ExampleSeedPass1!
TEST_ORG_ID=00000000-0000-0000-0000-000000000001
TEST_APP_ID=00000000-0000-0000-0000-000000000010
GATEWAY_LOGIN_URL=http://localhost:9000/login
```

No quoting unless values contain spaces. No `export` prefix. The file is
sourced by downstream tools via `. .bootstrap-credentials.env` (POSIX) or
`source .bootstrap-credentials.env` (bash).

`.bootstrap-credentials.env` is gitignored. The repo carries
`bootstrap/credentials.env.example` (a checked-in template with placeholder
values) for discoverability.

### How downstream tools consume outputs

- **hawkscan:** detects `.bootstrap-credentials.env` in the repo root at
  Phase 1c / Phase 1c.5 and substitutes `${TEST_USER}`, `${TEST_PASS}`, etc.
  into the auth block of `stackhawk.yml`. The bootstrap skill's parent SKILL.md
  (`../SKILL.md`) documents the handoff to hawkscan; see also
  `idempotency-patterns.md` for how steps should preserve idempotency when they
  write to outputs.
- **Tool C (future Runner):** sources `.bootstrap-credentials.env` before
  executing any step, making the values available for env interpolation in
  step files and `target.connection` fields.
- **CI:** sources the file (generated by a CI-aware run of the Runner) before
  the hawk scan step in the pipeline.

---

## Self-validation rules

Before writing the manifest to disk, Skill A performs these five checks. If any
check fails, the skill surfaces the problem to the user and does not write a
broken manifest.

1. **Required step fields present.** Every step has `id`, `type`, `file`, `target`,
   and `idempotency`. A step missing any of these is invalid.

2. **`depends_on` references resolve.** Every ID listed in any step's
   `depends_on` must match the `id` of another step in the manifest. A
   reference to a nonexistent ID is surfaced as an error with the referencing
   step's ID and the missing target ID.

3. **No circular dependencies.** A topological sort over the `depends_on`
   edges must succeed. If a cycle is detected (e.g., A → B → A), the skill
   reports the cycle members and stops.

4. **Every `file:` path exists.** For each step, the path `bootstrap/<file>`
   must exist in the emitted tree at the moment the manifest is written. A
   manifest pointing to a nonexistent file is invalid.

5. **`outputs:` keys are referenced.** Every key in `outputs:` should be
   produced by or referenced in at least one step (either as part of the step's
   SQL/HTTP body or in the step's `creates` list). Unreferenced output keys
   produce a warning (not an error) — the key may be intentional (e.g., a
   computed URL), but the warning prompts the user to confirm.

---

## Complete example

Full manifest for the generic two-upstream example (gateway-api + auth-service +
inventory-service). This is the reference shape that Skill A produces for a
typical scenario: an API gateway with no own DB, two upstream Postgres services,
and a REST API link step.

The manifest uses a top-level `targets:` map (service name → connection details)
so each step can reference its target by name as a scalar string rather than
repeating connection details inline. Per-step `idempotency:` is a scalar string
(the strategy name) alongside an explicit `check_sql` / `check_http` field — the
compact form the skill emits in practice. The expanded object form
(`idempotency: { check_sql: "..." }`) documented in §Idempotency primitives
above is equivalent and accepted by the Runner.

```yaml
version: 1
name: gateway-api-hawkscan-bootstrap
description: Seeds users, orgs, and apps required for authenticated HawkScan against gateway-api.

targets:
  auth-service:
    kind: postgres
    connection: ${AUTH_SERVICE_DB_URL}
  inventory-service:
    kind: postgres
    connection: ${INVENTORY_SERVICE_DB_URL}
  gateway-api:
    kind: http
    base_url: ${GATEWAY_URL:http://localhost:9000}

prerequisites:
  env:
    - name: AUTH_SERVICE_DB_URL
      description: "Postgres DSN for auth-service — e.g. postgres://user:pass@localhost:5432/auth_dev"
    - name: INVENTORY_SERVICE_DB_URL
      description: "Postgres DSN for inventory-service — e.g. postgres://user:pass@localhost:5432/inventory_dev"
    - name: GATEWAY_URL
      description: "Base URL for gateway-api — e.g. http://localhost:9000"
  services:
    - name: auth-service
      url: ${AUTH_SERVICE_URL:http://localhost:8080}
      check: http_ready
    - name: inventory-service
      url: ${INVENTORY_SERVICE_URL:http://localhost:9090}
      check: http_ready
    - name: gateway-api
      url: ${GATEWAY_URL:http://localhost:9000}
      check: http_ready
  notes: |
    Start the stack before running: `docker-compose up -d` or your env's equivalent.
    Ensure AUTH_SERVICE_DB_URL and INVENTORY_SERVICE_DB_URL are set in your shell
    or .env file before invoking the Runner.
    See bootstrap/credentials.env.example for a template.

steps:
  - id: auth-orgs
    description: Create test organization in auth-service
    service: auth-service
    type: sql
    file: auth-service/001-orgs.sql
    target: auth-service
    creates: [ "org:example-test-org" ]
    idempotency: check_sql
    check_sql: "SELECT 1 FROM organizations WHERE name = 'Example Test Org';"

  - id: auth-users
    description: Create test user, bound to test org
    service: auth-service
    type: sql
    file: auth-service/002-users.sql
    target: auth-service
    depends_on: [ auth-orgs ]
    creates: [ "user:test-owner@example.com" ]
    idempotency: check_sql
    check_sql: "SELECT 1 FROM users WHERE email = 'test-owner@example.com';"

  - id: inventory-apps
    description: Create scannable app, owned by test org
    service: inventory-service
    type: sql
    file: inventory-service/001-apps.sql
    target: inventory-service
    depends_on: [ auth-orgs ]
    creates: [ "app:target-app-1" ]
    idempotency: check_sql
    check_sql: "SELECT 1 FROM applications WHERE name = 'target-app-1';"

  - id: gateway-link
    description: Link app to env via gateway-api REST API (no DB; goes through API gateway)
    service: gateway-api
    type: http
    file: gateway-api/001-link-app-to-env.http
    target: gateway-api
    depends_on: [ auth-users, inventory-apps ]
    creates: [ "env-link:target-app-1" ]
    idempotency: check_http
    check_http:
      method: GET
      path: /v1/apps/target-app-1/envs
      expect_status: 200
      expect_jq: ".envs | length > 0"

outputs:
  TEST_USER: test-owner@example.com
  TEST_PASS: ExampleSeedPass1!
  TEST_PASSWORD: ExampleSeedPass1!  # alias for usernamePassword recipe compatibility
  TEST_ORG_ID: 00000000-0000-0000-0000-000000000001
  TEST_APP_ID: 00000000-0000-0000-0000-000000000010
  GATEWAY_LOGIN_URL: ${GATEWAY_URL}/login
```

`TEST_PASSWORD` is emitted whenever a password-storage column was detected and seeded (see
`discovery.md` §Password-Storage Detection). Both `TEST_PASS` and `TEST_PASSWORD` carry the
same plaintext value; `TEST_PASS` preserves backward compatibility with existing integrations
while `TEST_PASSWORD` is the key hawkscan's `usernamePassword` auth recipe references.

### Referenced step files

**`bootstrap/auth-service/001-orgs.sql`**
```sql
-- Seed test organization.
INSERT INTO organizations (id, name, created_at)
VALUES (
  '00000000-0000-0000-0000-000000000001',
  'Example Test Org',
  NOW()
)
ON CONFLICT (id) DO NOTHING;
```

**`bootstrap/auth-service/002-users.sql`**
```sql
-- Seed test user bound to the test organization.
-- Supply password via: psql -v test_pass="$TEST_PASS" -f 002-users.sql
INSERT INTO users (id, email, password_hash, org_id, role, created_at)
VALUES (
  '00000000-0000-0000-0000-000000000002',
  'test-owner@example.com',
  crypt(:'test_pass', gen_salt('bf')),
  '00000000-0000-0000-0000-000000000001',
  'SCAN_USER',
  NOW()
)
ON CONFLICT (email) DO NOTHING;
```

**`bootstrap/inventory-service/001-apps.sql`**
```sql
-- Seed scannable application owned by the test org.
INSERT INTO applications (id, name, org_id, created_at)
VALUES (
  '00000000-0000-0000-0000-000000000010',
  'target-app-1',
  '00000000-0000-0000-0000-000000000001',
  NOW()
)
ON CONFLICT (name, org_id) DO NOTHING;
```

**`bootstrap/gateway-api/001-link-app-to-env.http`**
```http
### Link target-app-1 to the default scan environment

PUT {{$env GATEWAY_URL}}/v1/apps/target-app-1/envs/Development
Content-Type: application/json
Authorization: Bearer {{$env GATEWAY_ADMIN_TOKEN}}

{
  "orgId": "00000000-0000-0000-0000-000000000001",
  "description": "Default scan environment"
}
```

---

## Forbidden patterns

These anti-patterns make manifests harder to review, test, and maintain.
Skill A should never emit them; code review should block them.

### Embedding step content as YAML strings in the manifest

**Wrong:**
```yaml
- id: auth-orgs
  type: sql
  # BAD: SQL embedded as a multi-line YAML string
  content: |
    INSERT INTO organizations (id, name)
    VALUES ('00000000...', 'Example Test Org')
    ON CONFLICT DO NOTHING;
```

**Right:** put the SQL in `auth-service/001-orgs.sql` and reference it via `file:`.

SQL embedded in YAML loses syntax highlighting, SQL linting, diff readability,
and the ability to run the file directly with `psql`. The same applies to
`.http` content embedded in YAML strings. The manifest references files by
path; the files own their content.

---

### Hardcoding credentials in step files

**Wrong:**
```sql
-- BAD: password literal in a checked-in file
INSERT INTO users (email, password) VALUES ('test-owner@example.com', 'ExampleSeedPass1!');
```

**Right:** use env interpolation and store values in `.bootstrap-credentials.env` (gitignored):
```sql
INSERT INTO users (email, password_hash)
VALUES ('test-owner@example.com', crypt(current_setting('app.test_pass'), gen_salt('bf')))
ON CONFLICT (email) DO NOTHING;
```

Or pass the password via the Runner's env substitution. `.bootstrap-credentials.env`
is the handoff point; step files reference `${TEST_PASS}` or a connection-level
session setting. The checked-in `credentials.env.example` contains only
placeholder values.

---

### Using `none: true` without a justification comment

**Wrong:**
```yaml
idempotency:
  none: true
```

**Right:**
```yaml
idempotency:
  none: true   # JUSTIFY: vendor CLI has no query API; no safe replay check available
```

`none: true` is a footgun. Any manifest that reaches code review with
`none: true` and no comment should be rejected until a justification is added
(or, better, until a real idempotency check is implemented). Skill A will
warn when emitting `none: true` and prompt the user to confirm that no
alternative exists.

---

### Mixing service responsibilities in one step file

**Wrong:**
```yaml
# WRONG — one step file touching two services
- id: gateway-setup
  service: gateway-api
  type: sql
  file: gateway-api/001-setup.sql   # file inside performs inserts against BOTH auth-service DB and inventory-service DB
  target: { kind: postgres, connection: ${AUTH_SERVICE_DB_URL} }
  # ... (idempotency check can only cover one service)
```

**Right:**
```yaml
# RIGHT — one step per service
- id: auth-orgs
  service: auth-service
  type: sql
  file: auth-service/001-orgs.sql
  target: { kind: postgres, connection: ${AUTH_SERVICE_DB_URL} }
  idempotency: { check_sql: "SELECT 1 FROM organizations WHERE name = 'Example Test Org';" }

- id: inventory-apps
  service: inventory-service
  type: sql
  file: inventory-service/001-apps.sql
  target: { kind: postgres, connection: ${INVENTORY_SERVICE_DB_URL} }
  depends_on: [ auth-orgs ]
  idempotency: { check_sql: "SELECT 1 FROM applications WHERE name = 'target-app-1';" }
```

Each step targets exactly one service so its idempotency check, target, and
dependency edges are unambiguous. A multi-service step body would force the
runner to coordinate transactions across services, which the manifest format
does not support.

Mixed-service step files make the manifest's dependency graph unreliable (the
Runner cannot know which services a mixed file actually touches), break
re-runability when one service is healthy and another is not, and make diffs
harder to attribute.
