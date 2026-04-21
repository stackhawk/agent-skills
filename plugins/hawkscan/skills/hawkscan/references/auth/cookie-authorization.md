# cookieAuthorization

**REQUIRED** when the application uses cookies for session management. If the login response has `Set-Cookie` headers (look for `JSESSIONID`, `PHPSESSID`, `connect.sid`, `session`), you MUST include `cookieAuthorization` alongside your credential source. Without it, HawkScan authenticates successfully but the session is dropped during scanning.

## When to use

- Login response sets cookies via `Set-Cookie`
- Traditional server-rendered web apps (Rails, Django, Spring, Express sessions)
- APIs that use cookie-based sessions instead of bearer tokens

## Config

```yaml
app:
  authentication:
    usernamePassword:
      type: FORM
      loginPath: /login
      loginPagePath: /login
      usernameField: username
      passwordField: password
      scanUsername: ${SCAN_USERNAME}
      scanPassword: ${SCAN_PASSWORD}
    cookieAuthorization:
      cookieNames:
        - JSESSIONID
    loggedInIndicator: "\\QSign Out\\E"
    loggedOutIndicator: ".*Location:.*/login.*"
    testPath:
      path: /search
      success: ".*200.*"
```

## How to find the cookie name

Log in once with `curl -v -X POST -d "username=user@example.com&password=secret" https://app.example.com/login` and look at the `Set-Cookie` response headers. Or open browser devtools → Network tab, submit the login form, inspect the response's Cookies tab.

Common session cookie names by stack:

- Java / Spring: `JSESSIONID`
- PHP: `PHPSESSID`
- Node.js / Express: `connect.sid`
- Generic: `session`, `session_id`, `sid`

## Field notes

- `cookieNames`: list of cookie names to track for the session. Set this to the actual session cookie(s) from the login response.
- Minimal form `cookieAuthorization: {}` (empty object) also enables cookie-based session management, but specifying `cookieNames` is strongly recommended — HawkScan knows which cookies matter and can warn on loss.
- Pairs with `usernamePassword`, `oauth`, or `external` as the credential source.

## Source

Adapted from `stackhawk/hawkscan/mcp-server/src/main/resources/markdown/app.authentication.cookieAuthorization.md`. Verified against `integration-tests/src/test/resources/test_files/conf_files/stackhawk-jsv-form-cookie.yml`.
