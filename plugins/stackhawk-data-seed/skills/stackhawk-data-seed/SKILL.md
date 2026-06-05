---
name: stackhawk-data-seed
version: 1.12.0
description: >
  Set up checked-in seed data so authenticated HawkScan can reach non-trivial
  paths. Drives the `hawk perch seed` preflight, designs the minimum seed
  manifest from the repo digest, then validates and finalizes it via
  `hawk perch seed validate` / `finalize` — emitting reviewed artifacts under
  data-seed/ (manifest.yaml, per-service SQL / HTTP / gRPC / Mongo / shell
  scripts, and a .data-seed-credentials.env handoff hawkscan consumes).
  Use when the user says "set up data for HawkScan", "my scan has no data to
  hit", "seed this repo for scanning", or as a first-time-setup step before
  invoking hawkscan on a fresh repo. NOT autonomous — the user explicitly asks.
---

# StackHawk Data Seed Skill

This skill produces checked-in, reproducible seed-data artifacts for a target repo so authenticated HawkScan finds non-empty results. The `hawk perch seed` command provides the deterministic steps — a static repo **pre-flight** (storage + upstream detection), a manifest **validator**, and an artifact **finalizer**. This skill supplies the reasoning between them: it reads the pre-flight's digest and designs the minimum seed manifest. It works the same across every agent that can run a subprocess and read its output.

It does NOT run the artifacts, start the environment, or write `stackhawk.yml` — those belong to the human, the user's tooling, and the `hawkscan` skill respectively.

---

## When to Run

Invoke explicitly when:

- User says "set up data for HawkScan" / "seed this repo" / "my scan has no data to hit."
- Configuring HawkScan against a repo for the first time and the app needs authenticated routes to scan.
- A previous `data-seed/` exists but the data shape changed (new entity types, new upstream service).

Do NOT run autonomously after code changes — this is a setup tool, not a per-commit safety net.

---

## Phase 0: Preflight

### 0.1 — Confirm working directory

The user must invoke from inside the target repo (the repo HawkScan will scan):

```bash
test -d .git || echo "NOT-A-REPO"
pwd
```

If not a git repo, ask the user to `cd` to the target repo and re-invoke.

### 0.2 — Confirm hawk supports the seed flow (capability gate)

This skill drives the caller-driven `hawk perch seed` subcommands (`validate` and `finalize`). Probe for them directly:

```bash
if hawk perch seed validate --help >/dev/null 2>&1 && hawk perch seed finalize --help >/dev/null 2>&1; then
  echo "SEED-FLOW-OK"
else
  echo "SEED-FLOW-UNSUPPORTED"
fi
hawk version 2>/dev/null || hawk --version 2>/dev/null   # for the message only; never gates
```

If `SEED-FLOW-UNSUPPORTED`, **PUNT** — do NOT hand-author seed data:

