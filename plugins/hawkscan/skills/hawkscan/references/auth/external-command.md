# externalCommand

**Last-resort** credential source. Runs an inline `sh`+`curl` command that outputs JSON with headers and/or cookies for HawkScan to inject. Use only when `usernamePassword`, `oauth`, and scripts all can't handle the flow.

## When to use

- None of the other auth patterns fit
- You need a shell command (`curl`, `jq`, `awk`) to mint the token
- The token must be refreshed periodically — `externalCommand` re-runs whenever HawkScan detects the session has expired

## Constraints

- Only `sh` and `curl` are allowed — no custom binaries, no external script files.
- The command must be inline under `parameters`.
- `timeoutSeconds` defaults to 60.

## Config

```yaml
app:
  authentication:
    externalCommand:
      command: "sh"
      parameters:
        - "-c"
        - |
          RESPONSE=$(curl -sk -c - \
            -d "username=${SCAN_USERNAME}&password=${SCAN_PASSWORD}" \
            "https://example.com/login")
          SESSION_COOKIE=$(echo "$RESPONSE" | grep -o 'JSESSIONID\s.*' | awk '{print $2}')
          echo "{\"cookies\": [{\"JSESSIONID\": \"$SESSION_COOKIE\"}]}"
    loggedInIndicator: "\\QSign Out\\E"
    loggedOutIndicator: ".*Location:.*/login.*"
    testPath:
      path: /api/profile
      success: ".*200.*"
```

## Output format

The command must print JSON to stdout, with `headers` and/or `cookies` as **arrays of single-key objects**:

```json
{"headers": [{"Authorization": "Bearer eyJ..."}], "cookies": [{"JSESSIONID": "abc123"}]}
```

Both `headers` and `cookies` are optional; include whichever the application requires.

## Field notes

- `command`: the executable to run (typically `sh`).
- `parameters`: list of arguments passed to the command. Use `["-c", "<inline script>"]` for multi-line shell.
- `timeoutSeconds`: how long HawkScan waits for the command before failing (default 60).
- The command runs once at scan start and again whenever HawkScan detects the session has expired.
- Env vars in your `stackhawk.yml` (e.g., `${SCAN_USERNAME}`) are interpolated before the command runs. They're also passed through as process env so the command can read them directly.
- **Proxy env:** HawkScan injects `HTTP_PROXY`, `HTTPS_PROXY`, and `PROXY_CA_CERT` into the command's environment so outbound requests route through the scan proxy. No configuration needed — but don't override these in the command.

## Source

Adapted from `stackhawk/hawkscan/mcp-server/src/main/resources/markdown/app.authentication.externalCommand.md` (with corrections — upstream docs show object-shaped JSON output; canonical shape is arrays of single-key objects, per `ExternalCommandAuthenticationMethodTest.kt`). Verified against `integration-tests/src/test/resources/test_files/conf_files/stackhawk-jsv-external-command-auth.yml`.
