# testPath

Required field in every auth config. A protected endpoint HawkScan hits to verify authentication works.

## Requirements

1. Returns **401** or **403** when accessed WITHOUT authentication.
2. Returns **200** when accessed WITH valid authentication.

## Config

```yaml
app:
  authentication:
    testPath:
      path: /api/user
      success: ".*200.*"
      requestMethod: GET    # optional; defaults to GET
```

## Good candidates

- API endpoints that return user data (`/api/user`, `/api/profile`, `/api/me`)
- Protected dashboard data endpoints (`/dashboard/data`)
- Any endpoint that requires the session cookie or bearer token

## Bad candidates

- The login endpoint itself (accepts unauthenticated requests)
- Public endpoints (always return 200)
- Static assets, health checks, `robots.txt`

## Field notes

- `success`: regex matched against the full HTTP response. `.*200.*` catches any response containing `200`.
- Alternative: use `fail: ".*401.*"` to match failure patterns instead of success.
- `requestMethod`: `GET`, `POST`, or `PUT`. Default `GET`.
- Supports an optional `requestBody` string when the protected endpoint requires one.

## Source

Adapted from `stackhawk/hawkscan/mcp-server/src/main/resources/markdown/app.authentication.testPath.md`. Verified against `integration-tests/src/test/resources/test_files/conf_files/stackhawk-jsv-form-cookie.yml`.
