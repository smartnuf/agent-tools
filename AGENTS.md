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
- Respect any more-specific `AGENTS.md` in subdirectories.
