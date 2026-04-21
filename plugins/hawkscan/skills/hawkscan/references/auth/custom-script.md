# Custom Script

Credential source for complex auth flows that config alone can't handle (multi-step MFA, federated SAML/OAuth, cross-domain cookies, non-standard sessions). Scripts are written in Kotlin (`.kts`) — preferred — or JavaScript.

## When to use

- Multi-step login (e.g., MFA, captcha, two-page forms)
- Federated SAML/OAuth flows with multi-host redirects
- Custom session handshakes that require request/response inspection

Prefer this over `externalCommand` — scripts run in-process and have direct access to the HTTP request/response pipeline.

## Config

```yaml
app:
  authentication:
    script:
      name: auth-script
      filePath: scripts/authenticate.kts
    loggedInIndicator: "HTTP/[0-9]+.[0-9]+\\s+([2-3][0-9][0-9])"
    loggedOutIndicator: "HTTP/[0-9]+.[0-9]+\\s+(4[0-9][0-9])"
    testPath:
      path: /api/protected
      success: ".*200.*"

hawkAddOn:
  scripts:
    - name: auth-script
      filePath: scripts/authenticate.kts
      type: authentication
```

## Field notes

- `script.name` must match a `name` under `hawkAddOn.scripts`.
- `type: authentication` tells HawkScan to invoke the script during login.
- For session management (re-login when session expires), pair with a `type: session` script under `hawkAddOn.scripts`.

## Getting started

See the [hawkscan-examples repo](https://github.com/kaakaww/hawkscan-examples#authentication-and-session-management-scripts) for Kotlin script templates covering:

- Form login with cookie extraction
- Token-for-cookie exchange
- SAML redirect handling
- Multi-step login flows

## Source

Adapted from existing content in `plugins/hawkscan/skills/hawkscan/references/config-patterns.md` (pre-split) and the kaakaww/hawkscan-examples script templates. Upstream MCP markdown has no equivalent file.
