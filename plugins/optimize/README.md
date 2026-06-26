# StackHawk Optimize Skill

`/optimize` analyzes your codebase and produces an optimal HawkScan setup — tech flags,
scan-policy plugin selection, and `stackhawk.yml` corrections — then applies it as a
non-destructive **trial** (an isolated org scan policy), runs one trial scan, and lets you
**promote** the setup or **discard** it with no residue.

See `skills/optimize/SKILL.md` and its `references/` for the full workflow.

Requires an onboarded StackHawk app + env and a `hawkop` build that includes the
`policy create/get/delete` commands.
