# Codebase → Config Mapping

## Tech flags
Reuse the hawkscan skill's tech-flag detection heuristics (linked from the Companion
skills section of SKILL.md) — evidence files such as `package.json`, `pom.xml`, `go.mod`,
`requirements.txt`, `docker-compose.yml`, `Gemfile`, `*.csproj`/`*.sln`.
Map detected techs to canonical flag keys. The canonical flag list is authoritative — fetch
it with `hawk op app tech-flags get --app <APP> --format json` and only use keys that exist.
When enabling a child flag (e.g. `Language.Java.Spring`), also enable its parents.

## Plugins
Start from a base preset that matches the app shape:
- Plain REST/HTML app → `DEFAULT`
- OpenAPI-described API → `DEFAULT_API`
- GraphQL API → the GraphQL preset (confirm exact name via `hawk op policy list`)

Fetch the base with `hawk op policy get --name <PRESET>`. Then:
- DROP plugin families irrelevant to the detected stack (reduces noise + time).
- KEEP/ADD families the stack needs.
Validate every plugin id against the base policy's plugin list — never invent ids.
Edit the fetched JSON as little as possible: keep every field on every plugin entry (dropping
`pluginType` silently removes the passive rules) and never write `STRENGTH_LOW` /
`THRESHOLD_LOW` (protobuf zero values are dropped on serialization, leaving the plugin with no
strength/threshold). Keep the preset's values; never delete or blank them.

## stackhawk.yml correctness
- App type: SPA → enable SPA/spider settings; REST → leave spider conservative.
- OpenAPI spec present → set `app.openApiConf` to point at it.
- GraphQL → wire `app.graphqlConf` and keep the **broad GraphQL preset** as the first-scan policy.
  Do not narrow the plugin set before one broad scan has completed (auto-narrowing settings
  shrink coverage; `autoPolicy` is not a `stackhawk.yml` section on current hawk). Prune after.
- Base paths → set sensible scope.
- Auth → FLAG for the user; never fabricate credentials.

## Profile lean
Default **balanced**. A speed lean drops more borderline plugin families and tightens
scope; a coverage lean keeps families when in doubt. Only deviate from balanced if the user
explicitly asks.
