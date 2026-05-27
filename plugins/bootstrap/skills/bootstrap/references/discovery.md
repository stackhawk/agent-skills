# Discovery Reference

## Overview

Discovery is best-effort. The skill scans the target repo and any identified
upstream repos for storage-layer and API signals, builds a per-service model,
and falls back to asking the user where signals are ambiguous. This reference
documents the signals consulted and the commands the skill runs to detect them.

---

## Storage Type Detection — Per Ecosystem

A positive hit (any output from `find` or `grep`) is a confirmed signal. Conflicting signals require user clarification.

### PostgreSQL

**Signal:** Liquibase changelog YAML/XML, Flyway V-prefixed SQL under
`db/migration/`, Flyway config with a `jdbc:postgresql` URL, Prisma schema
with `provider = "postgresql"`, Alembic migrations directory, or `.psql` files.

```bash
# Liquibase changelogs
find . -not -path "*/node_modules/*" -not -path "*/target/*" \
  -not -path "*/build/*" -not -path "*/vendor/*" -not -path "*/.git/*" \
  \( -name "db.changelog-*.yaml" -o -name "db.changelog-*.xml" \) \
  2>/dev/null | head -5

# Flyway versioned migrations
find . -not -path "*/node_modules/*" -not -path "*/target/*" \
  -not -path "*/build/*" -not -path "*/vendor/*" -not -path "*/.git/*" \
  -path "*/db/migration/V*__*.sql" \
  2>/dev/null | head -5

# Flyway migrations under db/migrate (Rails-style layout)
find . -not -path "*/node_modules/*" -not -path "*/target/*" \
  -not -path "*/build/*" -not -path "*/vendor/*" -not -path "*/.git/*" \
  -path "*/db/migrate/*.sql" \
  2>/dev/null | head -5

# Flyway config with postgres JDBC URL
grep -rn --include="flyway.conf" --include="flyway.toml" \
  -E 'url\s*=\s*jdbc:postgresql' . 2>/dev/null | head -3

# Prisma postgresql provider
grep -rn --include="schema.prisma" \
  -E 'provider\s*=\s*"postgresql"' . 2>/dev/null | head -3

# Alembic migrations directory
find . -not -path "*/node_modules/*" -not -path "*/target/*" \
  -not -path "*/build/*" -not -path "*/vendor/*" -not -path "*/.git/*" \
  -name "env.py" -path "*/alembic/*" \
  2>/dev/null | head -3

# Raw .psql scripts
find . -not -path "*/node_modules/*" -not -path "*/target/*" \
  -not -path "*/build/*" -not -path "*/vendor/*" -not -path "*/.git/*" \
  -name "*.psql" \
  2>/dev/null | head -5
```

**Meaning:** Storage kind `postgres`. Seed emits standard SQL `INSERT` statements (no MySQL-specific backtick syntax). Prisma example: `provider = "postgresql"` in `prisma/schema.prisma`.

---

### MySQL

**Signal:** Liquibase changelog with `mysql` in the driver class or url,
Flyway config referencing `jdbc:mysql`, Prisma schema with
`provider = "mysql"`, or `.mysql` script files.

```bash
# Liquibase with MySQL dialect/driver
grep -rn \
  -E '(jdbc:mysql|com\.mysql\.|mysql\.jdbc)' \
  --include="*.yaml" --include="*.xml" --include="*.properties" \
  --exclude-dir=target --exclude-dir=build --exclude-dir=vendor \
  . 2>/dev/null | head -3

# Flyway config with MySQL JDBC URL
grep -rn --include="flyway.conf" --include="flyway.toml" \
  -E 'url\s*=\s*jdbc:mysql' . 2>/dev/null | head -3

# Prisma mysql provider
grep -rn --include="schema.prisma" \
  -E 'provider\s*=\s*"mysql"' . 2>/dev/null | head -3

# Raw .mysql scripts
find . -not -path "*/node_modules/*" -not -path "*/target/*" \
  -not -path "*/build/*" -not -path "*/vendor/*" -not -path "*/.git/*" \
  -name "*.mysql" \
  2>/dev/null | head -5
```

