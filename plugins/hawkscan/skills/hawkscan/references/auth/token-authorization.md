# tokenAuthorization

Authorization type used when the application expects a token in a request header (e.g., `Authorization: Bearer <token>`). Pair with [`tokenExtraction`](token-extraction.md) (for login-based flows) or [`external`](external.md) (for pre-supplied tokens).

## When to use

- Login returns a bearer token / JWT in the JSON body or a response header
- Pre-obtained token injected via `external`
- API uses `Authorization: Bearer`, `X-Auth-Token`, or similar header

## Config

```yaml
app:
  authentication:
    usernamePassword:
      type: JSON
      loginPath: /api/auth/signin
      usernameField: username
      passwordField: password
      scanUsername: ${SCAN_USERNAME}
      scanPassword: ${SCAN_PASSWORD}
    tokenExtraction:
      type: TOKEN_PATH
      value: "token"
    tokenAuthorization:
      type: HEADER
      value: Authorization
      tokenType: Bearer
      isJWT: true
    loggedInIndicator: '.*'
    loggedOutIndicator: ''
    testPath:
      path: /api/items
      success: ".*200.*"
```

## Field notes

- `type`: typically `HEADER` to inject the token into a request header.
- `value`: the **header name** (e.g., `Authorization`, `X-Auth-Token`). Not a template string.
- `tokenType`: prefix added to the token value. Most common: `Bearer`. Also seen: `Basic` (for basic-auth tokens injected via `external`), or omit for raw token values.
- **`isJWT: true`** — enable when the token is a JWT. HawkScan decodes the JWT and validates the session by checking `exp` instead of relying on `loggedInIndicator` / `loggedOutIndicator`. More reliable than pattern matching. When `isJWT: true`, you can effectively disable indicators: `loggedInIndicator: '.*'` and `loggedOutIndicator: ''`.

## Source

Adapted from `stackhawk/hawkscan/mcp-server/src/main/resources/markdown/app.authentication.tokenAuthorization.md`. Verified against `integration-tests/src/test/resources/test_files/conf_files/stackhawk-jsv-json-token.yml` and `common/src/test/resources/conf_files/redaction/stackhawk_oauth_redacted.yml`.
