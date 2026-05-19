# Auth Analyzer Fallback

When Phase 1c's static auth detection can't produce a working `authentication:` block, this reference describes the fallback flow that drives the live auth analyzer through `hawk perch` + the upstream `recipe.auth-analyzer-workflow` recipe.

## When to invoke this fallback

Phase 1c.5 fires when **any** of these are true:

1. **Ambiguous classification.** Phase 1c sub-step 0 found auth signals in the codebase (a single `AddAuthentication(` call, conflicting framework imports, two independent but unrelated signals) but the agent can't confidently map the pattern to one of the recipe-table entries in Phase 1c.
2. **Validation failure after static config.** Phase 1c wrote an `authentication:` block based on grep signals, but `API_KEY=$HAWK_API_KEY hawk validate auth stackhawk.yml` returned non-zero — wrong login path, wrong token extractor, etc.
3. **Explicit user request.** The user asks to use the live analyzer. Common phrasings:
   - "Set up auth interactively"
   - "Use the auth analyzer"
   - "Run the live analyzer"
   - "I want to log in manually for auth"
   - "Capture my login flow"

In each case, announce before running so the user knows the fallback is firing.

## Prerequisite checks

Before opening a browser session, confirm the tooling is present. If any check fails, **do not** attempt the fallback — punt to manual setup. The skill does not crash; Phase 1c.5 simply doesn't run.

```bash
# 1. Hawk supports the new auth-analyzer commands and recipe
hawk config show recipe.auth-analyzer-workflow --text >/dev/null 2>&1 \
  || PUNT "Your hawk version doesn't include the auth analyzer. Upgrade hawk, or configure auth manually with 'hawk config show app.authentication --text'."

hawk perch validate-auth --help >/dev/null 2>&1 \
  || PUNT "Your hawk version doesn't include 'hawk perch validate-auth'. Upgrade hawk."

# 2. Chrome is installed (macOS / Linux)
{ [ -d "/Applications/Google Chrome.app" ] \
    || command -v google-chrome >/dev/null 2>&1 \
    || command -v chromium      >/dev/null 2>&1; } \
  || PUNT "Auth analyzer requires Chrome. Configure auth manually with 'hawk config show app.authentication --text'."
```

`PUNT` is shorthand for: print the message, stop the fallback, return control to the user.

## Announcement templates

Use the announcement that matches the trigger:

| Trigger | Announcement |
|---|---|
| Ambiguous classification | "Static auth detection couldn't classify the pattern. Falling back to the live auth analyzer." |
| Validation failure | "Static auth config failed validation. Falling back to the live auth analyzer." |
| Explicit request | "Running the live auth analyzer at your request." |

The user should always know the fallback is firing before the browser opens.

## Start the capture

Reuse an existing perch session if one is already running; otherwise start fresh:

```bash
if ! pgrep -f "hawk perch" >/dev/null 2>&1; then
  API_KEY=$HAWK_API_KEY hawk perch start --with-chrome stackhawk.yml
fi
```

Then announce to the user:

> "Chrome has opened. Please log in to your app and do a few authenticated actions (open a page or two that requires login). Let me know when you're done."

Wait for explicit user confirmation. No timeout — the user drives this.

## Verify the traffic buffer

After the user says "done", confirm the buffer isn't empty:

```bash
API_KEY=$HAWK_API_KEY hawk perch traffic --format json
```

If the result is an empty array, re-prompt once:

> "I don't see any captured traffic yet. Did you log in successfully? Please try again, then tell me when you're done."

If still empty after the retry:

> "Still no captured traffic. Configure auth manually with `hawk config show app.authentication --text` and re-invoke."

Stop perch (`API_KEY=$HAWK_API_KEY hawk perch stop`) and punt. Do not advance to the analyzer with an empty buffer.

## Run the analyzer

Announce: "Running the auth analyzer."

```bash
hawk config show recipe.auth-analyzer-workflow --text
```

Follow the returned markdown step-by-step. The recipe owns iteration:

- Read auth signals: `API_KEY=$HAWK_API_KEY hawk perch auth-signals --format json`
- Select the matching recipe: `hawk config show app.authentication.<type> --text`
- Write `authentication:` into `stackhawk.yml`
- Validate live: `API_KEY=$HAWK_API_KEY hawk perch validate-auth stackhawk.yml`
- On failure, read the structured errors + `hint` fields, fix, repeat
- Cap at 5 iterations

The recipe's `validate-auth` runs against the live HSTE daemon perch started, so the validator actually executes the login flow against your running app.

## Cleanup on success

```bash
API_KEY=$HAWK_API_KEY hawk perch stop
```

Announce: "Auth configured and validated. Continuing to scan."

Return control to Step 3 (Validate and Run). `stackhawk.yml` now has a validated `authentication:` block.

## Cleanup on failure

If the analyzer exhausts iterations or hits an unrecoverable error:

```bash
API_KEY=$HAWK_API_KEY hawk perch stop
```

Surface the structured errors from the final `validate-auth` call. Announce:

> "The auth analyzer couldn't produce a valid config in N iterations. Errors above. Configure auth manually with `hawk config show app.authentication --text` and re-invoke the skill."

Do **not** proceed to scan with a broken auth config.

## Error handling

| Failure mode | Skill behavior |
|---|---|
| Chrome not installed | Announce + punt to manual setup. |
| Hawk too old (perch subcommands or recipe missing) | Announce + upgrade prompt, punt. |
| Perch daemon already running | Reuse session; do not start a second. |
| `hawk perch start` fails (port collision, app unreachable) | Surface stderr, punt to manual. |
| Empty traffic buffer after user confirms | Re-prompt once; punt if still empty. |
| Recipe iteration cap exhausted | Stop perch, surface validator errors, punt. |
| Mid-iteration crash (perch dies, gRPC unreachable) | Stop perch, surface stderr, punt. |
| User interrupts (Ctrl-C) during capture | Stop perch cleanly, exit. |

## Re-run behavior

After a successful run, `stackhawk.yml` has an `authentication:` block. On subsequent skill invocations:

- Phase 1c sub-step 0 sees the block already exists.
- If `API_KEY=$HAWK_API_KEY hawk validate auth stackhawk.yml` passes, the scan proceeds with the existing block — no fallback.
- If `validate auth` fails (login endpoint moved, token expired logic changed, etc.), trigger #2 fires and Phase 1c.5 runs again.

No special re-entry logic needed — the trigger conditions handle re-runs naturally.

## Cleanup on agent disconnect

If the user closes the agent session mid-capture, perch keeps running. Document this caveat to the user:

> "If you abandon the session before I say 'continuing to scan', run `hawk perch stop` yourself to clean up."

Future versions of the skill may automate this.