**Meaning:** Storage kind `mysql`. Seed SQL may use MySQL-specific syntax (backtick identifiers, `AUTO_INCREMENT`). Typical signal: `url=jdbc:mysql://localhost:3306/myapp` in `flyway.conf`.

---

### SQLite

**Signal:** Prisma schema with `provider = "sqlite"`, or `.sqlite` / `.db`
files committed to the repo (common in development-only setups or mobile apps).

```bash
# Prisma sqlite provider
grep -rn --include="schema.prisma" \
  -E 'provider\s*=\s*"sqlite"' . 2>/dev/null | head -3

# Committed SQLite database files
find . -not -path "*/node_modules/*" -not -path "*/target/*" \
  -not -path "*/build/*" -not -path "*/vendor/*" -not -path "*/.git/*" \
  \( -name "*.sqlite" -o -name "*.sqlite3" -o -name "*.db" \) \
  2>/dev/null | head -5
```

**Meaning:** Storage kind `sqlite`. No migration runner — the committed `.sqlite` / `.db` file is the source of truth. Bootstrap notes the file path and advises copy vs. recreate.

---

### MongoDB

**Signal:** `mongoose` in `package.json` dependencies, `mongo-go-driver`
import paths in Go source, `.mongo.js` scripts, or `pymongo` in
`requirements.txt` / `pyproject.toml`.

```bash
# Node — mongoose in package.json
grep -rn --include="package.json" \
  -E '"mongoose"\s*:' . 2>/dev/null \
  | grep -v node_modules | head -3

# Go — mongo-go-driver import
grep -rn --include="*.go" \
  -E '"go\.mongodb\.org/mongo-driver' \
  --exclude-dir=vendor \
  . 2>/dev/null | head -3

# Python — pymongo
grep -rn \
  --include="requirements*.txt" --include="pyproject.toml" \
  -E '^pymongo' . 2>/dev/null | head -3

# .mongo.js seed/fixture scripts
find . -not -path "*/node_modules/*" -not -path "*/target/*" \
  -not -path "*/build/*" -not -path "*/vendor/*" -not -path "*/.git/*" \
  -name "*.mongo.js" \
  2>/dev/null | head -5
```

**Meaning:** Storage kind `mongo`. Seed emits `db.collection.insertMany([...])` documents, not SQL.

---

### DynamoDB

**Signal:** `@aws-sdk/client-dynamodb` in Node package.json,
`aws-cdk-lib/aws-dynamodb` imports, `boto3.resource('dynamodb')` in Python,
or `dynamoose` package.

```bash
# Node — AWS DynamoDB client
grep -rn --include="package.json" \
  -E '"@aws-sdk/client-dynamodb"|"dynamoose"' . 2>/dev/null \
  | grep -v node_modules | head -3

# Node — CDK DynamoDB construct
grep -rn --include="*.ts" --include="*.js" \
  --exclude-dir=node_modules --exclude-dir=dist --exclude-dir=cdk.out \
  -E 'aws-cdk-lib/aws-dynamodb|@aws-cdk/aws-dynamodb' . 2>/dev/null | head -3

# Python — boto3 dynamodb
grep -rn --include="*.py" \
  --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ \
  -E "boto3\.(resource|client)\s*\(\s*['\"]dynamodb" . 2>/dev/null | head -3
```

**Meaning:** Storage kind `dynamo`. No SQL migrations — schema is implicit in CDK constructs or `create_table` calls. Bootstrap surfaces table definitions and emits seed in DynamoDB `PutItem` format.

---

### Cosmos

**Signal:** `@azure/cosmos` in Node package.json, or `Azure.Cosmos` NuGet
package reference in a `.csproj` file.

```bash
# Node — @azure/cosmos
grep -rn --include="package.json" \
  -E '"@azure/cosmos"' . 2>/dev/null \
  | grep -v node_modules | head -3

# .NET — Azure.Cosmos NuGet
grep -rn --include="*.csproj" \
  -E '"Azure\.Cosmos"' . 2>/dev/null | head -3

# Also check Directory.Packages.props (central package management)
grep -rn --include="Directory.Packages.props" \
  -E 'Azure\.Cosmos' . 2>/dev/null | head -3
```

**Meaning:** Storage kind `cosmos`. Bootstrap surfaces container and partition-key definitions from app code or Bicep/ARM templates, and emits seed in Cosmos JSON format.

