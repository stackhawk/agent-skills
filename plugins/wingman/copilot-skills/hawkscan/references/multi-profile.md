# Multi-Profile Authorization Scanning (BOLA/BFLA)

Scan as several users at once so HawkScan can test whether one user can read another user's
objects (BOLA — broken object-level authorization) or call functions their role should not
reach (BFLA — broken function-level authorization). Configure 2+ users in
`app.authentication.profiles` and run with `--profile-scan-mode=primary-full`: one profile
gets the full scan policy, the rest run the cross-profile BOLA/BFLA checks. Entered from
Phase 1c in SKILL.md, after the single-user auth recipe is chosen.

## Contents
- [When to go multi-profile](#when-to-go-multi-profile)
- [Get the accounts: find → make → ask](#get-the-accounts-find--make--ask)
- [Profile set](#profile-set)
- [stackhawk.yml templates](#stackhawkyml-templates)
- [Run command and full-scan profile](#run-command-and-full-scan-profile)
- [Quality gate and failures](#quality-gate-and-failures)
- [Fixing BOLA/BFLA findings](#fixing-bolabfla-findings)

---

## When to go multi-profile

Go multi-profile **autonomously, without asking**, when all three hold:

1. **Authorization signals in code.** Discovery found at least one of:

   | Signal | Looks like (e.g.) |
   |--------|-------------------|
   | Object-ID routes | `/<resource>/{id}`, `/<resource>/:id`, `@GetMapping("/{id}")` |
   | Ownership checks | a query filtered by the current user (`where owner_id = <current-user>`) |
   | Role / function guards | `@PreAuthorize`, `@RolesAllowed`, a `requireRole(...)` middleware, an `isAdmin` check, an admin-only router |
   | Tenant scoping | `org_id` / `tenant_id` columns or tenant middleware |

   These are illustrative starting points — search the repo's real source root for its own
   equivalents.
2. **Capability.** `hawk scan --help | grep -q -- --profile-scan-mode` succeeds. If it
   fails, scan as one user and say in the summary that BOLA/BFLA needs a newer hawk
   (`brew upgrade stackhawk/cli/hawk`).
3. **2+ usable accounts** after the ladder below.

No signals → scan as one user. Extra test accounts on their own are not a reason to write
`profiles`.

## Get the accounts: find → make → ask

Work down the ladder; stop as soon as the profile set below is satisfied.

1. **Find.** `.data-seed-credentials.env`, `.env*` and `.env.example`, README and docs,
   seed SQL and fixtures, test fixtures. Note each account's role and which data it owns.
2. **Make** — only when the target host is local or a dev environment; never a shared or
   production host.
   - **Standard users:** call the app's own signup/registration endpoint, e.g.
     `curl -s -X POST "$HOST<signup-path>" -H 'Content-Type: application/json' -d '<signup-body>'`.
     Have each new user create at least one object of their own so BOLA has something
     to cross-read.
   - **Privileged users, or no signup endpoint:** seed them via Phase 1c.6 in SKILL.md
     (`stackhawk-data-seed`).
3. **Ask.** Still under 2 usable accounts → ask the user. Say which roles are needed and
   why, and which env vars the skill will read, e.g.:

   > To test authorization (BOLA/BFLA) I need an admin plus two standard users who own
   > different data. Please set `HAWK_PROFILE_ADMIN_USERNAME` / `HAWK_PROFILE_ADMIN_PASSWORD`,
   > `HAWK_PROFILE_USER_A_USERNAME` / `HAWK_PROFILE_USER_A_PASSWORD`, and
   > `HAWK_PROFILE_USER_B_USERNAME` / `HAWK_PROFILE_USER_B_PASSWORD` (or `_TOKEN` for
   > token auth), or tell me how to create them.

   - One extra account supplied → use the 2-profile minimum.
   - User declines → scan as one user; the summary records
     "BOLA/BFLA skipped: no second account."

Env var names are `HAWK_PROFILE_<NAME>_USERNAME`, `_PASSWORD`, `_TOKEN`, and `_ID` for a
per-user identifier, with `<NAME>` the profile name upper-cased and `-` turned into `_`.
Credential values never go into `stackhawk.yml`.

## Profile set

How the checks work: the BOLA check replays **GET** requests made by one profile using
another profile's session; the BFLA check replays **POST/PUT/DELETE**. **Both skip
profiles marked `isPrivileged: true`**, so authorization probes always come from the
standard users.

- **Ideal — 3 profiles:** `admin` (`isPrivileged: true`), `user-a`, `user-b`. `user-a` and
  `user-b` share a role but own different data (BOLA); admin-only functions are probed
  from the standard users (BFLA).
- **Minimum — 2 profiles:** privileged + standard (BFLA-focused), or two standard users
  (BOLA-focused).
- Each profile uses the **same auth pattern** chosen in Phase 1c. Login mechanics,
  authorization, indicators, and `testPath` stay at the `app.authentication` level; a profile
  carries only its own credentials.
- `globalParameters` holds per-user values crawling can't discover, such as the user's own
  ID. It is a **map** (`userId: ${VAR}`), not a list — a list fails validation even though
  `hawk config show` prints its type as `GlobalParametersEntry[]`.
- Profile names must be unique; the scan aborts on duplicates.

## stackhawk.yml templates

Lines marked `# from Phase 1c` come from the recipe already chosen; replace every
`<placeholder>`. Merge into the existing `app:` block — `applicationId`, `env`, and `host`
are unchanged.

**Username/password login** — the top-level `scanUsername`/`scanPassword` are still
required; each profile overwrites them at scan time, so point them at the first profile:

```yaml
app:
  authentication:
    usernamePassword:                       # from Phase 1c
      type: JSON
      loginPath: <login-path>
      usernameField: <username-field>
      passwordField: <password-field>
      scanUsername: ${HAWK_PROFILE_ADMIN_USERNAME}
      scanPassword: ${HAWK_PROFILE_ADMIN_PASSWORD}
    tokenExtraction:                        # from Phase 1c
      type: TOKEN_PATH
      value: "<token-json-path>"
    tokenAuthorization:                     # from Phase 1c
      type: HEADER
      value: Authorization
      tokenType: Bearer
    loggedInIndicator: "<logged-in-regex>"  # from Phase 1c
    loggedOutIndicator: "<logged-out-regex>"
    testPath:                               # from Phase 1c
      path: <test-path>
      success: ".*200.*"
    profiles:
      - name: admin
        isPrivileged: true
        userNamePassword:
          username: ${HAWK_PROFILE_ADMIN_USERNAME}
          password: ${HAWK_PROFILE_ADMIN_PASSWORD}
      - name: user-a
        userNamePassword:
          username: ${HAWK_PROFILE_USER_A_USERNAME}
          password: ${HAWK_PROFILE_USER_A_PASSWORD}
        globalParameters:
          userId: ${HAWK_PROFILE_USER_A_ID}
      - name: user-b
        userNamePassword:
          username: ${HAWK_PROFILE_USER_B_USERNAME}
          password: ${HAWK_PROFILE_USER_B_PASSWORD}
        globalParameters:
          userId: ${HAWK_PROFILE_USER_B_ID}
```

**Pre-issued tokens** — a top-level `external` block is required; each profile's
`authTokens` replaces its `values`. Note the token field is `val`, not `value`, and
`external` uses inert indicators:

```yaml
app:
  authentication:
    external:
      values:
        - type: TOKEN
          tokenType: Bearer
          value:
            name: Authorization
            val: ${HAWK_PROFILE_ADMIN_TOKEN}
    loggedInIndicator: ".*"
    loggedOutIndicator: "$^"
    testPath:                               # from Phase 1c
      path: <test-path>
      success: ".*200.*"
    profiles:
      - name: admin
        isPrivileged: true
        external:
          authTokens:
            - type: TOKEN
              tokenType: Bearer
              value:
                name: Authorization
                val: ${HAWK_PROFILE_ADMIN_TOKEN}
      - name: user-a
        external:
          authTokens:
            - type: TOKEN
              tokenType: Bearer
              value:
                name: Authorization
                val: ${HAWK_PROFILE_USER_A_TOKEN}
      - name: user-b
        external:
          authTokens:
            - type: TOKEN
              tokenType: Bearer
              value:
                name: Authorization
                val: ${HAWK_PROFILE_USER_B_TOKEN}
```

`authScript` profiles follow the same shape: `hawk config show app.authentication.profiles.authScript --text`.

Then run `hawk validate config stackhawk.yml` and `hawk validate auth stackhawk.yml` as
usual. `validate auth` exercises the top-level user; per-profile authentication is proven by
the scan's pre-flight (see Quality gate below).

## Run command and full-scan profile

Once `profiles` exists, **every** scan and rescan carries both flags:

```bash
hawk scan --profile-scan-mode=primary-full --full-scan-profile=<privileged-profile-name> --json-output
hawk rescan --scan-id <SCAN_ID> --profile-scan-mode=primary-full --full-scan-profile=<privileged-profile-name> --json-output
```

- The full policy goes to the **privileged** profile by default — it reaches the most
  surface. With two standard users, pass the first declared profile.
- Never omit `--profile-scan-mode`: its default, `business-logic`, runs only the 2
  BOLA/BFLA plugins (~30 s, 0 general findings).
- **Destructive-admin pause.** If discovery found privileged endpoints that delete or reset
  users, change passwords or roles, or bulk-delete data, ask before the first scan: "Run the
  full policy as `<privileged-profile-name>` (more coverage, may mutate admin data or lock out
  that account) or as `<standard-profile-name>`?" Record the answer as a YAML comment directly
  above `profiles:` so later runs reuse it without asking:

  ```text
  # hawkscan: full-scan-profile=<profile-name> (confirmed by user <YYYY-MM-DD>: destructive admin endpoints)
  ```

  On later runs, read that comment and pass its profile name to `--full-scan-profile`.

## Quality gate and failures

| Symptom | Cause | Action |
|---------|-------|--------|
| Exit 1, `Pre-flight authentication check failed for N profile(s)` listing profiles | Those profiles could not log in; the whole scan aborts before it starts | Fix that profile's env vars or re-seed it (Phase 1c.6 in SKILL.md). If unfixable, remove that profile. Under 2 left → remove `profiles`, scan as one user, tell the user |
| Exit 1, `More than one profile needs to be configured` | Only one profile declared | Add a second account (ladder above) or remove `profiles` |
| Error listing valid profile names | `--full-scan-profile` names a profile that doesn't exist | Use one of the listed names |
| 0 findings in under ~60 s | `--profile-scan-mode` missing — the business-logic trap | Re-run with the mode; never report this as clean |

Then apply the normal Step 4.5 quality gate from SKILL.md to the full-policy profile's coverage.

## Fixing BOLA/BFLA findings

Fix in code like any other finding, then rescan with the same profile flags to verify.

- **BOLA** (a standard user read another user's object): scope the lookup to the
  authenticated principal — owner or tenant — inside the handler or service, and return
  404 or 403 when it doesn't match. Don't rely on unguessable IDs.
- **BFLA** (a standard user called a privileged function): enforce the required role
  server-side on the mutating handler, deny by default, and return 403. Hiding the UI
  control is not a fix.
- Several findings on routes that share one handler or middleware usually share one fix —
  group them.
