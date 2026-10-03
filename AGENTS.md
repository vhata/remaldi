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