---

### HTTP-only (no DB in this repo)

**Signal:** None of the above storage signals appear. The repo contains HTTP
handlers, route definitions, and possibly an OpenAPI spec, but no migration
files, no ORM dependencies, no schema files.

```bash
# Confirm no migration directories exist
find . -not -path "*/node_modules/*" -not -path "*/target/*" \
  -not -path "*/build/*" -not -path "*/vendor/*" -not -path "*/.git/*" \
  -type d \( -name "migrations" -o -name "migrate" -o -name "db" \
             -o -name "alembic" -o -name "flyway" \) \
  2>/dev/null | head -5

# Confirm no ORM deps
grep -rn --include="package.json" \
  -E '"(mongoose|sequelize|typeorm|prisma|pg|mysql2|sqlite3)"' . 2>/dev/null \
  | grep -v node_modules | head -3
grep -rn --include="requirements*.txt" --include="pyproject.toml" \
  -E '^(sqlalchemy|django|pymongo|motor|psycopg2|pymysql)' . 2>/dev/null | head -3
```

**Meaning:** Storage kind `http`. No seed step. Bootstrap focuses on startup and the upstream dependency map. Upstream deps found in env config (see the Environment Config Detection section below) may have their own storage — trace those repos separately.

---

### gRPC-only

**Signal:** `.proto` files present and a gRPC server bootstrap call exists,
but no DB drivers or migration files.

```bash
# .proto files
find . -not -path "*/node_modules/*" -not -path "*/target/*" \
  -not -path "*/build/*" -not -path "*/vendor/*" -not -path "*/.git/*" \
  -name "*.proto" \
  2>/dev/null | head -5

# gRPC server bootstrap (Go)
grep -rn --include="*.go" --exclude-dir=vendor \
  -E 'grpc\.NewServer\(' . 2>/dev/null | head -3

# gRPC server bootstrap (Java/Kotlin)
grep -rn --include="*.java" --include="*.kt" \
  --exclude-dir=target --exclude-dir=build \
  -E 'ServerBuilder|GrpcServerFactory|grpcServer' . 2>/dev/null | head -3

# gRPC server bootstrap (Node)
grep -rn --include="*.ts" --include="*.js" \
  --exclude-dir=node_modules --exclude-dir=dist \
  -E '@grpc/grpc-js|grpc\.Server' . 2>/dev/null | head -3
```

**Meaning:** Storage kind `grpc` (or `none` if combined with HTTP-only). API surface `grpc`. No SQL seed — bootstrap emits stub payloads from `.proto` message definitions.

---

### Fixture-based / In-memory

**Signal:** Test-only annotations that set up a database (`@Sql` in Spring),
factory files under `tests/factories/`, but no migration runner or persistent
storage dependency.

```bash
# Spring @Sql annotations
grep -rn --include="*.java" --include="*.kt" \
  --exclude-dir=target --exclude-dir=build \
  -E '@Sql\b' . 2>/dev/null | head -5

# Factory files (Ruby FactoryBot, Python factory_boy, JS/TS)
find . -not -path "*/node_modules/*" -not -path "*/target/*" \
  -not -path "*/build/*" -not -path "*/vendor/*" -not -path "*/.git/*" \
  \( -path "*/factories/*.rb" -o -path "*/factories/*.py" \) \
  2>/dev/null | head -5

# No Flyway, Liquibase, or Alembic (confirm absence)
find . -not -path "*/node_modules/*" -not -path "*/target/*" \
  -not -path "*/build/*" -not -path "*/vendor/*" -not -path "*/.git/*" \
  \( -name "flyway.conf" -o -name "db.changelog-*.yaml" \
     -o -name "env.py" -path "*/alembic/*" \) \
  2>/dev/null | head -3
```

**Meaning:** Storage kind `none`. No persistent seed step. The manifest configures the in-memory H2 / SQLite connection that the test harness expects.

---

## API-Type Detection

Run these before generating any manifest. Each signal determines the manifest
step type for the service's HTTP surface.

