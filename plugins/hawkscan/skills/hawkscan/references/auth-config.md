# Authentication Configuration Reference

## Contents
- [Phase 1c: Configure auth with hawk config show](#phase-1c-configure-auth-with-hawk-config-show)
- [Phase 1c.6: Seed backend when auth fails on an empty datastore](#phase-1c6-seed-backend-when-auth-fails-on-an-empty-datastore)

---

## Phase 1c: Configure auth with hawk config show

Use `hawk config` to retrieve the canonical recipe for whichever auth pattern fits the app. The recipe content is the same source the hosted-scanner auth-analyzer reads — one source of truth.

**Step 1 — List available auth methods:**

```bash
hawk config show app.authentication --text
```

Returns the overview plus a list of authentication sub-types.

**Step 2 — Pick one by name based on observed app behavior:**

| Observed pattern                                          | Sections to fetch                                                                                       |
|-----------------------------------------------------------|---------------------------------------------------------------------------------------------------------|
| Form POST → Set-Cookie with session                       | `app.authentication.usernamePassword`<br>`app.authentication.cookieAuthorization`                       |
| OAuth client-credentials / password / authorization-code  | `app.authentication.oauth`<br>`app.authentication.tokenAuthorization`                                   |
| JSON POST returning a JWT                                 | `app.authentication.usernamePassword`<br>`app.authentication.tokenExtraction`<br>`app.authentication.tokenAuthorization` |
| Pre-issued token from env var                             | `app.authentication.external`<br>`app.authentication.tokenAuthorization`                                |
| Multi-step flow not expressible in config                 | `app.authentication.script`                                                                             |
| Bash + curl last resort                                   | `app.authentication.externalCommand`                                                                    |

**If no row matches** — bespoke challenge-response, multi-stage flow with client-side computed proof, custom undocumented scheme, or you can't tell which row fits: stop here. Return to SKILL.md **Phase 1c.5** (auth analyzer fallback). Do not force-fit a recipe pattern. Do not proceed to Step 3 with a guess. Do not ship without auth.

**Step 3 — Fetch each relevant section:**

```bash
hawk config show <section> --text
```

Use the returned markdown's YAML example as the template; substitute observed values.

**Step 4 — Always include a testPath:**

```bash
hawk config show app.authentication.testPath --text
```

The `testPath` must return 401/403 without auth and 200 with auth.

**Step 5 — Validate before scanning:**

Auth validation is mandatory whenever you author or modify the `authentication:` block — skipping it means you find out auth is broken inside a full scan instead of in seconds.

```bash
# Structural validation (always)
hawk validate config stackhawk.yml

# Live auth validation (required when authentication: block is new or modified)
hawk validate auth stackhawk.yml
```

If `validate config` fails: fix the structural error and re-run. If `validate auth` fails: re-fetch the relevant recipe(s) via `hawk config show <section> --text` and adjust the `authentication:` block.

---

## Phase 1c.6: Seed backend when auth fails on an empty datastore

Distinct from Phase 1c.5 (which fixes a *wrong or ambiguous recipe*): use 1c.6 when the auth **recipe is correct** but authentication fails because the **credential/entity doesn't exist in the backend** — e.g. a 401/403 on a known-correct login against a freshly-started local stack whose database was just created (empty `users` / `api_key` / org tables). The fix is to seed the backend, not to change the recipe or run the analyzer.

**Signal — all three must be true:**
1. The `authentication:` block matches a real recipe and is structurally valid
2. `hawk validate auth` (or the login call) returns 401/403 or an empty token
3. The backing datastore is empty/fresh (just-started local services, migrations only just ran, no seeded dev user or key)

If the recipe itself is wrong or ambiguous instead, use **Phase 1c.5** (return to SKILL.md).

**Action:**

- **Gate first** — seeding needs hawk ≥ 6.0.0. Probe:
  ```bash
  hawk perch seed validate --help >/dev/null 2>&1 && hawk perch seed finalize --help >/dev/null 2>&1
  ```
- If the probe **succeeds** and `stackhawk-data-seed` is installed → invoke it. It runs `hawk perch seed` (preflight → synthesizes manifest → validate → finalize), and on success produces a `.data-seed-credentials.env` handoff this skill then consumes.
- If the probe **fails** (hawk too old) → tell the user the authenticated scan can't get past the empty backend without seed data, and to either **upgrade** (`brew upgrade stackhawk/cli/hawk`, hawk ≥ `6.0.0`) to enable seeding or manually create the dev user/credential, then re-run. If they proceed without seeding, the scan still runs but authenticated endpoints return empty/unauthorized — flag that results will be limited.
- If `stackhawk-data-seed` is **not available** but hawk supports the flow → tell the user to install it (`/plugin install stackhawk-data-seed@stackhawk`) and re-run the seeding step; not a hard blocker for the scan.
- **Cross-repo:** for a gateway / multi-service app the credential or entity usually lives in an **upstream** service's datastore (e.g. the auth service), not the target repo. Run the seed against that upstream repo; seeding the gateway repo alone finds no local storage and produces a no-op.

After seeding, re-run `hawk validate auth stackhawk.yml` and continue.
