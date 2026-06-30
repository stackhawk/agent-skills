# HawkScan CI Skill

Wire HawkScan DAST scanning into your CI/CD pipeline — provider-agnostic, edits the pipeline file in place, builds on the local-scan path the `hawkscan` skill owns.

## What This Does

This skill graduates a working *local* HawkScan setup (`stackhawk.yml` exists and validates) into a CI/CD pipeline. It:

1. Detects your CI provider from repo files (`.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, `.circleci/config.yml`, etc.).
2. Asks how the scan should run — trigger (PRs / push / schedule), blocking behavior (fail on findings or warn-only), job placement (chained after build or standalone).
3. Prompts you for where `HAWK_API_KEY` lives — your CI's native secrets engine (default) or an organizationally-approved external secrets manager (Vault, AWS/GCP/Azure secret managers, 1Password, Doppler).
4. Picks the right execution shape — the `stackhawk/hawkscan-action` GitHub Action where available, the `stackhawk/hawkscan` Docker image elsewhere, or the bare `hawk` CLI as a fallback.
5. Writes or patches the workflow file with a HawkScan job that exports `COMMIT_SHA` and `BRANCH_NAME` for traceability, runs the scan, handles the exit code per your choice, and uploads the scan artifact.
6. Tells you the out-of-band steps still needed — setting the secret in the provider UI/CLI, updating branch protection if the job should be a required check.

## What This Does NOT Do

- Generate `stackhawk.yml` — that's the `hawkscan` skill's surface. If config is missing, this skill hands off.
- Pick auth recipes, parse findings, triage results — all covered by the `hawkscan` skill.
- Trigger the pipeline. You own the merge story.
- Autonomous activation. Editing workflow files is invasive (CODEOWNERS, branch protection, out-of-band secret setup). Trigger this skill only by explicit request.

## Prerequisites

- A working local HawkScan setup — `stackhawk.yml` at repo root, `hawk validate config` passing, real `applicationId` (not a placeholder). If you don't have this yet, run the `hawkscan` skill first.
- The `hawk` CLI installed (v6.0.0+). The skill calls `hawk config show` and `hawk validate config`.
- Access to your CI provider's secret store, or an external secrets manager your org approves.

## Installation

```bash
# Add the StackHawk marketplace
/plugin marketplace add stackhawk/agent-skills

# Install the CI skill
/plugin install hawkscan-ci@stackhawk
```

## Usage

Once installed, the skill triggers on phrases like:

> "set up hawkscan in CI"

> "add stackhawk to my pipeline"

> "configure github actions for hawkscan"

> "wire hawkscan into ci/cd"

It will prompt you with three planning questions (trigger / blocking / placement), one secret-storage question, then write the workflow and show you the diff.

## See Also

- [`hawkscan` skill](../hawkscan/) — local DAST scanning, `stackhawk.yml` generation, findings fix loop.
- [`api` skill](../api/) — StackHawk platform API queries (findings reporting, posture summaries).
- [StackHawk CI/CD docs](https://docs.stackhawk.com/integrations/ci-cd/) — per-provider canonical references.