```bash
# OpenAPI/Swagger specs
find . -not -path "*/node_modules/*" -not -path "*/vendor/*" \
  -not -path "*/target/*" -not -path "*/build/*" -not -path "*/.git/*" \
  \( -name "openapi*.yaml" -o -name "openapi*.json" \
     -o -name "swagger*.yaml" -o -name "swagger*.json" \) \
  2>/dev/null | head -5

# gRPC .proto files
find . -not -path "*/node_modules/*" -not -path "*/vendor/*" \
  -not -path "*/target/*" -not -path "*/build/*" -not -path "*/.git/*" \
  -name "*.proto" \
  2>/dev/null | head -5

# GraphQL schema
find . -not -path "*/node_modules/*" -not -path "*/vendor/*" \
  -not -path "*/target/*" -not -path "*/build/*" -not -path "*/.git/*" \
  \( -name "*.graphql" -o -name "schema.graphql" \) \
  2>/dev/null | head -5

# .NET ASP.NET Core
find . -not -path "*/bin/*" -not -path "*/obj/*" -not -path "*/.git/*" \
  \( -name "*.csproj" -o -name "Program.cs" \) \
  2>/dev/null | head -5
```

**Interpret results:**

| Signal found | API surface | Manifest step type |
|---|---|---|
| `openapi*.yaml` / `swagger*.json` | REST with spec | `http` (attach spec path) |
| `.proto` files | gRPC | `grpc` |
| `*.graphql` / `schema.graphql` | GraphQL | `http` with GraphQL path |
| `.csproj` / `Program.cs` | ASP.NET Core REST | `http` |
| None of the above | Plain web app or unknown | `http` (no spec) |

If both an OpenAPI spec and `.proto` files are present, the service likely
exposes both transports (common in gRPC-gateway setups). Record both; the
manifest will have one step per transport.

---

## Auth-Signal Detection

These signals tell bootstrap that end-users must authenticate before
accessing the service's data — meaning the seed phase must include at least
one user record with valid credentials.

```bash
# C# / ASP.NET — auth middleware (exclude bin/obj)
grep -rn --include="*.cs" --exclude-dir=bin --exclude-dir=obj \
  -E "\[Authorize|AddAuthentication\(|UseAuthentication\(" \
  . 2>/dev/null | head -3

# Java / Kotlin — Spring Security (exclude target/build)
grep -rn --include="*.java" --include="*.kt" \
  --exclude-dir=target --exclude-dir=build \
  -E "@PreAuthorize|@Secured|class\s+SecurityConfig" \
  . 2>/dev/null | head -3

# Node — passport / express-jwt / jsonwebtoken / Auth0 (exclude node_modules/dist)
grep -rn --include="*.js" --include="*.ts" \
  --exclude-dir=node_modules --exclude-dir=dist \
  -E "(require|from)\s*['\"].*?(passport|express-jwt|jsonwebtoken|@auth0)" \
  . 2>/dev/null | head -3
```

**If two or more signals are found** (or one clear framework-level signal like `AddAuthentication(` or `class SecurityConfig`): auth is required. The manifest seed step must include a user row. Also surface: the login endpoint path, the expected credential fields, and any role required to reach the target data.

**Python / Ruby / Go** auth signals are not listed above — use env config (see the Environment Config Detection section below) to find JWT secrets, OAuth client IDs, or session cookie keys as auth indicators.

### Password-Storage Detection

When auth is required, also check whether the service stores passwords directly (as opposed to delegating entirely to an external IdP). A service that stores bcrypt-hashed passwords supports the simpler `usernamePassword` hawkscan auth recipe; one that only stores OAuth/OIDC subject IDs requires API-key-to-JWT exchange or a custom script recipe.

#### Step 1 — Find a password column in migrations

Look for `password`, `password_hash`, or `password_digest` column definitions in schema sources:

```bash
# Liquibase YAML changelogs
grep -rln "password\|password_hash\|password_digest" \
  --include="db.changelog-*.yaml" --include="db.changelog-*.xml" \
  --exclude-dir=target --exclude-dir=build \
  . 2>/dev/null | head -5

# Flyway versioned SQL migrations
grep -rln "password\|password_hash\|password_digest" \
  --include="V*__*.sql" \
  --exclude-dir=target --exclude-dir=build \
  . 2>/dev/null | head -5

# Prisma schema
grep -n "password\|passwordHash\|passwordDigest" \
  $(find . -name "schema.prisma" -not -path "*/node_modules/*" 2>/dev/null) 2>/dev/null | head -5

# Django / Alembic models
grep -rln "password\|password_hash" \
  --include="models.py" --include="*.py" \
  --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ \
  . 2>/dev/null | head -5
```

