# usernamePassword

Credential source for applications that accept a single POST with a username and password. Covers form-based logins, JSON API logins, and HTTP Basic.

## When to use

- App has a `/login` endpoint that accepts `username` + `password`
- App has a JSON API `/auth/signin` that returns a token
- First-choice auth pattern — prefer this over `oauth` / scripts when it fits

## Config

**Form-based login + cookie session:**

```yaml
app:
  antiCsrfParam: _csrf           # include if login form has a CSRF token
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

**JSON API login + token extraction:**

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
    loggedInIndicator: "HTTP.*2[0-9][0-9].*"
    loggedOutIndicator: "HTTP\\/1\\.1 4[0-9][1-3].*"
    testPath:
      path: /api/items
      success: ".*200.*"
```

## Field notes

- `type`: `FORM` (`application/x-www-form-urlencoded` POST) or `JSON` (`application/json` POST body).
- `loginPath`: endpoint that accepts credentials. Can be a path on `app.host` (`/login`) or a full URL when login is on a different host (`https://idp.example.com/auth/login`) — useful for SSO/federated login.
- `loginPagePath`: optional, the path that serves the HTML login form (FORM type only — used to fetch CSRF tokens before submitting).
- `usernameField` / `passwordField`: the actual form field names the app expects (not necessarily `username`/`password`).
- `scanUsername` / `scanPassword`: use `${VAR}` env var interpolation. Pair with `cookieAuthorization` (for `Set-Cookie` sessions) or `tokenExtraction` + `tokenAuthorization` (for token responses).
- `otherParams`: add additional form fields beyond username/password:

  ```yaml
  otherParams:
    - name: rememberMe
      val: "true"
  ```

## Source

Adapted from `stackhawk/hawkscan/mcp-server/src/main/resources/markdown/app.authentication.usernamePassword.md`. Verified against `integration-tests/src/test/resources/test_files/conf_files/stackhawk-jsv-form-cookie.yml` and `stackhawk-jsv-json-token.yml`.
