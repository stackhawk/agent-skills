# HawkScan Config Patterns Reference

Reference for API-type and auth-specific `stackhawk.yml` configuration patterns.
Read specific sections as needed — don't load the whole file for simple configs.

## Table of Contents
1. [OpenAPI / REST](#openapi--rest)
2. [GraphQL](#graphql)
3. [gRPC](#grpc)
4. [SOAP](#soap)
5. [JSON-RPC](#json-rpc)
6. [Authentication Patterns](#authentication-patterns)
   - [Inject Token or Cookie (External)](#inject-token-or-cookie-external)
   - [Form-Based Login (Username/Password)](#form-based-login-usernamepassword)
   - [OAuth2 (Third-Party IdP)](#oauth2-third-party-idp)
   - [External Command](#external-command)
   - [Custom Script](#custom-script)
7. [Multi-Environment Config](#multi-environment-config)
8. [Failure Threshold & CI Config](#failure-threshold--ci-config)
9. [Excluding Paths](#excluding-paths)

---

## OpenAPI / REST

```yaml
app:
  applicationId: ${APP_ID}
  env: ${APP_ENV:Development}
  host: ${APP_HOST:http://localhost:8080}
  openApiConf:
    filePath: openapi.yaml          # local file relative to stackhawk.yml
    # path: /v3/api-docs            # OR URL path on the host serving the spec
    # filePaths:                    # OR multiple spec files
    #   - frontend/openapi-app.json
    #   - backend/openapi-auth.json
```

If the spec lives at a URL your app serves (e.g., `/swagger.json`, `/v3/api-docs`),
use `path`. If it's a local file, use `filePath`. Use `filePaths` for multiple specs.
HawkScan uses the spec to discover routes the spider might miss.

**Custom variables for spec parameters:**
```yaml
  openApiConf:
    filePath: openapi.yaml
    fakerEnabled: true              # generate realistic test values with $faker: prefix
    includedMethods:                # methods to inject custom variables for
      - POST
      - PUT
    customVariables:
      - field: userId
        values:
          - "42"
      - field: orgId
        values:
          - ${TEST_ORG_ID}
```

---

## GraphQL

```yaml
app:
  applicationId: ${APP_ID}
  env: ${APP_ENV:Development}
  host: ${APP_HOST:http://localhost:4000}
  graphqlConf:
    enabled: true
    schemaPath: /graphql              # introspection endpoint path on the host
    # filePath: schema.json           # OR local schema file
    requestMethod: POST               # POST (default) or GET
    operation: ALL                    # QUERY, MUTATION, or ALL (default: both)
    fakerEnabled: true
    excludeOperations:
      - name: deleteUser
        type: MUTATION                # QUERY, MUTATION, or ALL
    customVariables:
      - field: userId
        values:
          - "42"
        operationName: getUser        # optional: filter by operation
        operationType: QUERY          # optional: QUERY or MUTATION
```

**Note:** Either `schemaPath` (introspection endpoint) or `filePath` (local schema
file) is required. If both are set, the file is loaded first, then `schemaPath` is
used for API requests.

---

## gRPC

```yaml
app:
  applicationId: ${APP_ID}
  env: ${APP_ENV:Development}
  host: ${APP_HOST:http://localhost:50051}
  grpcConf:
    path: 'localhost:9001'            # gRPC reflection endpoint
    # filePath: descriptor_set.pb    # OR path to descriptor set file
    customVariables:
      - field: customerEmail
        values:
          - $faker:email
```

**Note:** Use `path` when the gRPC server supports reflection. Use `filePath` when
reflection isn't available and you have a pre-compiled descriptor set. TLS/auth is
not currently supported for gRPC scanning.

---

## SOAP

```yaml
app:
  applicationId: ${APP_ID}
  env: ${APP_ENV:Development}
  host: ${APP_HOST:http://localhost:8080}
  soapConf:
    path: /ws/features.wsdl           # WSDL endpoint path on the host
    # filePath: features.xsd          # OR local schema definition file
```

Use `path` for a published WSDL endpoint, or `filePath` for a local XSD file.
HawkScan uses the schema to generate SOAP-specific payloads during scanning.

---

## JSON-RPC

```yaml
app:
  applicationId: ${APP_ID}
  env: ${APP_ENV:Development}
  host: ${APP_HOST:http://localhost:8080}
  jsonRpcConf:
    enabled: true
    endpoint: /jsonrpc                # JSON-RPC endpoint path
    filePath: openrpc.json            # local OpenRPC spec file
    # path: /openrpc.json            # OR hosted OpenRPC spec path
    maxDepth: 3                       # nested object generation depth (default: 3)
    fakerEnabled: true
    requestTimeout: 30000             # HTTP timeout in ms (default: 30000)
    excludeMethods:
      - "admin\\..*"                  # regex patterns for methods to skip
    customVariables:
      - field: userId
        values:
          - user-123
```

---

## Authentication Patterns

All authentication configs live under `app.authentication`. Every auth pattern should
include these common fields:

```yaml
app:
  authentication:
    loggedInIndicator: "HTTP/[0-9]+.[0-9]+\\s+([2-3][0-9][0-9])"
    loggedOutIndicator: "HTTP/[0-9]+.[0-9]+\\s+(4[0-9][0-9])"
    testPath:
      path: /api/protected-route
      success: ".*200.*"
      requestMethod: GET
    # ... auth method config below ...
```

- **`loggedInIndicator`** — regex matched against responses to confirm the scan is
  still authenticated. Typically matches 2xx/3xx status codes.
- **`loggedOutIndicator`** — regex that indicates the session was lost. Typically
  matches 4xx status codes.
- **`testPath`** — a protected endpoint used to verify authentication is working.
  Supports `success` or `fail` regex, `requestMethod` (GET/POST/PUT), and optional
  `requestBody`.

---

### Inject Token or Cookie (External)

Use when you have a pre-obtained token or cookie (e.g., from a CI secret or external
auth flow). `external` supplies the value; pair it with `tokenAuthorization` to tell
HawkScan which header to inject it into, or `cookieAuthorization` to manage it as a
session cookie.

**Inject a Bearer token:**
```yaml
app:
  authentication:
    loggedInIndicator: "HTTP/[0-9]+.[0-9]+\\s+([2-3][0-9][0-9])"
    loggedOutIndicator: "HTTP/[0-9]+.[0-9]+\\s+(4[0-9][0-9])"
    external:
      type: TOKEN
      value: ${AUTH_TOKEN}
    tokenAuthorization:
      type: HEADER
      value: Authorization
      tokenType: Bearer
    testPath:
      path: /api/protected
      success: ".*200.*"
      requestMethod: GET
```

**Inject a cookie:**
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

**Key fields:**
- `external.type`: `TOKEN` or `COOKIE`
- `external.value`: the raw token or cookie value — use `${VAR}` env var interpolation
- Pair `external` with `tokenAuthorization` (header injection) or `cookieAuthorization`
  (cookie jar) — the authorization block carries the header name / cookie name

---

### Form-Based Login (Username/Password)

Use for traditional web apps where HawkScan POSTs credentials to a login endpoint.

**Form-urlencoded login with cookie session:**
```yaml
app:
  antiCsrfParam: _csrf              # include if your login form has a CSRF token
  authentication:
    loggedInIndicator: "HTTP.*2[0-9][0-9]\\s*O[kK](\\s*)|HTTP.*3[0-9][0-9].*"
    loggedOutIndicator: "HTTP.*4[0-9][0-9](\\s*)Unauthorized.*"
    usernamePassword:
      type: FORM
      loginPagePath: /login
      loginPath: /login
      usernameField: email
      passwordField: password
      scanUsername: ${SCAN_USERNAME}
      scanPassword: ${SCAN_PASSWORD}
      otherParams:
        - name: rememberMe
          val: "true"
    cookieAuthorization:
      cookieNames:
        - sessionid
    testPath:
      path: /dashboard
      success: ".*200.*"
      requestMethod: GET
```

**JSON API login with token extraction:**
```yaml
app:
  authentication:
    loggedInIndicator: "HTTP/[0-9]+.[0-9]+\\s+([2-3][0-9][0-9])"
    loggedOutIndicator: "HTTP/[0-9]+.[0-9]+\\s+(4[0-9][0-9])"
    usernamePassword:
      type: JSON
      loginPath: /api/auth/login
      usernameField: email
      passwordField: password
      scanUsername: ${SCAN_USERNAME}
      scanPassword: ${SCAN_PASSWORD}
    tokenExtraction:
      type: TOKEN_PATH
      value: "authentication.token"     # dot-notation path in JSON response body
    tokenAuthorization:
      type: HEADER
      value: Authorization
      tokenType: Bearer
    testPath:
      path: /api/me
      success: ".*200.*"
      requestMethod: GET
```

**Key fields:**
- `type`: `FORM` (application/x-www-form-urlencoded) or `JSON` (application/json)
- `loginPagePath`: optional, path that serves the HTML login form (FORM type only)
- `loginPath`: path to POST credentials to
- `otherParams`: additional form fields beyond username/password
- `cookieAuthorization.cookieNames`: cookies to maintain for the session
- `tokenExtraction.value`: dot-notation path to locate the token in the JSON response
- `tokenAuthorization`: how to attach the extracted token to subsequent requests

---

### OAuth2 (Third-Party IdP)

Use when your app authenticates via an external IdP (Auth0, Okta, Cognito, etc.).
Supports `client_credentials` and `password` grant types.

**Client credentials grant:**
```yaml
app:
  authentication:
    loggedInIndicator: "HTTP/[0-9]+.[0-9]+\\s+([2-3][0-9][0-9])"
    loggedOutIndicator: "HTTP/[0-9]+.[0-9]+\\s+(4[0-9][0-9])"
    oauth:
      parameters:
        tokenEndpoint: ${TOKEN_ENDPOINT}
        grantType: client_credentials
        additionalBodyParams:
          audience: ${API_AUDIENCE}
          scope: "openid profile"
      credentials:
        clientId: ${CLIENT_ID}
        clientSecret: ${CLIENT_SECRET}
    tokenExtraction:
      type: TOKEN_PATH
      value: access_token
    tokenAuthorization:
      type: HEADER
      value: Authorization
      tokenType: Bearer
    testPath:
      path: /api/private
      success: ".*200.*"
      requestMethod: GET
```

**Password grant (resource owner):**
```yaml
    oauth:
      parameters:
        tokenEndpoint: ${TOKEN_ENDPOINT}
        grantType: password
        additionalBodyParams:
          audience: ${API_AUDIENCE}
      credentials:
        clientId: ${CLIENT_ID}
        clientSecret: ${CLIENT_SECRET}
        username: ${SCAN_USERNAME}
        password: ${SCAN_PASSWORD}
```

**Key:** Put all OAuth credentials in env vars. Never hardcode client secrets.

---

### External Command

Use when authentication requires running an external script or process that outputs
tokens/cookies as JSON. HawkScan runs the command and injects the result.

```yaml
app:
  authentication:
    loggedInIndicator: "HTTP.*2[0-9][0-9]\\s*O[kK](\\s*)|HTTP.*3[0-9][0-9].*"
    loggedOutIndicator: "HTTP.*4[0-9][0-9](\\s*)Unauthorized.*"
    externalCommand:
      command: "sh"
      parameters:
        - "-c"
        - "./scripts/get-auth-token.sh"
    testPath:
      path: /api/protected
      success: ".*200.*"
      requestMethod: GET
```

The external command must output JSON to stdout in this format:
```json
{
  "headers": [
    {"Authorization": "Bearer eyJ..."}
  ],
  "cookies": [
    {"session": "abc123"}
  ]
}
```

---

### Custom Script

Use when no preconfigured auth type fits (complex MFA flows, non-standard sessions,
etc.). Scripts are written in JavaScript or Kotlin.

```yaml
app:
  authentication:
    loggedInIndicator: "HTTP/[0-9]+.[0-9]+\\s+([2-3][0-9][0-9])"
    loggedOutIndicator: "HTTP/[0-9]+.[0-9]+\\s+(4[0-9][0-9])"
    script:
      name: auth-script
      filePath: scripts/authenticate.js
    testPath:
      path: /api/protected
      success: ".*200.*"
      requestMethod: GET
hawkAddOn:
  scripts:
    - name: auth-script
      filePath: scripts/authenticate.js
      type: authentication
```

See the [hawkscan-examples repo](https://github.com/kaakaww/hawkscan-examples#authentication-and-session-management-scripts)
for script templates.

---

## Multi-Environment Config

Layer config files to avoid duplication. Base config holds shared settings; env-specific
files override just what's different:

**`stackhawk.yml`** (base):
```yaml
app:
  applicationId: ${APP_ID}
  openApiConf:
    filePath: openapi.yaml
```

**`stackhawk-ci.yml`** (CI override):
```yaml
app:
  env: CI
  host: http://localhost:8080
tags:
  - name: _STACKHAWK_GIT_COMMIT_SHA
    value: ${COMMIT_SHA}
  - name: _STACKHAWK_GIT_BRANCH
    value: ${BRANCH_NAME}
hawk:
  failureThreshold: high
```

Run with both files (later file takes precedence):
```bash
hawk scan stackhawk.yml stackhawk-ci.yml
```

---

## Failure Threshold & CI Config

```yaml
hawk:
  failureThreshold: high    # high | medium | low
                            # scan exits 42 if findings at this level or above are found
```

**Recommended CI strategy:**
- Feature branches: `failureThreshold: high` — fail only on critical issues
- Main/release branches: `failureThreshold: medium` — stricter gate

---

## Spider & Scan Tuning

### Spider Configuration

Controls how HawkScan discovers routes before active scanning:

```yaml
hawk:
  spider:
    base: true                    # enable basic web crawler (default: true)
    ajax: false                   # enable AJAX spider for SPAs (default: false)
    ajaxBrowser: CHROME_HEADLESS  # browser for AJAX spider
    maxDurationMinutes: 2         # crawl duration limit (default: 2)
    seedPaths:                    # additional starting points for the spider
      - /api/v1
      - /api/v2
      - /dashboard
    har:
      filePath: traffic.har       # import HAR file for route discovery
```

**When to tune the spider:**
- **Low path count?** → Enable `ajax: true` for SPAs, add `seedPaths`, or feed an API spec
- **Scan taking too long?** → Reduce `maxDurationMinutes`
- **Missing authenticated routes?** → Add `seedPaths` for known protected endpoints

### Scan Runtime Configuration

Controls active scanning behavior:

```yaml
hawk:
  scan:
    maxDurationMinutes: 30        # total scan time limit
    maxRuleDurationMinutes: 5     # per-rule time limit
    requestDelayMillis: 0         # delay between requests (rate limiting)
    concurrentRequests: 20        # thread count (default: 20)
    policyName: "API-Scan"        # named scan policy
```

**When to tune:**
- **App rate-limited?** → Add `requestDelayMillis` and reduce `concurrentRequests`
- **Scan timing out?** → Increase `maxDurationMinutes`
- **Too many false positives?** → Use a named `policyName` to select specific scan rules

---

## Path Scope Control

### Excluding Paths

Prevent HawkScan from testing destructive or sensitive endpoints:

```yaml
app:
  excludePaths:
    - /admin/delete.*
    - /api/v1/users/.*/delete
    - /logout
    - /api/internal.*
```

### Including Paths

Restrict scanning to only specific paths (useful for focused scans):

```yaml
app:
  includePaths:
    - /api/v1/.*
    - /api/v2/.*
```

Paths are matched as regex. Both `excludePaths` and `includePaths` apply to the spider
and active scanning. When both are set, `includePaths` is applied first, then
`excludePaths` filters out matches.

**When to exclude:**
- Destructive operations (delete all, reset, nuke) that would break test state
- Third-party redirect endpoints not under your control
- Health check / metrics endpoints that generate noise

**When to include:**
- Scanning only a specific API version or service
- Focusing a scan after a targeted code change
- Reducing scan time by limiting scope

---

## Auto Policy & Input Vectors

### Auto Policy

Automatically optimize the scan policy based on your API type configuration:

```yaml
app:
  autoPolicy: true                # default: true
```

When enabled, HawkScan selects scan rules appropriate for your configured API type
(OpenAPI, GraphQL, gRPC, etc.). Leave this on unless you need fine-grained control
via `hawk.scan.policyName`.

### Auto Input Vectors

Automatically enable injectable parameter types based on your API:

```yaml
app:
  autoInputVectors: true          # default: true
```

When enabled, HawkScan determines which input types to test (query params, headers,
JSON body, etc.) based on your API configuration. Disable only if you need manual
control via `inputVectors`.

---

## CSRF Protection

If your app uses CSRF tokens, tell HawkScan the parameter name so it can extract
and include the token in requests:

```yaml
app:
  antiCsrfParam: _csrf            # name of the CSRF token parameter
```

This is particularly important for form-based authentication where login forms include
a CSRF token field.

---

## Header Injection (Replacer)

Use `hawkAddOn.replacer` to inject custom headers into every request. Useful for
tenant headers, API versioning, or custom `X-` headers your app requires:

```yaml
hawkAddOn:
  replacer:
    rules:
      - matchString: "x-requested-with"
        replacement: "HawkScan"
        replaceOnly: false          # false = add if missing, true = only replace existing
        isRegex: false
      - matchString: "x-tenant-id"
        replacement: ${TENANT_ID}
        replaceOnly: false
```

**Common uses:**
- `X-Requested-With` header for AJAX-expecting backends
- Custom tenant/org headers for multi-tenant apps
- API version headers (`Accept: application/vnd.api+json;version=2`)
