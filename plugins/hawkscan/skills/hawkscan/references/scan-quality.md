# Scan Quality Reference

Run this gate after **every** scan — full scans and rescans alike — before findings are
parsed into fix tasks (SKILL.md calls it Step 4.5, sitting between Step 3's scan run and
Step 4's fix-task generation). It is a feedback loop into config tuning, **not a governor**:
gate state never blocks a finding from being reported and fixed. A thin scan that only
reached a fraction of the surface can still have found something real, and that finding
gets fixed now, regardless of what the gate says. The gate's job is narrower: notice when a
scan almost certainly missed API surface, and drive a bounded, additive config fix so the
*next* scan reaches more of it.

The gate derives its expectation fresh every time it runs. There is no persisted plan or
prior-run state to compare against — recompute the expected surface from the repo and the
effective config each time, the same way discovery would if run again right now.

**Multi-config execution.** When a repo has more than one `stackhawk.yml` surface (discovery
writes one config per surface, ordered by DAST value — primary or backing API first, a SPA
frontend last), scan and gate **sequentially**, one config at a time, in that same
value order. Gate immediately after each config's scan rather than batching every scan
first and gating afterward — an auth-wall caught and fixed on config 1 saves the identical
wasted scan on config 2. The iteration caps described below (2 interactive / 1 autonomous)
apply **per config**, not to the run as a whole. The autonomous post-code-change loop scans
only the config(s) whose surface the change touched — that scan must still cover that
surface's entire scope (the fix-ALL-findings rule from Step 4 is unchanged) — defaulting to
the primary surface's config when it's unclear which surface a change touched. A full sweep
across every config is an interactive operation only; never trigger one autonomously.

## Contents
- [Derive the expectation (fresh, every scan)](#derive-the-expectation-fresh-every-scan)
- [The five checks](#the-five-checks)
- [On gaps: iterate the config](#on-gaps-iterate-the-config)
- [Reporting rules](#reporting-rules)
- [Degradation](#degradation)

---

## Derive the expectation (fresh, every scan)

Before you can tell whether a scan under-covered its target, you need something to compare
it against. Build that expectation the same way every time, right after the scan finishes:

- **Spec wired** (`openApiConf`, `graphqlConf`, `grpcConf`, `soapConf`): the expectation is
  the paths or operations the spec declares. `hawk op scan uris <scanId> --format json` is
  config-aware — it reads the effective scan config and automatically fetches
  graphql-operations or jsonrpc-methods when `graphqlConf` or `jsonRpcConf` is present in
  that config (force either with `--graphql` / `--jsonrpc` if auto-detection misses it).
  That gives you the real scanned-URI set to diff against the spec's declared set.
- **No spec wired**: re-derive the expected route inventory using the same per-framework
  route greps as the discovery reference (`scan-planning.md`) — the same detection
  heuristics, the same counting technique, run fresh against the current code, not carried
  over from whatever discovery counted last time. Code changes between scans; the
  expectation should too.
- **Spec-less apps that keep coming up short**: if the grepped expectation and the scanned
  URIs repeatedly diverge because there's nothing authoritative to wire, that's a signal to
  recommend generating a spec — the same code-change recommendations discovery makes
  (`scan-planning.md`'s "Recommend code changes for gaps" section: `springdoc-openapi` for
  Spring, `swagger-jsdoc`/`@nestjs/swagger` for Node, `drf-yasg`/`drf-spectacular` for
  Django REST Framework, `swashbuckle` for .NET). Surface the recommendation; don't apply it
  unrequested.
- `hawk op scan uris` and `hawk op scan config` ship with the combined `hawk` CLI the
  preflight already requires. If either subcommand errors or isn't recognized on the
  installed CLI, fall back per the Degradation section below — detect it by the command
  failing, don't ask the user which version they have.

Because the no-spec expectation is re-derived with the **same** per-framework greps discovery
uses, the gate inherits discovery's blind spots: a surface neither discovery nor this
re-derivation detects (a second gRPC service, a dynamically-mounted router) won't be flagged
as unscanned — the gate can't miss-diff against a surface it never counted. This is why the
user-confirmed discovery summary (`scan-planning.md`) is the real backstop for surface
completeness, not the gate alone.

## The five checks

Run all five after every scan. Each has its own command, pass condition, and a stable
reason identifier used when reporting a gap — this gate's own reporting (Step 4.5 in
SKILL.md) uses these identifiers directly, so keep them exactly as written here across any
edits to this file: `coverage-gap`, `spec-not-wired`, `surface-unscanned`,
`auth-validate-failed`, `auth-wall`, `all-4xx`, `base-path-mismatch`, `env-unreachable`.

| # | Check | What it measures | Command(s) | Pass condition | Reason identifier(s) |
|---|-------|-------------------|------------|-----------------|------------------------|
| 1 | Coverage | Scanned URIs vs. the expectation derived above | `hawk op scan uris <scanId> --format json` diffed against the expectation list | **Never fails the gate.** Always computed and reported as evidence, e.g. "14 of 41 planned routes untouched," with the untouched routes listed | `coverage-gap` (evidence only) |
| 1b | Base-path resolve | Whether spec-derived paths actually resolve against the app, or systematically 404 because the config and spec disagree on the base/context path | In the scanned-URI list, look for the same route appearing both prefixed and un-prefixed (e.g. `/api/v1/authors` **and** bare `/authors`), or a cluster of spec paths all 404 while a prefixed variant succeeds; confirm with a curl of `host + spec-path` vs the prefixed variant | No systematic base-path 404 pattern — spec paths resolve to real routes. This **does** fail the gate (structural). Fix per `openapi-specs.md` "Base path and context path" | `base-path-mismatch` |
| 2 | Auth | Live auth validation before the scan; auth-wall signals during it | `hawk validate auth <surface config>.yml` pre-scan (against the config being gated — repos with multiple per-surface configs validate each one); `hawk op scan metrics <scanId>` for auth-wall flags | `validate auth` exited 0, and no auth-wall flag on any surface that has `authentication:` configured | `auth-validate-failed`, `auth-wall` |
| 3 | Surface-completeness | Every surface discovery found has a config, that config actually ran, and any spec found for it is wired into that config | `hawk op scan config <scanId>` (effective config the scan ran with); fall back to reading the local `.yml` files | Every discovered surface maps to a config that exists, ran this scan, and has its spec wired if one exists | `surface-unscanned`, `spec-not-wired` |
| 4 | Health | Connection-failure spikes, timeout streaks, app unreachable mid-scan; all-4xx response patterns on a configured surface | `hawk op scan metrics <scanId>` for flags; `hawk op scan get <scanId>` for `url_count` and status summary | No connection-failure spike, no timeout streak, no mid-scan unreachability, and no configured surface returning all 4xx | `env-unreachable`, `all-4xx` |

**Signal classes.** Every non-evidence gap above is either config-class or environment-class
— the class decides what you're allowed to do about it:

- **Config-class** — `spec-not-wired`, `surface-unscanned`, `auth-validate-failed` (the fix
  lives in the config's `authentication:` block), `auth-wall` while the app is demonstrably
  up, `all-4xx` on a configured surface (this is usually auth-shaped: the surface is
  reachable but every request is being rejected), and `base-path-mismatch` (the fix is
  aligning `app.host` and the spec's base/context path — `openapi-specs.md`). These route
  into the normal bounded config iteration described below.
- **Environment-class** — `env-unreachable`, covering connection-failure spikes, timeout
  streaks, and the app going unreachable mid-scan. **Never touch the config for these.**
  Verify the app is up using the same playbook as SKILL.md's Step 1c / Step 6 exit-1
  diagnosis, restart or wait if needed, then retry the scan once — that retry does not
  consume a config-iteration. If the same environment-class signal recurs on the retry,
  report it as an environment problem and stop; do not keep retrying and do not reach for a
  config edit to work around it.

Performance signals — slow paths, rate-limited endpoints, a scan that ran long — are not a
gate concern at all. They route to the `optimize` skill's existing suggestion path (SKILL.md
Step 4, surfaced once per session for full scans ≥ 20 minutes), never to this gate.

## On gaps: iterate the config

When one or more config-class gaps are open, loop back to SKILL.md's Step 2b (tune existing
`stackhawk.yml`) with this shape:

- **Batch, then rescan once.** Collect every gate-named fix from this scan's gap set — wire
  the missing spec, enable `hawk.spider.ajax`, fix the `authentication:` block, add a config
  for an unscanned surface — into a single edit pass. Rescan once after applying all of
  them together. Don't rescan after each individual fix; that wastes scans the gate exists
  to save.
- **Only iterate when the config actually changed.** If a reported gap has no config-level
  fix — a monorepo slice with no visibility into the missing service, dynamic routing that
  needs a code change, a spec that genuinely doesn't exist yet — report it and move on.
  Don't burn an iteration re-scanning a config you didn't touch.
- **Iteration cap: 2 interactive, 1 autonomous — per config, and counted in rescans, not
  edits.** A batch of five config edits followed by one rescan is one iteration. This
  matches the Autonomous Security Loop's existing guard rail of at most one fix-rescan cycle
  when running unattended.
- **At the cap, stop.** Report the remaining structural gaps by reason identifier, the
  coverage route-diff evidence (the untouched-route list from check 1), and concrete next
  steps — including any code-change recommendations discovery would make for surfaces that
  can't be closed by config alone. Never claim the scan is done, or the app is secure, while
  gaps remain open at the cap.
- **A severe coverage gap with all four structural checks green** is not a config-iteration
  target — it means the scan reached everything it was told to reach and still found little.
  Route it to SKILL.md's Step 6 empty-data handling instead: suggest the
  `stackhawk-data-seed` skill rather than continuing to edit the scan config.

**Additive-only.** Every fix applied during iteration must add coverage: wire a spec, turn
on the Ajax Spider, correct an auth recipe, add a missing surface's config. Iteration must
**never** widen `excludePaths`, raise `failureThreshold`, add `excludePlugins`, or otherwise
weaken the scan so it happens to pass the gate. If the only way to close a gap is to reduce
what gets scanned, that is not a pass — report the honest gap instead of manufacturing a
clean one.

Environment-class gaps never enter this loop at all — see the Signal classes note above:
verify the app, retry once for free, and stop if it recurs.

## Reporting rules

- **Findings are always reported and always fixable**, independent of gate state. The gate
  never withholds, delays, or downgrades a finding — a scan that under-covered the surface
  can still have found a real, exploitable bug, and that bug gets fixed on this pass.
- **Never say the scan is "done and secure"** (or any equivalent framing) while a
  config-class or environment-class gap is still open. Say plainly what was scanned, what
  wasn't, and why — the reason identifiers exist so this statement is specific, not vague.
- **The autonomous post-code-change loop reports gate gaps rather than treating exit 0 as
  success.** It runs this gate after its scan, and if gaps remain once the autonomous
  iteration cap (1) is reached, it reports them explicitly — reason identifiers, coverage
  route-diff evidence, and next steps — instead of accepting a clean exit code at face value.
- **Performance-class signals are never gate gaps.** If health metrics point at slowness
  rather than unreachability or all-4xx, that's an `optimize` suggestion, not a quality-gate
  reason identifier.
- Keep every reported gap tied to one of the eight reason identifiers above so this gate's
  own reporting stays specific rather than parsing prose — the identifiers must stay stable
  across edits to this file.

## Degradation

`hawk op scan uris` and `hawk op scan config` ship with the combined `hawk` CLI. If either
subcommand errors or isn't recognized on the installed CLI, degrade silently and keep going —
detect it by the command failing, don't ask the user to check their version:

- **Coverage (check 1)** degrades from a full scanned-vs-expected route diff to a single
  before/after number: `url_count` from `hawk op scan get <scanId>`. You lose the
  untouched-route list; still report the number as evidence, just note it's coarser.
- **Surface-completeness (check 3)** degrades from reading the effective scan config via
  `hawk op scan config` to local signals: read the per-surface `.yml` files directly to
  confirm a surface's config exists and its spec block is present, and use the
  `hawk validate config` output for each file to confirm the config is structurally sound.
- **Auth and health (checks 2 and 4)** are unaffected — `hawk op scan metrics` and
  `hawk validate auth` remain the primary signal either way.

`hawk op scan stats` does not exist yet (it's a follow-up ticket) but will eventually add
measured, per-path engine statistics rather than the grep- and `url_count`-based estimates
this reference relies on today. When it ships, prefer its measured signal over the inferred
approach described here. Until then, its absence is expected — degrade silently and don't
block or warn on it being missing.
