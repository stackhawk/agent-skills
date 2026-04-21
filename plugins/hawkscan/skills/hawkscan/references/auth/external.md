# external

Credential source for pre-obtained tokens or cookies. Bypasses login entirely — useful when the token comes from a CI secret, SSO pre-flight, or an out-of-band auth flow. `external` supplies the value; pair with `tokenAuthorization` (for header injection) or `cookieAuthorization` (for cookies).

## When to use

- Token already obtained from CI (`GITHUB_TOKEN`, Auth0 service token, etc.)
- SSO / federated auth handled outside the scan
- No login flow HawkScan can observe

## Config

**Inject a bearer token:**

```yaml
app:
  authentication:
    external:
      type: TOKEN
      value: ${AUTH_TOKEN}
    tokenAuthorization:
      type: HEADER
      value: Authorization
      tokenType: Bearer
    loggedInIndicator: "HTTP/[0-9]+.[0-9]+\\s+([2-3][0-9][0-9])"
    loggedOutIndicator: "HTTP/[0-9]+.[0-9]+\\s+(4[0-9][0-9])"
    testPath:
      path: /api/protected
      success: ".*200.*"
```

**Inject a session cookie:**

```yaml
app:
  authentication:
    external:
      type: COOKIE
      value: ${SESSION_COOKIE}
    cookieAuthorization:
      cookieNames:
        - session
    testPath:
      path: /dashboard
      success: ".*200.*"
```

## Field notes

- `external.type`: `TOKEN` or `COOKIE`.
- `external.value`: the raw token/cookie value. Always use `${VAR}` env var interpolation — never hardcode.
- `external` only supplies the value. The authorization block (`tokenAuthorization` or `cookieAuthorization`) carries the header name / cookie name.
- For JWTs, set `tokenAuthorization.isJWT: true` — HawkScan will re-check expiry via the `exp` claim rather than re-running any login flow. If the token expires mid-scan, you'll need a longer-lived token or switch to `externalCommand` to refresh.

## Source

Adapted from `stackhawk/hawkscan/mcp-server/src/main/resources/markdown/app.authentication.external.md` (with corrections — upstream docs have the wrong YAML shape). Verified against `common/src/test/resources/conf_files/regression/stackhawk-auth-basic.yml`.
