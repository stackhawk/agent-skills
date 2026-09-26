# StackHawk Wingman

Wingman is a convenience plugin for Claude Code users who want the default StackHawk skill set in one install. Its manifest declares dependencies on HawkScan, StackHawk API, StackHawk Data Seed, and StackHawk Optimize. Those plugins handle DAST scanning, security reporting, scan data preparation, and setup trials respectively.

Wingman contains no standalone skill in its own `skills/` directory. Claude Code installs and enables the four dependent plugins when you install `wingman@stackhawk` from the [StackHawk agent skills marketplace](https://github.com/stackhawk/agent-skills). Each dependency has its own requirements and instructions. The plugins use the StackHawk `hawk` CLI and may call StackHawk services or scan a target application when you invoke their skills. Review each plugin's README and skill instructions before use.

For Claude chat or Cowork, install the individual skill plugins directly so their skills are available on those surfaces. The dependency bundle is intended for Claude Code. Wingman is released under the MIT license.