A hit in a `createTable` block (Liquibase) or a `CREATE TABLE` statement (Flyway) that names the table `users`, `accounts`, `credentials`, or similar confirms a local password column.

#### Step 2 — Identify the encoding mechanism

```bash
# BCrypt — Java/Kotlin Spring Security
grep -rln "BCryptPasswordEncoder\|BCrypt\.hashpw" \
  --include="*.java" --include="*.kt" \
  --exclude-dir=target --exclude-dir=build \
  . 2>/dev/null | head -5

# BCrypt — Python
grep -rln "bcrypt\.hashpw\|bcrypt\.checkpw\|from bcrypt" \
  --include="*.py" \
  --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ \
  . 2>/dev/null | head -5

# BCrypt — Node.js
grep -rln "require\(['\"]bcrypt\|from ['\"]bcrypt\|from ['\"]bcryptjs" \
  --include="*.js" --include="*.ts" \
  --exclude-dir=node_modules --exclude-dir=dist \
  . 2>/dev/null | head -5

# Argon2 — any ecosystem
grep -rln "argon2\|Argon2" \
  --exclude-dir=target --exclude-dir=build --exclude-dir=node_modules \
  --exclude-dir=.venv --exclude-dir=venv \
  . 2>/dev/null | head -5

# PBKDF2 — Django default (AbstractBaseUser / make_password)
grep -rln "make_password\|check_password\|PBKDF2PasswordHasher" \
  --include="*.py" \
  --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ \
  . 2>/dev/null | head -5
```

Combined BCrypt detection across all ecosystems:

```bash
grep -rln "BCryptPasswordEncoder\|BCrypt.hashpw\|require\(['\"]bcrypt\|from ['\"]bcrypt" \
  --exclude-dir=target --exclude-dir=build --exclude-dir=node_modules --exclude-dir=vendor \
  . 2>/dev/null | head -5
```

#### Step 3 — Mark the service and drive Phase 2

| Detection result | Action |
|---|---|
| Password column found + BCrypt encoder found | Mark service as "supports password auth". Phase 2 proposes seeding a known test password (default `ExampleSeedPass1!`). Hash is computed at emission time and embedded in the SQL literal. |
| Password column found + Argon2 or PBKDF2 | Mark service as "supports password auth (non-bcrypt)". Emit the same proposal but note the encoder so the hash is generated correctly. |
| Password column found + encoder unknown | Ask the user what encoder is used before proposing password seeding. |
| No password column (external IdP only) | Do not propose password seeding. The seed must supply an API key or OAuth credential instead. |

When a service is marked "supports password auth", Phase 2 includes the password line in the proposal dialog (see SKILL.md §2.2) and Phase 3.6 emits `TEST_PASSWORD` in `.bootstrap-credentials.env` alongside `TEST_PASS`.

---

## Environment Config Detection

Environment files contain database URLs, upstream service addresses, and
auth secrets. Read these to understand how the service is wired at runtime.

```bash
# .env family
find . -not -path "*/node_modules/*" -not -path "*/vendor/*" \
  -not -path "*/.git/*" \
  \( -name ".env" -o -name ".env.example" -o -name ".env.local" \
     -o -name ".env.test" -o -name ".env.development" \) \
  2>/dev/null | head -10

# Spring application.yml / application.properties
find . -not -path "*/target/*" -not -path "*/build/*" -not -path "*/.git/*" \
  \( -name "application.yml" -o -name "application.yaml" \
     -o -name "application.properties" \) \
  2>/dev/null | head -5

# .NET appsettings
find . -not -path "*/bin/*" -not -path "*/obj/*" -not -path "*/.git/*" \
  \( -name "appsettings.json" -o -name "appsettings.Development.json" \
     -o -name "appsettings.Test.json" \) \
  2>/dev/null | head -5

# Node config files
find . -not -path "*/node_modules/*" -not -path "*/.git/*" \
  \( -name "config.json" -o -name "config.yaml" -o -name "config.yml" \) \
  2>/dev/null | head -5

# Django settings
find . -not -path "*/.git/*" -not -path "*/__pycache__/*" \
  -not -path "*/.venv/*" -not -path "*/venv/*" \
  -name "settings.py" \
  2>/dev/null | head -5

# Rails application.rb
find . -not -path "*/.git/*" -not -path "*/tmp/*" \
  -name "application.rb" \
  2>/dev/null | head -5
```

