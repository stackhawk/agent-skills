# oauth

Credential source for applications that authenticate via an OAuth2 external IdP (Auth0, Okta, Cognito, Keycloak, etc.). Supports `client_credentials` and `password` grants.

## When to use

- App delegates auth to an OAuth2 IdP
- You have a `clientId` + `clientSecret` from the IdP
- The scan needs its own OAuth client registered (don't reuse a human user's OAuth session — register a service account or test client)

## Config

**Client credentials grant (service-to-service):**

```yaml
app:
  authentication:
    oauth:
      credentials:
        clientId: ${CLIENT_ID}
        clientSecret: ${CLIENT_SECRET}
      parameters:
        tokenEndpoint: ${TOKEN_ENDPOINT}
        grantType: client_credentials
        additionalBodyParams:
          audience: ${API_AUDIENCE}
          scope: "openid profile"
        requestHeaders:
          Content-Type: application/json
    tokenExtraction:
      type: TOKEN_PATH
      value: access_token
    tokenAuthorization:
      type: HEADER
      value: Authorization
      tokenType: Bearer
      isJWT: true
    loggedInIndicator: '.*'
    loggedOutIndicator: ''
    testPath:
      path: /api/private
      success: ".*200.*"
```

**Password grant (resource owner):**

```yaml
app:
  authentication:
    oauth:
      credentials:
        clientId: ${CLIENT_ID}
        clientSecret: ${CLIENT_SECRET}
        username: ${SCAN_USERNAME}
        password: ${SCAN_PASSWORD}
      parameters:
        tokenEndpoint: ${TOKEN_ENDPOINT}
        grantType: password
        additionalBodyParams:
          audience: ${API_AUDIENCE}
    tokenExtraction:
      type: TOKEN_PATH
      value: access_token
    tokenAuthorization:
      type: HEADER
      value: Authorization
      tokenType: Bearer
      isJWT: true
    testPath:
      path: /api/private
      success: ".*200.*"
```

## Field notes

- `grantType` values are lowercase with underscores: `client_credentials`, `password`. Not `CLIENT_CREDENTIALS`.
- `tokenEndpoint`: full URL to the IdP's token endpoint (e.g., `https://tenant.us.auth0.com/oauth/token`).
- `additionalBodyParams`: extra form params sent with the token request — usually `audience` and `scope`.
- `requestHeaders`: optional; override the `Content-Type` when the IdP requires JSON instead of the default `application/x-www-form-urlencoded`.
- `password` grant additionally needs `username` + `password` inside `credentials`.
- Always pair OAuth with `tokenExtraction` (to pull `access_token` from the IdP response) and `tokenAuthorization` (to inject it into scan requests). Set `isJWT: true` when the token is a JWT — more reliable than pattern-matching indicators.

## Source

Adapted from `stackhawk/hawkscan/mcp-server/src/main/resources/markdown/app.authentication.oauth.md`. Verified against `common/src/test/resources/conf_files/redaction/stackhawk_oauth_redacted.yml`.
