# Repository instructions

This repository contains reusable, user-level tools for coding agents and humans.

- Keep scripts cross-platform, idempotent, and safe to rerun.
- Never commit credentials, tokens, private source material, `.venv/`, caches, or downloaded binaries.
- Prefer official platform package managers for native programs and `uv` for Python environments.
- Do not silently alter a user's shell profile, user `PATH`, or system packages. Require an explicit flag and report every change.
- Pin or constrain dependencies deliberately; review upgrades before changing them.
- Put portable Python code in `src/agent_tools/`, launchers in `bin/`, platform automation in `scripts/`, and configuration in `config/`.
- Preserve compatibility with Windows PowerShell 7+, Linux, and macOS. Where behavior differs, document and test the difference.
- Downloads outside package managers must use official HTTPS sources and verify a published checksum or signature.
- Prefer additive, reviewable changes. Do not overwrite user configuration without a backup and explicit authorization.
- Run `python -m unittest discover -s tests`, the platform script syntax checks, and `agent-tools doctor` when relevant.
- Bound Windows CI steps that invoke native-tool installers with explicit timeouts. After inspecting a failure, retry the same head at most once; never push an empty or unrelated commit merely to retrigger CI.
- Read `docs/plan/00-index.md` before planning roadmap work. Keep its status, effort forecast, evidence links, and corresponding GitHub milestone current in the same change that advances a milestone.
- For non-trivial work, identify the milestone and acceptance criterion, write a task plan with estimated effort before implementation, and report completed work, validation, changed estimates, and the recommended next task afterward.
- Mark roadmap criteria complete only with durable evidence such as a merged change, passing test, published artifact, or release. Do not infer completion from prose or issue counts. When the final criterion completes, reconcile remaining issues and explicitly close the GitHub milestone.
- Follow [`docs/development-workflow.md`](docs/development-workflow.md) for branch, pull-request, review, and merge work. Merge evidence must apply to the exact current head, concurrent autonomous streams must serialize integration through one merge owner, and pre-existing repository or user state must be preserved.
- Respect any more-specific `AGENTS.md` in subdirectories.
