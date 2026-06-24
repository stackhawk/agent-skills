# Auth Analyzer Fallback

When Phase 1c's static auth detection can't produce a working `authentication:` block, this reference describes the fallback flow that drives the auth analyzer through the **`hawk perch onboard`** wizard. Onboard is the single command that owns daemon startup, Chrome capture, the iterative validate-auth loop, and structured progress events for skill consumption.

## Contents
- [When to invoke this fallback](#when-to-invoke-this-fallback)
- [Prerequisite checks](#prerequisite-checks)
- [Announcement templates](#announcement-templates)
- [Start hawk perch onboard](#start-hawk-perch-onboard)
- [Event handler matrix](#event-handler-matrix)
- [Writing the auth YAML](#writing-the-auth-yaml)
- [Iterating on validation failures](#iterating-on-validation-failures)
- [Cleanup on success](#cleanup-on-success)
- [Placeholder applicationId guard](#placeholder-applicationid-guard)
- [Cleanup on failure](#cleanup-on-failure)
- [Error handling](#error-handling)
- [Re-run behavior](#re-run-behavior)
- [Cleanup on agent disconnect](#cleanup-on-agent-disconnect)
- [Why a single command instead of orchestrating pieces](#why-a-single-command-instead-of-orchestrating-pieces)

---

## When to invoke this fallback

Phase 1c.5 fires when **any** of these are true:

1. **Ambiguous classification.** Step 1a found auth signals in the codebase (a single `AddAuthentication(` call, conflicting framework imports, two independent but unrelated signals) but the agent can't confidently map the pattern to one of the recipe-table entries in Phase 1c.
2. **Validation failure after static config.** Phase 1c wrote an `authentication:` block based on grep signals, but `API_KEY=$HAWK_API_KEY hawk validate auth stackhawk.yml` returned non-zero — wrong login path, wrong token extractor, etc.
3. **Explicit user request.** The user asks to use the live analyzer. Common phrasings:
   - "Set up auth interactively"
   - "Use the auth analyzer"
   - "Run the live analyzer"
   - "I want to log in manually for auth"
   - "Capture my login flow"

In each case, announce before running so the user knows the fallback is firing.

## Prerequisite checks

Before opening a browser session, confirm the tooling is present. If any check fails, **do not** attempt the fallback — punt to manual setup.

```bash
# 1. Hawk supports `perch onboard` and the recipe
hawk perch onboard --help >/dev/null 2>&1 \
  || PUNT "Your hawk version doesn't include 'hawk perch onboard'. Upgrade hawk, or configure auth manually with 'hawk config show app.authentication --text'."

hawk config show recipe.auth-analyzer-workflow --text >/dev/null 2>&1 \
  || PUNT "The recipe.auth-analyzer-workflow is missing from this build of hawk. Upgrade hawk."

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

The user should always know the fallback is firing before Chrome opens.

## Start `hawk perch onboard`

Pick the invocation based on what's in the working directory:

```bash
# Case A: stackhawk.yml already exists (Phase 1c left one behind, or the user wrote one)
API_KEY=$HAWK_API_KEY hawk perch onboard \
  --events json \
  --auth-output ./stackhawk-auth.yml \
  --max-attempts 5 \
  ./stackhawk.yml

# Case B: no stackhawk.yml yet (greenfield). Onboard will synthesize one from --app-host.
API_KEY=$HAWK_API_KEY hawk perch onboard \
  --events json \
  --auth-output ./stackhawk-auth.yml \
  --max-attempts 5 \
  --app-host "$APP_HOST"
```

Spawn as a long-running subprocess. **stdout** carries JSONL phase events. **stderr** carries human text (banners, prompts, error detail) — don't discard it; tee it for the user.

If onboard reports the daemon is already running, it reuses the existing one — do not start a second.

## Event handler matrix

Stream-parse one JSON object per line from stdout. Each line is `{"phase": "...", ...payload}`.

| `phase` | Payload fields | Skill behavior |
|---|---|---|
| `starting` | `configFile`, `appHost` | Acknowledge silently |
| `daemonReady` | `proxyPort`, `daemonReused`, `chromeLaunched` | Tell user: "Chrome is open at proxy port `<proxyPort>`. Please log in to your app and do a few authenticated actions." If `chromeLaunched: false`, surface the stderr warning and tell the user to open the app in their own browser with proxy `localhost:<proxyPort>`. |
| `awaitingLogin` | `prompt` | **Wait for user confirmation in chat.** In non-TTY mode the wizard immediately advances past this phase (it doesn't actually block), but the skill must not write the auth YAML until the user confirms they've logged in — onboard has no other gate for "login done". |
| `awaitingAuthYaml` | `expectedPath` | After user confirms login, consult the recipe and the captured traffic, then write `stackhawk-auth.yml` at `expectedPath`. (See "Writing the auth YAML" below.) |
| `validateAttempt` | `attempt`, `maxAttempts`, `success`, `errors[]` | On `success: true`, do nothing — wait for `done`. On failure, read `errors[]`, edit `stackhawk-auth.yml` to address each field-level error, save. The file-mtime change auto-triggers the next attempt — no Enter needed. |
| `done` | `outcome` (`success` \| `exhausted`), `configPath` | On `success`: run the placeholder-appId guard (below), then continue to Step 3. On `exhausted`: surface accumulated errors, punt to manual. The code does not emit `outcome: "abandoned"` — Ctrl-C kills the JVM before any DONE event. |

## Writing the auth YAML

When `awaitingAuthYaml` fires, consult three sources in this order:

1. **Recipe** — the canonical workflow:
   ```bash
   hawk config show recipe.auth-analyzer-workflow --text
   ```
2. **Captured traffic** — what the user actually did during login:
   ```bash
   API_KEY=$HAWK_API_KEY hawk perch traffic --format json
   ```
3. **Auth signals** — structured pattern detection (login candidates, cookie setters, token responses, OAuth endpoints):
   ```bash
   API_KEY=$HAWK_API_KEY hawk perch auth-signals --format json
   ```

Then pick the matching authentication recipe:

```bash
hawk config show app.authentication.<type> --text
```

Write the resulting `authentication:` block into `stackhawk-auth.yml` at the path onboard expects.

## Iterating on validation failures

Each `validateAttempt` event with `success: false` carries an `errors[]` array. Each error has:

| Field | Meaning |
|---|---|
| `field` | Auth field that failed (e.g., `usernamePassword.loginPath`) — `_grpc` means the daemon crashed |
| `message` | Raw validator message |
| `hint` | Next diagnostic command — typically `hawk config show app.authentication.<field> --text` |
| `jsonPath` | YAML path to the failing field |

Read every error, follow the hint, edit `stackhawk-auth.yml`. Save the file — the file-mtime change is what triggers the next attempt. Do not send a newline on stdin and do not respawn onboard.

If `field == "_grpc"`, the daemon crashed mid-attempt. Surface the error and punt — restart from scratch with `hawk perch start` is the recovery path, not anything onboard can do.

## Cleanup on success

```bash
API_KEY=$HAWK_API_KEY hawk perch stop
```

`hawk perch onboard` does **not** tear down the daemon on exit (by design — `Onboard does not own the daemon`). The skill must always call `hawk perch stop` after the onboard subprocess terminates, on every exit path.

## Placeholder applicationId guard

If onboard synthesized `stackhawk.yml` from `--app-host` (Case B above), it wrote `applicationId: 00000000-0000-0000-0000-000000000000`. **Subsequent skill runs will not re-prompt** — they'll find the file and reuse it, then `hawk scan` upload will fail.

After `done outcome=success`, before continuing to Step 3:

```bash
grep -q "00000000-0000-0000-0000-000000000000" stackhawk.yml \
  && echo "Replace the placeholder applicationId in stackhawk.yml with your real one from app.stackhawk.com before scanning."
```

If the placeholder is present, prompt the user for their applicationId and replace it before invoking `hawk scan`.

Announce: "Auth configured and validated. Continuing to scan."

Return control to Step 3 (Validate and Run). `stackhawk.yml` plus `stackhawk-auth.yml` now have a validated `authentication:` configuration.

## Cleanup on failure

If onboard exits with `done outcome=exhausted` or the subprocess dies mid-flow:

```bash
API_KEY=$HAWK_API_KEY hawk perch stop
```

Surface the accumulated `errors[]` from the final `validateAttempt` event(s). Announce:

> "The auth analyzer couldn't produce a valid config in N attempts. Errors above. Edit `stackhawk-auth.yml` manually using `hawk config show app.authentication.<field> --text` for each failing field, then re-invoke the skill."

Do **not** proceed to scan with a broken auth config.

## Error handling

| Failure mode | Skill behavior |
|---|---|
| Chrome not installed | Announce + punt to manual setup |
| Hawk too old (`perch onboard` missing or recipe missing) | Announce + upgrade prompt, punt |
| `hawk perch onboard` exits non-zero before `done` | Surface stderr, `hawk perch stop`, punt |
| Daemon already running | Onboard reuses it (`daemonReused: true`); skill does nothing special |
| `chromeLaunched: false` in `daemonReady` | Tell user to open the app manually at `proxy localhost:<proxyPort>` |
| `awaitingAuthYaml` fires but skill can't write the file (permissions, etc.) | Stop onboard via `hawk perch stop` (which kills the daemon — and onboard with it), surface error, punt |
| `validateAttempt` error with `field: "_grpc"` | Daemon crashed; `hawk perch stop`, punt |
| `done outcome=exhausted` | Surface final errors, `hawk perch stop`, punt to manual |
| User interrupts the skill mid-capture | Best effort: `hawk perch stop`; warn user that onboard's subprocess may have leaked |

## Re-run behavior

After a successful run, `stackhawk-auth.yml` exists alongside `stackhawk.yml`. On subsequent skill invocations:

- If `API_KEY=$HAWK_API_KEY hawk validate auth stackhawk.yml` passes, the scan proceeds — no fallback.
- If `validate auth` fails (login endpoint moved, token logic changed, app rebuilt), trigger #2 fires and Phase 1c.5 runs again — onboard reuses the existing `stackhawk.yml` (case A above).

No special re-entry logic needed.

## Cleanup on agent disconnect

If the user closes the agent session mid-capture, the onboard subprocess and the HSTE daemon both keep running. Document this caveat to the user before invoking onboard:

> "If you abandon the session before I say 'continuing to scan', run `hawk perch stop` yourself to clean up."

## Why a single command instead of orchestrating pieces

Earlier versions of this fallback drove `hawk perch start`, `hawk perch traffic`, `hawk perch auth-signals`, and `hawk perch validate-auth` separately, with the skill owning the iteration loop. That worked but pushed retry caps, mtime detection, structured-error mapping, and "daemon ready?" polling into the skill. `hawk perch onboard` now owns all of that. The skill's job shrank to: trigger detection, user announcements, writing the YAML, reading event errors, and cleanup.

For the design history, see `docs/superpowers/specs/2026-05-18-llm-agnostic-auth-loop-design.md` and `docs/superpowers/specs/2026-05-19-perch-onboard-design.md` in the hawkscan repo.
