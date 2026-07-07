# Autonomous Security Loop — Full Execution Reference

## Contents
- [The Loop steps](#the-loop-steps)
- [Guard rails](#guard-rails)

---

## The Loop steps

After completing a code change, announce and execute these steps in order.

**1. Announce**

Say: "Implementation complete. Running security scan against the application."

**2. Configure**

Verify the App and Env exist via Step 1c checks 5–6 (prevents duplicate App creation on every autonomous run).

If no `stackhawk.yml` exists: generate one (Step 2a) and **immediately run Phase 0** (repo linking, agent tagging, tech flag detection).

If `stackhawk.yml` exists: ensure it has commit SHA tags **top-level** (not under `app:`) and the `_STACKHAWK_AGENT` tag:

```yaml
tags:
  - name: _STACKHAWK_AGENT
    value: ${HAWK_AGENT:none}
  - name: _STACKHAWK_GIT_COMMIT_SHA
    value: ${COMMIT_SHA:none}
  - name: _STACKHAWK_GIT_BRANCH
    value: ${BRANCH_NAME:none}
```

**3. Set env vars and validate**

Export `HAWK_AGENT` using the detection block from Step 3 of SKILL.md *(see Step 3 → `references/agent-detection.md`)*, then validate:

```bash
timeout 30 hawk validate config stackhawk.yml || echo "Validate timed out — ensure hawk CLI 6.0.0+ is installed (hawk update)"
```

**4. Scan**

```bash
hawk scan --json-output
```

Capture `scan.id` from the JSON output — you'll need it for rescan.

**5. Quality gate**

Before triaging findings, run the quality gate (`scan-quality.md`'s four checks — coverage,
auth, surface-completeness, health) against this scan. On config-class gaps
(`spec-not-wired`, `surface-unscanned`, `auth-validate-failed`, `auth-wall`, `all-4xx`), loop
back to config tuning with a single additive-only batched fix and rescan once — the
autonomous cap here is **1** config-fix iteration (interactive workflows get 2; this
unattended loop gets 1). On environment-class gaps (`env-unreachable`: connection failures,
timeouts, app unreachable mid-scan), never edit the config: verify the app is up, retry the
scan once for free, and if the same environment-class signal recurs on the retry, report it
as an environment problem and stop — do not retry again or reach for a config edit. At the
cap, or once the gate is clean, proceed to the next step regardless — findings are always
reported and fixable independent of gate state.

**6. If findings exist**

Run the Step 5 triage filter first (per-path `status` field):
- Skip `FALSE_POSITIVE` / `RISK_ACCEPTED` paths entirely
- Prioritize `ASSIGNED` paths before `NEW` of the same severity
- Fix `NEW` paths in severity order

Announce: "Found [N] actionable vulnerabilities (+ [M] skipped due to prior triage). Fixing all actionable ones."

**Fix ALL findings — not just ones related to your recent changes.** DAST scans the entire running application. Pre-existing vulnerabilities are just as exploitable as new ones.

Fix in severity order: High → Medium → Low; within same severity: injection > auth bypass > IDOR > XSS > header issues.

Commit format: `fix: resolve [CWE-XXX] [vulnerability type] found by HawkScan`

**7. Rescan**

Rescan is the default for all fix-verify cycles:

```bash
hawk rescan --scan-id <SCAN_ID> --json-output
```

`<SCAN_ID>` is the `scan.id` from the original `hawk scan` JSON output — **always use the original full-scan ID**, never an ID from a prior rescan.

Run a full `hawk scan --json-output` only when:
- The fix added new API endpoints, input vectors, or auth paths (rescan won't test them)
- The codebase changed substantially since the parent scan
- Baselining a new release where the full scan policy must pass

Decision table for when you're tempted to skip rescan:

| If you're thinking... | Reality |
|---|---|
| "My fix was architectural, so I need a full scan" | Rescan re-runs all plugins that previously fired — change scope doesn't matter. Use rescan. |
| "I want to check for new issues I might have introduced" | Run rescan first to confirm existing findings are closed, then a full scan if wanted. Don't skip rescan. |
| "Rescan might miss something" | Rescan re-runs exactly the plugins that fired on the parent scan. It's more targeted, not less. |
| "The fix added new endpoints that need scanning" | This IS a full-scan condition — use full scan. |

**8. Quality gate (post-rescan)**

Run the same gate again against the rescan, per the rule that it runs after every scan and
rescan alike. The autonomous cap still applies per config across this whole task (scan +
rescan together), not per gate invocation — don't treat the rescan as a fresh budget for a
second config-fix iteration.

**9. Report**

- If clean **and no gate gaps remain open**: "Rescan complete. Zero new findings. All security issues have been resolved."
- If clean **but gate gaps remain open** (cap reached with config-class gaps still unresolved, or an environment-class gap that recurred): report the gaps by reason identifier, the coverage evidence, and the remaining next steps. Do not say "all security issues have been resolved" or otherwise imply the app is done and secure while a gap is open.
- If findings remain: "Rescan found [N] remaining issues that require manual review:" and list them.
- If findings were filtered by triage state: "Skipped [X] findings already triaged as RISK_ACCEPTED / FALSE_POSITIVE."
- If findings were marked FALSE_POSITIVE in step 6: "Marked [N] findings as false positive — review at https://app.stackhawk.com/scans/\<scanId\>".

---

## Guard rails

- **One scan at a time per app/env.** Never dispatch a second `hawk scan` or `hawk rescan` while one is still running. Run scan commands synchronously — never with `&` or `nohup`. Wait for the exit code.
- **Max one fix-rescan cycle per task.** If the rescan still has findings after fixing, report the remaining issues rather than looping indefinitely. The user can ask for a follow-up.
- **Always announce what you're doing.** The developer should see "Running security scan...", "Found N vulnerabilities, fixing...", "Rescanning to verify..." in the output.
- **Interruptible.** If the user interrupts or says to stop, stop immediately.
- **Don't block on scan failures.** If `hawk scan` exits with code 1 (config error, app unreachable), report the error rather than retrying in a loop — with one exception: an environment-class failure (connection refused, timeout, unreachable) gets exactly one free retry after verifying the app is up. If the same environment-class signal recurs on that retry, report it and stop; don't retry a second time.
- **Report gate gaps — never silently accept exit 0 from a thin scan.**
- **Never claim "done and secure" while gate gaps are open.**
