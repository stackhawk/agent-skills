# tokenExtraction

Extracts a token from the login response so `tokenAuthorization` can inject it into subsequent scan requests. Pair with [`token-authorization.md`](token-authorization.md).

## When to use

- Login response returns JSON containing a token (`{"token": "...", "accessToken": "...", "jwt": "..."}`)
- Login response sets the token in a header (e.g., `X-Auth-Token: <value>`)

## Config

```yaml
app:
  authentication:
    tokenExtraction:
      type: TOKEN_PATH
      value: "token"
```

## Extraction types

- **`TOKEN_PATH`** — dot-notation path into the JSON response body. Examples:
  - `"token"` — top-level key `{"token": "..."}`
  - `"access_token"` — top-level `{"access_token": "..."}`
  - `"data.token"` — nested `{"data": {"token": "..."}}`
  - `"authentication.token"` — nested under `authentication`
- **`TOKEN_REGEX`** — regular expression matched against response body or headers. Use when the token lives in a header or in a non-JSON response.

## Field notes

- The extracted value is available to `tokenAuthorization.value` via the templating HawkScan wires up internally — you do NOT need to reference `{tokenExtraction.value}` explicitly in your config.
- Prefer `TOKEN_PATH` over `TOKEN_REGEX` when the response is JSON — more robust to whitespace/ordering changes.

## Source

Adapted from `stackhawk/hawkscan/mcp-server/src/main/resources/markdown/app.authentication.tokenExtraction.md`. Verified against `integration-tests/src/test/resources/test_files/conf_files/stackhawk-jsv-json-token.yml`.