> Your installed hawk (`<version from above, if any>`) doesn't include the data-seed flow yet. Upgrade to **hawk ≥ `__MIN_HAWK_SEED_VERSION__`** to enable seeding:
> `brew upgrade stackhawk/cli/hawk` (or download from https://download.stackhawk.com/hawk), then re-invoke this skill.

The probe — not the version number — is the gate; the version is shown only to help the user.

### 0.3 — Check for existing data-seed

```bash
test -d data-seed && echo "EXISTS"
```

If `data-seed/` exists, ask the user whether to **augment**, **replace** (`mv data-seed data-seed.bak-$(date +%s)`), or **cancel**.

---

## Phase 1: Run the pre-flight and route on the outcome

```bash
# With an app host (recommended when known — enriches the digest with served-OpenAPI routes):
hawk perch seed --events json --app-host "$APP_HOST"
# Without a host — OMIT the flag entirely; do NOT pass an empty --app-host:
hawk perch seed --events json
```

- `--app-host` — the target app's URL (e.g. `http://localhost:8080`). Optional; when reachable it enriches the digest with served-OpenAPI routes. Ask the user if a host is handy, otherwise omit it.
- `--output <dir>` — optional; directory to write `data-seed/` under (defaults to the current directory).

**stdout** carries JSONL phase events (one JSON object per line — parse with `jq -c .`). **stderr** carries human-readable text — tee it for the user, don't discard it.

Phase events: `starting` → `extracting` → `done`. **Read the `done` event's `outcome`** and branch:

| `outcome` | What it means | What you do |
|---|---|---|
| `nothing_to_seed` | No local datastore and no upstreams | Report the honest no-op and stop. Nothing to author. |
| `no_local_storage` | Entities live in upstream services | The `done` payload lists `upstreams` / `upstreamResults` (each with a `resolvedPath` or `unresolvedReason`) and writes a shared `.data-seed-identity.env`. For each **resolved** upstream, run this whole flow again with the working directory rooted at that upstream's `resolvedPath` (a fresh subprocess/session at that path — a bare `cd` may not persist across calls for every agent). It reuses the shared identity so cross-service IDs line up. Report any **unresolved** upstreams to the user. |
| `needs_synthesis` | A local datastore is present | Continue to Phase 2 using the `done` payload's `digest`. |

If the process exits non-zero, report the `done` event's message (plus relevant stderr) and stop — do not improvise seed artifacts. If no `done` event was emitted at all (e.g. the process crashed), report the last stderr line.

---

## Phase 2: Design the manifest (your job)

From the pre-flight `digest` (storage kind, migrations, routes, schema signals), design the **minimum** seed needed to authenticate and exercise routes, and write `data-seed/manifest.yaml`.

**Methodology:**

1. Pick the smallest set of entities that unblock authenticated, non-trivial routes — typically one org, one user (with credentials), and at least one owned resource (app/project/record) the routes read.
2. Order steps by foreign-key dependency (create the org before the user that references it, etc.).
3. Make every step **idempotent** (e.g. `INSERT … ON CONFLICT DO NOTHING`, upserts, "create if absent") so replaying the seed is safe.
4. Keep it minimal. Do NOT start services or run the artifacts.

**v1 manifest contract** (what `hawk perch seed validate` enforces) — a valid manifest is a YAML doc with these top-level keys:

```yaml
version: 1                 # must be exactly 1
name: <repo>-data-seed     # identifier
description: <one line>    # what this seed sets up
prerequisites: {}          # map; tools/services the steps assume (may be empty)
targets: {}                # map; datastores/endpoints the steps write to (may be empty)
steps: []                  # list; the ordered, idempotent seed operations (may be empty)
```

**No-op manifests:** a valid manifest with empty `prerequisites`, `targets`, and `steps` is an acceptable, honest result when there is genuinely nothing to seed — never fabricate seed records to look productive. (In practice the pre-flight returns `nothing_to_seed`/`no_local_storage` before Phase 2 for storage-less repos; this guidance is here for completeness.)

**Shared identity (cross-service consistency):** if `.data-seed-identity.env` is present (or `SEED_ORG_ID` / `SEED_USER_ID` / `SEED_APP_ID` / `SEED_USER_EMAIL` / `SEED_USER_PASSWORD` are in the environment), create the seeded entities with **those exact IDs/values** — do not mint your own. This keeps the same org/user/app consistent across every upstream service so a gateway's cross-service routes resolve.

---

## Phase 3: Validate

```bash
hawk perch seed validate data-seed/manifest.yaml --events json
```

Read the `done` event: `{"valid": true}` → proceed to Phase 4. `{"valid": false, "errors": [...]}` (and a non-zero exit) → fix the reported `errors` in the manifest and re-validate. After **3** unsuccessful validate attempts, report the errors and stop — do NOT finalize an invalid manifest.

---

## Phase 4: Finalize

```bash
hawk perch seed finalize data-seed/manifest.yaml --events json
```

Writes the manifest + per-service scripts under `data-seed/` and the `.data-seed-credentials.env` handoff. The `done` event carries `{"success": true, "writtenFiles": [...], "credsPath": "..."}`. A non-zero exit or `success: false` → report the message and stop.

> Event-parsing note: the terminal `done` keys differ per subcommand — the pre-flight and `finalize` use `success`, `validate` uses `valid`. **Treat any non-zero exit as failure** regardless of payload.

---

## Phase 5: Handoff

On a successful finalize:

```
Data seed complete. Created under <outputDir>:
- data-seed/manifest.yaml
- per-service seed scripts
- .data-seed-credentials.env (gitignored)

Next steps:
1. Review data-seed/manifest.yaml and the per-service files.
2. Start your stack, then replay the manifest (see data-seed/README.md if present).
3. Invoke hawkscan to configure stackhawk.yml — it reads .data-seed-credentials.env automatically.
```

Commit reminder:

```bash
git add data-seed/ .gitignore
git commit -m "chore: add data seed artifacts for HawkScan"
```

(Stage `.gitignore` only if you added an entry for `.data-seed-credentials.env`.)

`.data-seed-credentials.env` is gitignored and must not be committed.

---

## Boundaries with hawkscan

This skill never writes or modifies `stackhawk.yml`, selects authentication recipes, or creates Apps/Envs on the StackHawk platform. The handoff is one file: `.data-seed-credentials.env`. Hawkscan reads it and plugs the values into whatever auth recipe it selects.
