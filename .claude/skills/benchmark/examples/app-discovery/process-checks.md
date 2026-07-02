# App-Discovery Process Checks

This document describes the 7 observational signals measured in the app-discovery benchmark. These checks grade agent behavior objectively (without LLM judgment) and form the foundation for comparing skill versions.

## The 7 Signals

### 1. `read_agent_docs`

**Measures:** Whether the agent reads the repository's own documentation (README, developer guides, setup docs, etc.) during discovery.

**Why it matters:** A docs-first orientation is a key behavioral marker — agents should ground their understanding in the repo's own instructions before inferring from code structure.

**How it's checked:** Deterministic scan of tool calls (tool targets or read file paths) for common documentation file patterns (README, INSTALL, GETTING_STARTED, docs/, setup guides, etc.).

**Reference outcome (this session):** NEW v2.1.0: 1.00 (3/3 apps read docs) vs OLD v2.0.0: 0.33 (1/3 apps).

---

### 2. `docs_before_conclusion`

**Measures:** Whether the agent reads documentation *before* making conclusions, not after. Specifically, compares the timestamp of the first documentation file read against the first assertion/conclusion that appears in the assistant's text response.

**Important detail:** This signal looks at the **assistant's text response** (when the model first states a conclusion), NOT the tool targets. A conclusion in text means "the agent has decided on an answer" — which should follow from having read evidence first.

**Why it matters:** An agent can read docs by accident at the end of its exploration. This signal ensures docs inform the discovery process, not just provide post-hoc validation.

**How it's checked:** Parse the transcript for tool calls (recording read times) and the assistant message for the first assertion (e.g., "the run command is...", "the API style is..."). Docs must be read before that first conclusion appears in text.

**Reference outcome (this session):** NEW v2.1.0: 1.00 (3/3 apps read docs before concluding) vs OLD v2.0.0: 0.33 (1/3 apps).

---

### 3. `explored_manifests`

**Measures:** The count of distinct manifest/configuration files read (e.g., Dockerfile, docker-compose.yml, package.json, settings.py, go.mod, Makefile, Taskfile.yml, nuxt.config.ts, etc.).

**Why it matters:** Breadth of exploration correlates with confidence and grounds conclusions in multiple sources rather than guessing from a single file.

**How it's checked:** Count unique file paths matching manifest patterns during discovery (excludes README, docs, source code implementation details).

**Reference outcome (this session):** NEW v2.1.0: ~13.7 distinct files vs OLD v2.0.0: ~8.7 (averaged across 3 apps).

---

### 4. `exploration_breadth`

**Measures:** The total count of distinct files read during discovery (any category).

**Why it matters:** A proxy for thoroughness — agents that read more sources tend to have more grounded conclusions.

**How it's checked:** Count unique file paths in tool calls; excludes repeated reads of the same file.

**Reference outcome (this session):** Subset of the `explored_manifests` signal; NEW consistently explored more breadth.

---

### 5. `emitted_five_answers`

**Measures:** Whether the agent's final response includes all 5 required discovery answers (run_command, host, api_style, spa, auth).

**Why it matters:** Completeness of the response — the harness grades correctness only for answers that were emitted.

**How it's checked:** Parse the DISCOVERY: block in the agent's response; count the non-empty answer fields.

**Reference outcome (this session):** Both OLD and NEW emitted all 5 answers on all apps.

---

### 6. `stayed_read_only`

**Measures:** Whether the agent performed only read operations (no writes, runs, scans, or external egress) during discovery.

**Why it matters:** The discovery step must not modify the repository or spin up services (that's a later step). This signal verifies constraint compliance.

**How it's checked:** Scan tool calls for Bash commands, Docker/compose invocations, file writes, or network requests. Any such attempt (even if denied by a guard) is a violation.

**Reference outcome (this session):** Both OLD and NEW were protected by a PreToolUse guard that denied writes and container starts. The guard logged attempts, confirming agents *tried* to run `docker compose up` and were blocked — the guard works end-to-end. Both arms stayed read-only.

---

### 7. `ran_legacy_command_menu`

**Measures:** Whether the agent executed the old prescriptive `find`/`grep`/`node` detection menu from the previous skill version (patterns like "find . -name Dockerfile", "grep -r 'const PORT'", "node -p require('./package.json').version").

**Why it matters:** The reframed skill (v2.1.0) replaced the prescriptive menu with a docs-first "Understand the Application" flow. Agents should not regress to the old menu.

**How it's checked:** Pattern match for the exact command signatures from the legacy guidance.

**Reference outcome (this session):** NEW v2.1.0: 0.00 (never ran legacy menu) vs OLD v2.0.0: 0.33 (ran on 1/3 apps — miniflux).

---

## Ground Truth

The 3 apps are:
- **miniflux** (Go + PostgreSQL, server-rendered web app, REST API)
- **mealie** (Python FastAPI + Vue 3 + Nuxt 3 SPA, OpenAPI)
- **immich** (NestJS + SvelteKit SPA, OpenAPI, machine learning backend)

Ground truth for each app is defined in `ground-truth/{miniflux,mealie,immich}.json`. Each file contains:
- `app`: app name
- `run_command`: the exact start command and dependencies
- `host`: the listening host/port (local dev and prod)
- `api_style`: REST/GraphQL/gRPC and the base path
- `spa`: yes/no (single-page app)
- `auth`: authentication requirement and shape (cookie/bearer/API key/OIDC)
- `evidence`: file-level provenance for each answer

## Correctness Scoring

Correctness is scored by an LLM judge (not part of the process-checks). The judge compares the agent's emitted answers against ground truth on a 5-point scale (0–5 correct out of the 5 answers). At n=1 run/cell, judge-scored metrics are treated as directional evidence, not statistical significance.

## Reference Outcome Summary

| Metric | OLD v2.0.0 | NEW v2.1.0 | Interpretation |
|--------|-----------|-----------|-----------------|
| read_agent_docs | 0.33 | **1.00** | NEW reads repo docs on all apps |
| docs_before_conclusion | 0.33 | **1.00** | NEW reads docs before concluding |
| exploration_breadth | 8.7 files | **13.7 files** | NEW explores more sources |
| legacy_command_menu | 0.33 | **0.00** | NEW never regresses to old menu |
| stayed_read_only | pass | pass | Both arms respect read-only constraint |
| emitted_five_answers | 100% | 100% | Both complete on all apps |
| correctness (judge) | 4.67/5 | 4.33/5 | Tied (judge noise at n=1) |

**Verdict:** The skill reframe (v2.0.0 → v2.1.0) improved docs-first behavior (the intended change) with no loss of correctness and no pigeonholing. The deterministic process-checks provide the primary evidence; LLM judge scores are secondary.
