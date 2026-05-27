---
name: bootstrap
version: 1.8.0
description: >
  Read a target repo (and any upstream service repos it depends on),
  propose the minimum seed entities required for authenticated HawkScan
  to find non-trivial paths, dialog with the user to confirm/adjust,
  then emit checked-in artifacts: per-service SQL / HTTP / gRPC / Mongo /
  shell scripts, a manifest.yaml that orders them, and a
  .bootstrap-credentials.env handoff file that hawkscan consumes.
  Use when the user says "set up data for HawkScan", "my scan has no
  data to hit", "bootstrap this repo for scanning", or as a planned
  first-time-setup step before invoking hawkscan on a fresh repo. NOT
  autonomous — the user explicitly asks.
---

# Bootstrap Skill

This skill produces checked-in, reproducible seed-data artifacts for a target repository so HawkScan has authenticated entities to scan. It runs once per repo (or once per major data-shape change) and emits files under `bootstrap/` that humans review, commit, and eventually replay via the future Runner (Tool C).

It does NOT run the artifacts. It does NOT start the environment. It does NOT write `stackhawk.yml`. Those concerns belong to the human, the user's environment tooling, and the `hawkscan` skill respectively.

---

## When to Run This Skill

Invoke explicitly when one of these is true:

- User says "set up data for HawkScan" / "bootstrap this repo" / "my scan has no data to hit."
- User is configuring HawkScan against a repo for the first time and the app needs authenticated routes to scan.
- A previous `bootstrap/` exists but the data shape has changed (new entity types, new upstream service added).

Do NOT run autonomously after code changes — this skill is a setup tool, not a per-commit safety net.

---

## Phase 0: Preflight

Run these checks first; if any fails, stop and tell the user.

### 0.1 — Confirm working directory

The user must invoke this skill from inside the target repo (the repo HawkScan will scan). Verify:

```bash
test -d .git || echo "NOT-A-REPO"
pwd
```

If not in a git repo, ask the user to `cd` to the correct directory and re-invoke.

### 0.2 — Check for existing bootstrap

```bash
test -d bootstrap && echo "EXISTS"
```

If `bootstrap/` already exists, ask the user whether to:
- **Augment** — read the existing manifest and only propose additions for new entities.
- **Replace** — back up the existing dir (`mv bootstrap bootstrap.bak-$(date +%s)`) and start fresh.
- **Cancel** — exit without changes.

### 0.3 — Confirm scanning intent

Confirm the user wants the seed for **authenticated HawkScan** (not just generic dev data). The skill's defaults are tuned for "the minimum that lets an authenticated scan find non-empty results."

---

## Phase 1: Discover

Build an internal model of the target repo + its upstream service deps + each service's storage type. This phase is read-only.

### 1.1 — Repo-scan pass (target repo)

Scan for signals. See `references/discovery.md` for the full per-ecosystem detection matrix.

Cover at minimum:
- **Storage layer evidence:** Liquibase, Flyway, Prisma, Alembic, Knex, Django, Rails, gorm, Mongo schema files, DynamoDB CDK, Cosmos SDK.
- **API definitions:** OpenAPI, protobuf, GraphQL schemas.
- **Auth signals:** Spring Security, Passport, Auth0 SDK, custom middleware.
- **Env config:** `.env*`, `application.yml`, `appsettings.json`, `config.json`.
- **Compose:** `docker-compose.yml` services + ports.
- **Integration tests:** they often contain the working minimal seed.
- **Client imports / SDK uses** that imply upstream services.

→ Deep reference: [`references/discovery.md`](references/discovery.md)

### 1.2 — Dep-discovery pass

Identify upstream services referenced (host:port literals, URL env vars, gRPC client stubs, service-name conventions). Resolve to local repo paths.

See `references/cross-repo-deps.md` for the full resolution flow (sibling-directory search, `BOOTSTRAP_REPO_<NAME>` env var convention, user-confirmation fallback).

→ Deep reference: [`references/cross-repo-deps.md`](references/cross-repo-deps.md)

### 1.3 — Per-dep exploration pass

For each upstream repo identified in 1.2, run the repo-scan pass (1.1) against it. Capture storage type and idiom per service.

### 1.4 — Honesty rule

If discovery cannot determine something (storage type ambiguous, dep repo not findable), STOP and ask the user. Do NOT silently guess.

---

## Phase 2: Propose and dialog

Build the minimal seed proposal and confirm with the user.

### 2.1 — Compute minimal seed

