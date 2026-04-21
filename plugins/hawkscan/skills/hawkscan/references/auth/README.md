# Authentication Configuration

How to pick an auth pattern and configure it in `stackhawk.yml`. For per-pattern details, see the files in this directory. Every auth config must satisfy three things: a **credential source**, exactly one **authorization type**, and a **`testPath`**.

## Decision tree

1. Do you have a token/cookie from outside the scan (CI secret, SSO pre-flight)? → [`external.md`](external.md)
2. Does the app accept a username/password POST? → [`username-password.md`](username-password.md)
3. Does it authenticate via an OAuth2 IdP (Auth0, Okta, Cognito)? → [`oauth.md`](oauth.md)
4. Is the login flow too complex for config alone (MFA, multi-step, cross-domain)? → [`custom-script.md`](custom-script.md)
5. None of the above? → [`external-command.md`](external-command.md) (last resort — `sh`+`curl` only)

## Escalation ladder

Prefer earlier entries — they're simpler and more observable.

1. **`usernamePassword`** — single POST with credentials. Form login, JSON API login, HTTP Basic.
2. **`oauth`** — OAuth2 grant flow to an external IdP.
3. **`script`** (`.kts` via `hawkAddOn.scripts`) — escalate when config alone can't handle the flow (multi-step, federated SAML/OAuth, cross-domain cookies).
4. **`externalCommand`** — last resort. `sh`+`curl` only, inline command in config.
5. **`external`** — pre-supplied token from outside the scan. Bypasses login entirely.

## Authorization types — pick exactly one

Every auth config MUST include exactly one authorization type so HawkScan maintains the authenticated session during scanning. **Without one, auth will succeed but scanning silently runs unauthenticated** — the #1 auth footgun.

- **[`cookieAuthorization`](cookie-authorization.md)** — REQUIRED when the login response sets session cookies (`Set-Cookie: JSESSIONID=...`, `PHPSESSID`, `connect.sid`, `session`).
- **[`tokenAuthorization`](token-authorization.md)** — REQUIRED when the login response returns a bearer token in the JSON body or a header. Pair with [`tokenExtraction`](token-extraction.md).
- **`sessionScript`** — custom session management via Kotlin script. Rare; covered briefly in [`custom-script.md`](custom-script.md).

**How to tell which you need:** Log in once with `curl -v` (or watch the browser devtools Network tab). If the response has `Set-Cookie` headers → `cookieAuthorization`. If it returns JSON with a `token` / `access_token` / `jwt` field → `tokenAuthorization` + `tokenExtraction`.

## Required for every auth config

- `loggedInIndicator` and/or `loggedOutIndicator` — regex to detect auth state (see below)
- `testPath` — a protected endpoint used to verify auth is working. See [`test-path.md`](test-path.md).

## loggedIn / loggedOut indicators

Indicator regexes match against the full HTTP response (status line, headers, body).

```yaml
# Generic status-code patterns (safe default for most APIs)
loggedInIndicator: "HTTP/[0-9]+.[0-9]+\\s+([2-3][0-9][0-9])"
loggedOutIndicator: "HTTP/[0-9]+.[0-9]+\\s+(4[0-9][0-9])"

# App-specific (match UI text or redirect behavior)
loggedInIndicator: "\\QSign Out\\E"
loggedOutIndicator: ".*Location:.*/login.*"
```

**JWT shortcut:** set `tokenAuthorization.isJWT: true` and HawkScan validates the session by decoding the JWT's `exp` claim directly. Indicators become unnecessary — set `loggedInIndicator: '.*'` and `loggedOutIndicator: ''`. More reliable than pattern matching. See [`token-authorization.md`](token-authorization.md).

## Common mistakes

- **Missing `cookieAuthorization` or `tokenAuthorization`.** Auth validates; scanning silently runs unauthenticated. You MUST set exactly one.
- **Authentication block outside `app`.** All auth goes under `app.authentication.*`.
- **Lowercase enums.** Use `FORM`, `JSON`, `HEADER`, `TOKEN`, `TOKEN_PATH` — not `form`, `json`, etc.
- **Missing `testPath`.** HawkScan can't verify auth without it.
- **Hardcoded credentials.** Use `${VAR}` env var interpolation for every secret.
- **Mid-string interpolation.** `host: "https://${HOST}/login"` does NOT interpolate — the whole value must be the variable: `host: ${FULL_HOST_URL}`. (Inside `value:` strings like `"Bearer ${TOKEN}"` the interpolation does work — the limitation is top-level path-style fields.)

## Source

Strategic guidance adapted from `stackhawk/hawkscan/mcp-server/src/main/resources/markdown/app.authentication.md`. YAML shapes verified against integration test configs in `stackhawk/hawkscan` — individual per-pattern files cite the specific test config.
