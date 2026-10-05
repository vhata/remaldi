# Decisions

## 2026-10-04: Extend the existing setup PR

PR #1 already owns repository workflow setup. Continue `workflow-foundation`
in its isolated worktree rather than creating an overlapping claim. Preserve
its existing commit and deferred browser work. Main remains the user's landing
responsibility. The shell workflow tools are copied into the repository so
contributors need no globally installed skill.

## 2026-10-04: Keep existing quality tooling

Keep pre-commit, Ruff, strict mypy, unittest, and secret auditing. Add workflow
record checks to the same entrypoint and manager. Explicitly reject empty test
collection because unittest otherwise succeeds with zero tests. Python 3.12 is
the development/CI contract; local setup uses the user's installed environment,
while CI and hooks provision their own. No live browser scenario runs unattended.

## 2026-10-04: Ready means unblocked

The user chose repo-workflow's unblocked Ready policy over the earlier guide's
blocked-Ready convention. Move both live browser acceptance tasks to Needs triage
with explicit external blockers, preserving their slugs, sources, and acceptance
criteria. This exposes the actual availability boundary without assigning those
tasks or authorizing visible browser changes.