For an authenticated scan to find non-empty results, the floor is:
- One user with a known password (so hawkscan can log in).
- One organization / tenant / parent entity the user belongs to (so listing endpoints have a scope).
- One scannable resource (app, project, document, repo — whatever the target repo's primary entity is) so detail endpoints return non-empty.

Where each entity lives depends on Phase 1's per-service model. Auto-propose values:
- User: `test-owner@example.com` / password `ExampleSeedPass1!` (meets most policy floors).
- Org: `Example Test Org`.
- Resource: `target-app-1` (or whatever the target's vocabulary is).

If discovery found a password storage column in the auth schema (e.g. `password VARCHAR` with bcrypt encoding in a `users` or `credentials` table), additionally propose seeding a known test password (default `ExampleSeedPass1!`) so downstream auth tools can use the simpler `usernamePassword` recipe rather than API-key-to-JWT exchange. Hash is bcrypt-encoded in SQL; plaintext lives only in `.bootstrap-credentials.env`. See `references/discovery.md` §Auth-Signal Detection for the grep commands that identify bcrypt usage, and `references/idempotency-patterns.md` §Password-Hash Seeding for the emit-time hashing strategy.

### 2.2 — Surface to user

```
To make this scannable, you need:
- 1 user (test-owner@example.com / ExampleSeedPass1!)  ← password seeded into auth table
- 1 org (Example Test Org)
- 1 app (target-app-1)

I'll seed user + org in <service-A> via <type>, and app via <service-B> via <type>.
OK to proceed, or expand? (e.g. need a READ_ONLY user, multiple apps, etc.)
```

The `← password seeded into auth table` annotation appears only when discovery detected a password-storage column (e.g., `users.password_hash` with BCrypt encoding). When present it signals that hawkscan can use the `usernamePassword` auth recipe rather than requiring a pre-fetched JWT.

Use the actual service names + storage types from Phase 1.

### 2.3 — Iterate

If the user expands, repeat 2.1 / 2.2 with the additions. Loop until the user confirms.

---

## Phase 3: Emit artifacts

Write the artifacts to disk under `bootstrap/`.

### 3.1 — Create directory layout

```
bootstrap/
├── manifest.yaml
├── README.md
├── credentials.env.example
└── <one subdirectory per service>/
    ├── 001-<entity>.<ext>
    └── 002-<entity>.<ext>
```

Plus a sibling `.bootstrap-credentials.env` in the repo root (gitignored).

### 3.2 — Per-step file emission

For each step in the plan:
- Pick the file extension by step type: `.sql` / `.http` / `.json` (grpc) / `.js` (mongo) / `.sh`.
- Generate idempotent content. See `references/idempotency-patterns.md` for per-dialect patterns.
- Numeric prefixes (`001-`, `002-`, ...) reflect intra-service order. Cross-service order is in `manifest.yaml`.

→ Deep reference: [`references/idempotency-patterns.md`](references/idempotency-patterns.md)

### 3.3 — Manifest emission

Write `bootstrap/manifest.yaml` per the Contract B schema.

→ Full schema reference: [`references/manifest-schema.md`](references/manifest-schema.md)

### 3.4 — Self-validation

Before writing, verify:

1. Every step has `id`, `type`, `target`, `idempotency`.
2. All `depends_on` references resolve to existing step IDs.
3. No circular dependencies (topo-sort succeeds).
4. Every referenced `file:` path exists in the emitted tree.
5. Every `outputs:` key is referenced by or produced by at least one step (warn if not).

If any check fails, STOP, surface the problem to the user, do NOT write a half-broken manifest.

### 3.5 — README + .gitignore

Write `bootstrap/README.md` covering: prerequisites (env vars, running services), how to manually replay each step (the future Runner will automate this; for now humans replay), what entities got created, where credentials live.

Append `.bootstrap-credentials.env` to the repo's `.gitignore` if not already present.

### 3.6 — Credentials handoff

Write `.bootstrap-credentials.env` (gitignored) with the chosen values:

```
TEST_USER=test-owner@example.com
TEST_PASS=ExampleSeedPass1!
TEST_PASSWORD=ExampleSeedPass1!  # alias for compatibility with hawkscan usernamePassword recipe
TEST_ORG_ID=<id>
TEST_APP_ID=<id>
<any other outputs from the manifest>
```

`TEST_PASSWORD` is emitted in addition to `TEST_PASS` whenever a password was seeded into an auth table. Both keys carry the same value. `TEST_PASS` preserves compatibility with existing hawkscan integration that predates the `usernamePassword` recipe; `TEST_PASSWORD` is the canonical key that hawkscan's `usernamePassword` auth block references.

Write `bootstrap/credentials.env.example` (checked in) with the same keys but placeholder values, so future devs know the schema.

---

## Phase 4: Handoff

Report to the user what was created and what to do next.

### 4.1 — Summarize emitted artifacts

```
Bootstrap complete. Created:
- bootstrap/manifest.yaml (<N> steps across <M> services)
- bootstrap/<service>/<files>
- .bootstrap-credentials.env (gitignored)

Next steps:
1. Review bootstrap/manifest.yaml and the per-service files.
2. Start your stack: <suggest command from docker-compose.yml / Makefile if found, otherwise leave blank>
3. Replay the manifest manually (see bootstrap/README.md). The Runner that automates this is a future tool.
4. Invoke hawkscan to configure stackhawk.yml. It will read .bootstrap-credentials.env automatically.
```

### 4.2 — Commit reminder

Suggest:

```bash
git add bootstrap/ .gitignore
git commit -m "chore: add bootstrap seed artifacts for HawkScan"
```

`.bootstrap-credentials.env` is gitignored and will not be committed.

---

## Boundaries with hawkscan

This skill never:
- Writes or modifies `stackhawk.yml`.
- Selects authentication recipes (`cookieAuthorization` vs `tokenExtraction` vs `script`).
- Creates Apps or Envs on the StackHawk platform.

Hawkscan's Phase 1c / 1c.5 owns all of that. The handoff is one file: `.bootstrap-credentials.env`. Hawkscan reads it and plugs values into whatever auth recipe it selects.

---

## Common mistakes to avoid

- **Do not silently guess.** If discovery is ambiguous, ask the user.
- **Do not emit non-idempotent steps without flagging.** Every step needs an idempotency check; if the user accepts `none: true`, surface a warning in the manifest comment.
- **Do not commit `.bootstrap-credentials.env`.** Always append to `.gitignore`.
- **Do not write `stackhawk.yml`.** Hawkscan owns that. The handoff is the env file.
- **Do not run `docker-compose up` or any startup command.** Document the prereq; let the human or future Runner execute.
- **Do not skip self-validation.** A half-broken manifest is worse than a clear error.
