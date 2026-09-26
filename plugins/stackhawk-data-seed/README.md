# StackHawk Data Seed

This plugin teaches Claude to prepare checked-in seed data for applications that HawkScan will test. It inspects the target repository, uses `hawk perch seed` to discover storage and upstream services, and creates a manifest with the smallest useful set of seed steps. It validates and finalizes those files before presenting them for review.

The skill writes seed artifacts in the target repository. It does not run the seed steps, start services, or create `stackhawk.yml`. Review generated SQL, HTTP, gRPC, MongoDB, and shell steps before running them, and keep credentials out of checked-in files. A separate credentials handoff file is intended for local secret values.

## Requirements

Install the StackHawk `hawk` CLI with `hawk perch seed validate` and `hawk perch seed finalize` support. Invoke the skill from the repository you want to prepare for scanning.

## Install and use

In Claude Code, add the [StackHawk agent skills marketplace](https://github.com/stackhawk/agent-skills) and install `stackhawk-data-seed@stackhawk`. Ask Claude to "set up data for HawkScan" or "seed this repo for scanning". The skill runs only when you explicitly request it.

See [the skill instructions](skills/stackhawk-data-seed/SKILL.md) for the complete workflow. This plugin is released under the MIT license.
