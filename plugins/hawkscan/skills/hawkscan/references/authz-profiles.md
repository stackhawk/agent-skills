# Multi-Role Authorization Profiles (BOLA/BFLA)

How to detect an app whose users hold different privileges, configure one HawkScan auth
profile per role, and run a scan that actually exercises the BOLA and BFLA plugins.

## Contents
- [Why this is not automatic](#why-this-is-not-automatic)
- [Detection: the multi-role verdict](#detection-the-multi-role-verdict)
- [Phase 1c.7: build the profiles](#phase-1c7-build-the-profiles)
- [Always pass the mode; never drop it](#always-pass-the-mode-never-drop-it)
- [Running the scan](#running-the-scan)
- [Reading per-profile findings](#reading-per-profile-findings)

---

## Why this is not automatic

With two or more auth profiles configured, `--profile-scan-mode` decides how plugin coverage is
spread across them:

| Mode | Primary profile | Every other profile | Cost |
|---|---|---|---|
| `business-logic` *(the flag's own default)* | BOLA/BFLA only | BOLA/BFLA only | cheapest — 2 plugins total |
| **`primary-full`** — **what this skill passes** | full configured policy | BOLA/BFLA | one full scan, not N |
| `all-full` | full configured policy | full configured policy | scan time ≈ N× |

**Always pass the mode explicitly.** Omitting `--profile-scan-mode` selects `business-logic`,
so the moment a second profile exists an otherwise-normal scan silently drops to two plugins —
no XSS, no SQLi, nothing else — for as long as those profiles stay in `stackhawk.yml`.

`BUSINESS_LOGIC` is a hidden preset containing only:

| pluginId | name |
|----------|------|
| 422004 | Cross Platform BOLA |
| 422005 | Cross Platform BFLA |

It does not appear in `hawk op policy list`, so it cannot be fetched and copied.

**Under `primary-full` the engine supplies BOLA/BFLA itself.** Non-primary profiles are scanned
with `BUSINESS_LOGIC`, fetched once per scan — *not* with your policy. So authorization coverage
on those profiles does **not** depend on your policy containing 422004/422005. That is what
makes this the right default: full-depth coverage on one profile, authz coverage on all of
them, and no way to silently lose the latter.

Two places where that guarantee does not hold, and the policy's own contents still decide:

- **`all-full`** scans every profile with your policy, so BOLA/BFLA run only if it lists them
  (enabled). The engine never injects them and emits no warning when they are absent.
- **No platform connectivity** (keyless or offline): `BUSINESS_LOGIC` cannot be fetched, so
  non-primary profiles fall back to the bundled full policy. No bundled policy contains
  422004/422005, so such a run gets **no BOLA/BFLA at all**. Say so rather than implying
  coverage that isn't there.

Both are why the optimize skill still authors 422004/422005 with `"enabled": true`.

## Detection: the multi-role verdict

Compute during Step 1a discovery, from three signal groups. The commands below are
illustrative starting points — run them against the repo's real source root, not a literal
`src/`.

| Signal group | What to look for | Example probe |
|---|---|---|
| Role/privilege model | role or permission enums; RBAC annotations, decorators, guards; policy engines (Casbin, OPA, Pundit, CanCan); a roles or permissions table in migrations | `grep -rniE "enum .*(role\|permission)\|@PreAuthorize\|@RequiresRole\|hasPermission\|requireAdmin\|can\?\(" <source-root>` |
| Object ownership | queries filtered by an owner column, and handlers that take an ID from the path or body and do **not** filter by owner | `grep -rniE "where .*(user_id\|owner_id\|tenant_id\|account_id) *=" <source-root>` |
| Privileged surface | admin or internal route prefixes; routes addressing another user by ID; routes gated by a role check | `grep -rniE "\"/(admin\|internal)\|/users/\{?id" <source-root>` |

**The verdict is `multi-role` when a role/privilege model AND an ID-addressable resource
surface both appear.**

Missing ownership checks raise confidence but are never required. A missing ownership check is
the bug being hunted — requiring one as evidence would suppress the very finding this exists to
surface.

Record the verdict alongside the rest of discovery. Both Phase 1c.7 and the optimize skill
consume it.

## Phase 1c.7: build the profiles

**Step 0 — probe capability before touching anything.** Do this first, before any credential
work and before anything is written to `stackhawk.yml`. It is a zero-cost check with no state,
so nothing forces it to run late:

```bash
hawk scan --help 2>/dev/null | grep -q -- --profile-scan-mode
```

Non-zero means the installed `hawk` predates the flag — it does not exist to pass, ever, on
this binary. On any released `hawk` this probe fails; treat that as the common case, not the
edge case.

**If the probe fails, stop and ask the user now, before anything is modified.** At this point
"keep full breadth" is a clean no-op — nothing has been written yet:

> This `hawk` build predates `--profile-scan-mode`. Writing the 2+ auth profiles needed
> for BOLA/BFLA testing will make *every* future scan of this app run only 2 plugins
> (BOLA/BFLA) — the rest of the policy (XSS, SQLi, injection, headers, everything else) stops
> running until you upgrade `hawk` or remove the profiles. Options:
> 1. Keep the current full-breadth single-profile scan — skip writing the profiles, no
>    authorization testing this run.
> 2. Accept the 2-plugin BOLA/BFLA-only scan — write the profiles now.
> Which do you want?

Do not default either way — this is the one decision point in this feature where the agent
pauses for input, unlike the N× time warning below, which is status-only. Record the choice; if
the user picks (1), stop here — do not proceed to the cascade, and do not write `profiles:`.

If the probe passes, or the user picked (2), continue below.

Run the rest of Phase 1c.7 only after single-profile auth already validates green
(`hawk validate auth` passes). A broken single profile cannot be fixed by adding a second one.

Meaningful coverage needs specific shapes, not just extra logins:
- **BOLA** needs two users at the **same** privilege level, each owning at least one resource,
  so one can attempt to read the other's object by ID.
- **BFLA** needs a **low**-privilege user plus a privileged surface to attempt.

Work the cascade in order and stop at the first success:

**1. `fixtures` — harvest what the repo already has.** Cheapest, writes nothing. Look for
credentials with distinguishable roles in test fixtures and factories, seed SQL,
`docker-compose.yml` environment blocks, `.env.example`, and the README's local-setup section.
Accept only credentials the repo clearly intends for local development.

**2. `data-seed` — seed them.** Gate first, exactly as Phase 1c.6 does:

```bash
hawk perch seed validate --help >/dev/null 2>&1 && hawk perch seed finalize --help >/dev/null 2>&1
```

If the gate passes and `stackhawk-data-seed` is installed, invoke it and ask for its
**multi-user** shape: two peer users each owning a resource, plus one admin. It writes
`.data-seed-credentials.env` with one variable pair per seeded user, each pair carrying a
role-identifying suffix — the exact names are whatever `hawk perch seed finalize` emits, not a
name this skill assumes in advance. **Discover, don't assume:** read the file, group variables
into pairs by their suffix, and match each pair to peer-a / peer-b / admin by the suffix text
(e.g. a suffix containing `admin` or `privileged` is the admin pair). If which pair is
privileged is ambiguous from the suffixes alone, ask the user to confirm before setting
`isPrivileged: true` on the wrong profile.

**3. `ask` — ask the user.** State plainly what is missing and why it matters:

> Authorization testing needs a second account at the same privilege level as the first (to
> test BOLA) and ideally an admin account (to test BFLA). I found only one usable credential.
> Supply the others as environment variables and I will wire them up, or say skip and I will
> run a single-profile scan.

**4. `degrade` — proceed without it.** Run the normal single-profile scan. Report explicitly
that authorization testing was skipped, name which cascade step failed, and say what would
unblock it. Never silently drop the capability.

On success, write the profiles. Fetch the canonical field list first — never write this block
from memory:

```bash
hawk config show app.authentication.profiles --text
```

Each profile takes a unique `name`, one credential mechanism (`userNamePassword`, `external`,
or `authScript`), an `isPrivileged` boolean, and optional `globalParameters`. Set
`isPrivileged: true` on the admin profile only.

```yaml
# Shape only — every value here is a placeholder. Field list comes from hawk config show.
app:
  authentication:
    profiles:
      - name: <peer-a-profile-name>
        isPrivileged: false
        userNamePassword:
          username: ${<PEER_A_USER_VAR>}
          password: ${<PEER_A_PASS_VAR>}
      - name: <peer-b-profile-name>
        isPrivileged: false
        userNamePassword:
          username: ${<PEER_B_USER_VAR>}
          password: ${<PEER_B_PASS_VAR>}
      - name: <admin-profile-name>
        isPrivileged: true
        userNamePassword:
          username: ${<ADMIN_USER_VAR>}
          password: ${<ADMIN_PASS_VAR>}
```

Then re-validate, because the `authentication:` block changed:

```bash
hawk validate config stackhawk.yml
hawk validate auth stackhawk.yml
```

`hawk validate auth` hard-fails below 2 profiles, so a single-entry `profiles:` list is always
a mistake — either write 2+ or write none.

**Finally, re-invoke optimize Setup, passing the verdict.** With profiles written and validated,
re-invoke the optimize skill's Setup mode, passing it the `multi-role` verdict from discovery.
Setup authors (or updates) the scan policy so it includes plugins 422004 and 422005 literally —
this is what gives the provenance gate below something real to trust. If optimize is
unavailable, or degrades to recommend-only because the org lacks `ORG_POLICY_MANAGEMENT` /
`WRITE_POLICY` permission (see Step 3 of the optimize skill's preflight), no policy with
422004/422005 gets authored — drop the flag, which the provenance gate below already covers.

Do this step on the accepted-2-plugin path too, where the probe failed and there is no flag to
pass or drop. `BUSINESS_LOGIC` resolves regardless of what the policy contains, so it changes
nothing today — it prepares the policy for the moment `hawk` is upgraded and the flag becomes
available.

## Always pass the mode; never drop it

**Once 2+ profiles are written, they stay in `stackhawk.yml`.** Every scan that reads this file
from now on — not just this one — spreads coverage according to `--profile-scan-mode`, and
omitting it selects `business-logic`: exactly 2 plugins, permanently, for this app.

So on any build where the capability probe passed, **always pass
`--profile-scan-mode=primary-full`**. There is no condition under which dropping it improves
the outcome, because dropping it does not fall back to a normal scan — it falls back to the
2-plugin mode. Passing it is never worse than omitting it:

| Situation | With `primary-full` | Omitting the mode |
|---|---|---|
| Good policy | full policy on primary + BOLA/BFLA on the rest | 2 plugins |
| Weak or unrelated policy | that policy on primary + BOLA/BFLA on the rest | 2 plugins |
| `app.includedPlugins` set | that plugin set on primary + BOLA/BFLA on the rest | 2 plugins |

This is why there is no provenance gate here any more. Under `all-full` the policy's contents
decided whether BOLA/BFLA ran at all, so a policy of unknown origin was genuinely dangerous.
Under `primary-full` the engine scans non-primary profiles with `BUSINESS_LOGIC` regardless of
your policy, so authorization coverage cannot be lost by passing the mode with an imperfect
policy — only by *not* passing it.

**Still re-invoke optimize with the verdict** (the step in
[Phase 1c.7](#phase-1c7-build-the-profiles) above). It is no longer load-bearing for authz
coverage, but it decides how good the *primary* profile's full scan is, and it is what keeps
422004/422005 enabled for the two cases where the engine's guarantee does not apply —
`all-full`, and offline runs with no platform to fetch `BUSINESS_LOGIC` from.

When optimize is unavailable or degraded to recommend-only (no `ORG_POLICY_MANAGEMENT` /
`WRITE_POLICY` — see Step 3 of its preflight), proceed anyway: pass the mode, scan with
whatever policy the app already has, and tell the user the primary profile's depth is
whatever that policy provides. Do not withhold the mode as a consequence.

**The capability-gate fallback is the one that costs something, and it is not "mild."** If the
probe failed (Step 0 above), the user chose between keeping full breadth with zero
authorization testing and nothing written, or accepting `BUSINESS_LOGIC` — 2 plugins, with
every other plugin stopping for this app while the profiles remain. Say that plainly.

## Running the scan

Pass the mode and pin the profile that gets the full scan:

```bash
hawk scan --profile-scan-mode=primary-full --full-scan-profile=<privileged-profile-name> \
  --json-output stackhawk.yml   # e.g. --full-scan-profile=admin
```

**Always name `--full-scan-profile` explicitly.** It defaults to the *first profile declared in
the config*, which in the layout this skill writes is a low-privilege peer — so relying on the
default silently makes coverage depend on the order the profiles happen to appear in. Pin it to
the `isPrivileged: true` profile: that account reaches the widest surface, so the single
full-depth pass covers the most routes, while BOLA/BFLA still run as the unprivileged peers,
which is where authorization gaps actually show up.

Announce before starting (status output, **not** a prompt — do not pause for input):

```
StackHawk | Multi-role app detected - <N> auth profiles; full policy as <primary>, BOLA/BFLA on the rest
StackHawk | Cost is roughly one full scan plus <N-1> cheap 2-plugin passes, not <N>x
StackHawk | hawk.scan.maxDurationMinutes budgets the WHOLE scan across all profiles
```

`primary-full` exists precisely so scan time does not scale with profile count: only the
primary profile runs the full policy. Use `all-full` only when the user explicitly asks to
scan every profile in full, and warn there that time really does grow to roughly N×.

**Rescans need the same two flags.** `hawk rescan` accepts `--profile-scan-mode` and
`--full-scan-profile`, and the mode defaults to `business-logic` there too — so a rescan issued
without them against a multi-profile config re-runs only 2 plugins and cannot confirm the fix
it was run to check:

```bash
hawk rescan --scan-id <SCAN_ID> --profile-scan-mode=primary-full \
  --full-scan-profile=<privileged-profile-name> --json-output
```

Carry both flags on every verification rescan for as long as the profiles remain in the config.

If `hawk.scan.maxDurationMinutes` is already set, say so and give the arithmetic — the budget
covers every profile's pass, so one sized for a single-profile scan can still truncate the run
mid-way even in `primary-full`.

## Reading per-profile findings

Findings collapse by plugin — one alert per plugin per scan, with URIs merged. Profile identity
survives in exactly one place: the alert's **Other Info** field (`other`), where the profile is
recorded ahead of any existing content, and only when 2+ profiles were configured. There is no
queryable profile field.

Read it from Other Info, not from `evidence`. Evidence must match the captured
request/response byte for byte — the platform UI highlights a finding by locating that string
verbatim — so nothing is prefixed onto it. Single-profile scans are unchanged in both fields.

Carry the profile into the fix task. "Reachable as the low-privilege profile, not just as
admin" is the entire value of a BOLA/BFLA finding, and Other Info is the only place it exists.
A fix task that omits which role reached the endpoint has discarded the finding's point.
