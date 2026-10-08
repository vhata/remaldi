# Working on Remaldi

- Follow the user's selected task and [SPEC.md](SPEC.md). Keep independently
  shippable discoveries out of its implementation; record them in [TODO.md](TODO.md).
- Respect [ARCHITECTURE.md](ARCHITECTURE.md). Never launch or restart the browser,
  replay uncertain commands, or publish credentials or private browser captures.
- Before selecting work, inspect TODO readiness, review mappings, open PRs,
  remote branches, and worktrees. Draft PRs are shared active claims; an empty
  local queue does not prove nobody is working. Disclose unavailable visibility.
- Give each task one named owner and a dedicated branch. Parallelize independent
  work where practical; concurrent writers use isolated worktrees. The coordinator
  owns integration and shared interfaces. Follow [the TODO guide](docs/TODO_GUIDE.md)
  for exact claim/resolution markers, dependencies, and partial completion.
- Authors fix findings; separate reviewers inspect actual changes and verify
  fixes before readiness. Self-review and automated checks do not replace review.
  Follow [the review guide](docs/CODE_REVIEW_GUIDE.md); routine PR reviews do not
  create permanent codebase-review snapshots.
- Keep PRs draft until implementation, relevant [checks](docs/QUALITY.md), and
  independent review are complete. Then mark ready without waiting for approval.
  Return to draft if a gate becomes incomplete. The user owns final review,
  merges, releases, and tags unless explicitly delegated.
- Use focused commits with lasting problem/result/validation descriptions.
  Preserve unrelated changes and historical commits. Report actual checks,
  limitations, active ownership, and unresolved work.

Python setup and executable quality gates live in [docs/QUALITY.md](docs/QUALITY.md).

## Local workflow entrypoints

- Every task uses one branch and one worktree, including solo work. New branches
  use `todo/<slug>`, `review/<slug>`, or `fix/<slug>` for direct requests.
  Worktrees live in ignored `.worktrees/`.
- Run `bash scripts/workflow/claim-check.sh <slug>` before claiming, then
  `bash scripts/workflow/start-work.sh <queue> <slug>`. Coordinate any hit.
- PR bodies open with `## Why` and record scope, markers, validation, and
  `## Review` naming reviewer, exact reviewed revision, findings and dispositions.
  If GitHub is unavailable, save `.feral/pr-<slug>.md` and disclose a local claim.
- No direct-to-main exceptions. Rebase rather than merge main into task branches.
  The user lands by squash; retain the PR title/body as the lasting explanation.
  Never merge, release, tag, deploy or change hosting settings without delegation.
- Interactive branch pushes and draft PRs are normal task work. Unattended runs
  stay local unless push authority is explicit; log decisions and undo instructions
  in ignored `AUDIT.md`. Do not discard dirty worktrees or unmerged branches.
- Parallel writers have disjoint ownership; the coordinator serializes queue edits.
  Cap concurrent heavy checks at two. Independent reviewers report findings;
  authors fix, reviewers verify subsequent changes. Return a PR to draft if its
  checks or review become incomplete.
- Use `/Users/jonathan.hitchcock/.venv/3.12/bin/python` locally. CI and managed
  hooks use Python 3.12 in their own environments. `scripts/setup.sh` installs
  dependencies/hooks; `scripts/check.sh` is the shared gate.
- The review ledger is installed but has no baseline until a separately requested
  codebase review. Scheduled validation and both queues are in force. Stacks are
  optional; an unlanded parent prevents landing, not completion of scoped review.
- Read [docs/DECISIONS.md](docs/DECISIONS.md) before changing a non-obvious choice.
