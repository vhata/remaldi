# Decisions

## 2026-10-11: Vendor the workflow machinery under docket/

The generic workflow (contract, queue and review guides, validators) is vendored
under `docket/` by the docket skill's `install.sh` and is never edited here. It
replaces the scripts copied into `scripts/workflow/` and the guides rewritten
under `docs/`, which had drifted from the skill and received none of its fixes,
and supersedes the 2026-10-04 choice below to copy the shell tools into the
repository (its reason still holds: the installed copies run without a globally
installed skill).
`AGENTS.md` keeps only this project's settings in its marked Docket section, and
the review focus areas, baseline commands and drift checks live in
`docs/QUALITY.md`. One command installs or resyncs the whole directory and
`--check` reports drift, so a validator fix reaches this project without a hand
merge; the installed copies still run without a globally installed skill. The
cost is that a project-specific rule can no longer be written into a guide; it
goes in the Docket section or the quality doc, which the guides point to.

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
