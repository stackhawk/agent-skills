# Codebase → Config Mapping

## Tech flags
Reuse the hawkscan skill's tech-flag detection heuristics (linked from the Companion
skills section of SKILL.md) — evidence files such as `package.json`, `pom.xml`, `go.mod`,
`requirements.txt`, `docker-compose.yml`, `Gemfile`, `*.csproj`/`*.sln`.
Map detected techs to canonical flag keys. The canonical flag list is authoritative — fetch
it with `hawkop app tech-flags get --app <APP> --format json` and only use keys that exist.
When enabling a child flag (e.g. `Language.Java.Spring`), also enable its parents.

## Plugins
Start from a base preset that matches the app shape:
- Plain REST/HTML app → `DEFAULT`
- OpenAPI-described API → `DEFAULT_API`
- GraphQL API → the GraphQL preset (confirm exact name via `hawkop policy list`)

Fetch the base with `hawkop policy get --name <PRESET>`. Then:
- DROP plugin families irrelevant to the detected stack (reduces noise + time).
- KEEP/ADD families the stack needs.
Validate every plugin id against the base policy's plugin list — never invent ids.

## stackhawk.yml correctness
- App type: SPA → enable SPA/spider settings; REST → leave spider conservative.
- OpenAPI spec present → set `app.openApiConf` to point at it.
- GraphQL → consider `app.autoPolicy: true`.
- Base paths → set sensible scope.
- Auth → FLAG for the user; never fabricate credentials.

## Profile lean
Default **balanced**. A speed lean drops more borderline plugin families and tightens
scope; a coverage lean keeps families when in doubt. Only deviate from balanced if the user
explicitly asks.
