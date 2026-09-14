# Scan Policy Reference

How the scan policy is chosen, attached, and tuned across the first scan and any follow-up
full scans. Read this before Phase 0c and before starting a second full scan. Field syntax is
canonical in `hawk config show app.scanPolicy --text`; the optimize skill owns policy creation.

Evidence: seven headless first-run sessions on hawk 6.4.0 / wingman 2.5.0 (2026-09). Items
marked *observed* come from those sessions and are not yet enumerated by `hawk config show`.

## Contents
- [First scan: one broad policy, run to completion](#first-scan-one-broad-policy-run-to-completion)
- [Follow-up full scans: prune, do not crank](#follow-up-full-scans-prune-do-not-crank)
- [Attaching a named org policy](#attaching-a-named-org-policy)
- [Hand-built policy traps](#hand-built-policy-traps)
- [Why Phase 0c runs on every fresh config](#why-phase-0c-runs-on-every-fresh-config)

---

## First scan: one broad policy, run to completion

- **One broad policy for the detected stack.** The first scan uses the preset that matches the
  app shape (`DEFAULT`, `DEFAULT_API`, or the GraphQL preset — confirm names with
  `hawk op policy list`) plus the detected tech flags, built by optimize Setup (Phase 0c). Not
  every plugin at HIGH strength; not a hand-picked subset.
- **Run it to completion.** Do not stop it early and do not chain several long scans. The
  first completed broad scan reaches most of the findings any config can reach; further hours
  add a finding or two. *Observed:* 52 findings in ~5 min on a REST app and 43 in 5.6 min on a
  GraphQL app; a 20-minute follow-up at lowest threshold / HIGH strength added nothing.
- **Broadest scan last.** When several full scans run in one env, the **last completed scan is
  the result** — on the platform and for anyone grading the output. Ending on a narrow scan
  (`includePaths` on a few routes, a reduced plugin set) replaces the broad result. *Observed:*
  ending on a 13-path scan dropped one session from 71% to 42% of reachable findings. Narrow
  diagnostic scans are fine mid-session; finish with the broad one.

## Follow-up full scans: prune, do not crank

Terminology: `hawk rescan --scan-id` is fix verification (SKILL.md Step 3) and is not what this
section covers. This is about a *second full `hawk scan`* after the first broad one.

Run a follow-up full scan only for a reason the quality gate named (SKILL.md Step 4.5 — spec
not wired, auth wall, base-path mismatch) or to **prune**: drop tech flags for stacks the app
does not use, exclude paths that are pure noise. Do **not** raise strength or lower threshold
across all plugins — it multiplies scan time and, on this evidence, adds no findings. To change
the policy, re-run optimize Setup or edit the named policy through `hawk op policy`; do not
hand-edit policy JSON from memory (see traps below).

## Attaching a named org policy

A named org policy reaches a `stackhawk.yml` scan only through `app.scanPolicy.name`:

```yaml
app:
  scanPolicy:
    name: <POLICY_NAME>        # e.g. OPTIMIZE_TRIAL_MYAPP_DEVELOPMENT — must match ^[A-Z0-9_]+$
    # excludePluginIds: []     # optional local toggles layered on top of the named policy
    # includePluginIds: []
```

Creating a policy on the platform, or assigning it as the app default, does not by itself
change what a config that names a *different* policy scans with. Confirm the field shape with
`hawk config show app.scanPolicy --text` and that the policy exists with
`hawk op policy list --format json`. If the scan log shows a different policy than the one you
named, the name did not match — names are exact and upper-case.

## Hand-built policy traps

Prefer optimize Setup (`hawk op policy get --name <PRESET>` → edit → `hawk op policy create
--file`). If you must hand-edit policy JSON, start from a `policy get` dump and change as
little as possible. Two traps, both *observed*:

| Trap | Symptom | Rule |
|------|---------|------|
| **Protobuf zero values are dropped.** `STRENGTH_LOW` and `THRESHOLD_LOW` are the zero values of their enums, so a policy that sets them is serialized without those fields and the plugin entry lands with no strength/threshold. | A ~30-second scan, 0 findings, from a policy that "looked right". | Never write `STRENGTH_LOW` / `THRESHOLD_LOW` explicitly. Keep each plugin's strength/threshold exactly as the preset dump has them; never delete or blank them. The same mechanism applies to `enabled`: only `true` is stored, an omitted `enabled` means disabled. |
| **Stripping `pluginType` drops the passive rules.** Each plugin entry carries a `pluginType` (active vs passive). A hand-built JSON that omits it loses every passive rule — headers, cookies, information disclosure. | The scan completes, but there are zero passive findings (no missing-header, CSP, or cookie-flag alerts). | Keep every field from the `policy get` dump on every entry. Only toggle `enabled`, add or remove whole entries, or change strength/threshold. |

Before `hawk op policy create`, diff the JSON you are about to submit against the preset dump
(`hawk op policy get --name <PRESET> --format json`): same plugin count, `pluginType` present on
every entry, no `STRENGTH_LOW`/`THRESHOLD_LOW`. Check *before* creating — on current hawk,
`policy get` reads presets reliably but may not read back an org policy.

## Why Phase 0c runs on every fresh config

SKILL.md Phase 0c runs optimize Setup whenever a `stackhawk.yml` is **created** — not only the
first time an *application* is onboarded. A reused app with a fresh config (new clone, new env,
new operator) otherwise gets no policy step at all; *observed:* in seven sessions optimize was
never invoked, every operator hand-built a policy, and every one hit a trap above. Setup is
non-destructive (a trial policy referenced by `app.scanPolicy.name`; the app's own flags are
untouched), so re-running it on a reused app is safe.