**Extract upstream service URLs** from whatever files were found:

```bash
# Generic URL / host env var patterns
grep -rn \
  -E '(_URL|_HOST|_URI|_ENDPOINT)\s*=' \
  .env .env.example .env.local .env.test 2>/dev/null | head -20

# Spring YAML — spring.datasource and upstream service urls
grep -rn --include="application.yml" --include="application.yaml" \
  -E '(url:|service\.url:|baseUrl:|endpoint:)' \
  --exclude-dir=target --exclude-dir=build \
  . 2>/dev/null | head -10

# .NET connection strings and service URIs
grep -rn --include="appsettings*.json" \
  -E '"(ConnectionString|ServiceUrl|BaseUrl|Endpoint)"' \
  . 2>/dev/null | head -10
```

Each URL or hostname found is a candidate upstream dependency in the service
model. Cross-reference against Docker Compose service names (see the Docker
Compose Service and Port Detection section below) and the cross-repo dependency
map. See `cross-repo-deps.md` for how upstream-service references resolve to
local repo paths.

---

## Docker Compose Service and Port Detection

`docker-compose.yml` (and `compose.yaml`, `docker-compose.override.yml`) is
the most reliable source of truth for what services exist and what ports they
expose locally.

```bash
# Preferred — list services and their ports via yq
yq '.services | to_entries[] | [.key, (.value.ports // [])] | flatten' \
  docker-compose.yml 2>/dev/null

# Fallback — list top-level service names via grep
grep -E '^  [a-zA-Z0-9_-]+:' docker-compose.yml 2>/dev/null

# Fallback — extract ports blocks
grep -A2 'ports:' docker-compose.yml 2>/dev/null | grep -E '^\s+-\s+"?[0-9]'

# Check for override and alternate compose filenames
find . -maxdepth 2 -not -path "*/.git/*" \
  \( -name "docker-compose.yml" -o -name "docker-compose.yaml" \
     -o -name "compose.yml" -o -name "compose.yaml" \
     -o -name "docker-compose.override.yml" \) \
  2>/dev/null
```

**Each service in the compose file is a candidate manifest service.** Record service name, image or build context, and published ports. Services using official DB images (`postgres`, `mysql`, `mongo`) are infrastructure — no manifest entry, but they confirm the storage kind. Application services with a `build:` pointing to a subdirectory are a monorepo signal.

---

## Integration Test Fixture Detection

Integration test fixtures contain realistic, constraint-valid data — the best source of example values for seed rows. Read them; emit the minimum, not a copy.

```bash
# Spring / Java — SQL scripts loaded by @Sql or @DataJpaTest
find . -not -path "*/target/*" -not -path "*/build/*" -not -path "*/.git/*" \
  \( -path "*/src/test/resources/data.sql" \
     -o -path "*/src/test/resources/*.sql" \
     -o -path "*/src/test/resources/test-data/*" \) \
  2>/dev/null | head -10

# Python — pytest fixtures
find . -not -path "*/.venv/*" -not -path "*/venv/*" -not -path "*/.git/*" \
  \( -name "conftest.py" -o -path "*/tests/fixtures/*" \
     -o -path "*/fixtures/*.json" -o -path "*/fixtures/*.yaml" \) \
  2>/dev/null | head -10

# Ruby on Rails — FactoryBot and fixtures
find . -not -path "*/tmp/*" -not -path "*/.git/*" \
  \( -path "*/spec/factories/*.rb" -o -path "*/test/factories/*.rb" \
     -o -path "*/test/fixtures/*.yml" \) \
  2>/dev/null | head -10

# JS / TS — fixture directories
find . -not -path "*/node_modules/*" -not -path "*/dist/*" -not -path "*/.git/*" \
  \( -path "*/__fixtures__/*" -o -path "*/test/fixtures/*" \
     -o -path "*/tests/data/*" -o -path "*/fixtures/*.json" \) \
  2>/dev/null | head -10

# Go — testdata directories
find . -not -path "*/vendor/*" -not -path "*/.git/*" \
  -path "*/testdata/*" -type f \
  2>/dev/null | head -10
```

**What to do with fixtures:** Read to understand required vs. optional fields and extract realistic example values (avoid `"test"` / `"foo"` — use the fixture author's values, which are constraint-valid). Emit the minimum rows satisfying FK constraints and service startup. Do not copy fixtures wholesale — they are over-built with edge-case data the service startup does not need.

---

## What to Do When Discovery Is Ambiguous

When signals conflict (e.g., both Postgres and MySQL JDBC URLs appear) or
are absent entirely, present the user with this three-option dialog before
proceeding:

> **I couldn't determine the storage type for this service with confidence.
> Please choose one:**
>
> 1. **Tell me the storage type.** Options: Postgres, MySQL, SQLite, MongoDB,
>    DynamoDB, Cosmos, API-only (no DB in this repo).
> 2. **Tell me the path to migrations or schema I missed.** I'll re-scan
>    that path specifically.
> 3. **This service is HTTP-only and lives behind an API.** I'll skip
>    storage detection and treat it as an API facade.

Do not guess. An incorrect storage-kind assumption propagates into the
manifest and seed steps, producing commands that fail silently or corrupt
the local environment. A single clarifying question is faster than
debugging a bad manifest.

---

## Edge Cases

### Monorepos

**Signal:** A top-level directory contains per-service subdirectories, each
with their own `Dockerfile`, `package.json`, `pom.xml`, or `go.mod`.

```bash
# Find subdirectories with their own Dockerfile
find . -mindepth 2 -maxdepth 3 -not -path "*/.git/*" \
  -not -path "*/node_modules/*" -not -path "*/vendor/*" \
  -name "Dockerfile" \
  2>/dev/null | head -10

# Find subdirectories with their own package.json (excluding node_modules)
find . -mindepth 2 -maxdepth 3 -not -path "*/node_modules/*" \
  -not -path "*/.git/*" \
  -name "package.json" \
  2>/dev/null | head -10
```

**Handling:** Treat each qualifying subdirectory as its own service entry. Run the full detection suite independently in each. The top-level `docker-compose.yml` is canonical for inter-service wiring.

### Generated Code

Liquibase changelogs, Flyway copies, and protobuf stubs appear under `build/`, `target/`, or `generated/` — outputs, not sources. The standard exclusion flags cover these. For non-standard output dirs, scan `.gitignore`:

```bash
grep -E '^/?[a-zA-Z0-9_.-]+/$' .gitignore 2>/dev/null | head -10
```

Add discovered output dirs to the exclusion list before re-running detection.

### Vendored Dependencies

`vendor/` (Go), `node_modules/` (JS/TS), `target/` (Java/Kotlin), `.venv/`/`venv/` (Python) contain third-party code with their own migration files and ORM models. A false positive cascades into an incorrect storage kind and seed. Always exclude:

```bash
-not -path "*/node_modules/*"  -not -path "*/target/*"
-not -path "*/build/*"         -not -path "*/vendor/*"
-not -path "*/.git/*"          -not -path "*/.venv/*"
-not -path "*/venv/*"          -not -path "*/__pycache__/*"
-not -path "*/cdk.out/*"       -not -path "*/dist/*"
```

---

## Discovery Output

The result of all detection is an internal service model that feeds Phase 2 of the bootstrap SKILL.md workflow. Conceptual shape:

```
ServiceModel:
  name: <string>                          # service identifier (compose name or directory name)
  repo_path: <path or null>              # local clone path; null if remote-only
  storage_kind: postgres | mysql | sqlite | mongo | dynamo | cosmos | http | grpc | none
  api_surface: openapi | graphql | grpc | rest | none
  auth_signal: yes | no
  upstream_deps: [<service-name>, ...]   # other services this one calls at runtime
  env_vars_referenced: [<NAME>, ...]     # env var names found in config files
```

One `ServiceModel` per service. Monorepos get one model per subdirectory-service. The model is not persisted — if the user re-runs bootstrap after cloning a new upstream repo, discovery runs again from scratch.
