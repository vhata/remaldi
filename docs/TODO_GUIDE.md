# Selecting and resolving work

TODO is the authoritative queue for ordinary discoveries, including bugs found
during feature work. Whole-codebase review findings are separate evidence; only
deliberately promoted findings belong in [review/BACKLOG.md](../review/BACKLOG.md).
Do not create parallel issue and Markdown queues for the same tasks.

## Readiness and entry format

Needs triage means the outcome/dependencies are unclear. Needs proof of concept
means a bounded experiment must establish an implementable contract. Ready for
separate work means the outcome and verification are understood and unblocked.
An unresolved queue dependency or external blocker keeps the task in Needs triage
or Needs proof of concept. Ready does not itself grant assignment or authorization.
Move entries between stages without changing their stable ID.

Use P0 Critical only for evidence-backed active security/data-loss/release blockers;
other priorities are P1 High, P2 Normal, P3 Low, and Unprioritized. New discoveries
default to Unprioritized unless the user assigned a priority.

Each entry needs area, unique stable slug, concrete outcome/why, source/date,
starting point, dependencies, and an acceptance condition. Search before adding.
Record independently shippable discoveries here and continue the selected task.

## Ownership and selection

Direct user requests need no invented queue entry. Otherwise follow the selected
queue and priority; do not replace ready implementation with triage/prototype work
or select another queue because the requested queue is empty.

Search exact task/finding IDs and titles across open PRs, remote branches, local
branches, and worktrees before claiming work, then recheck before publication.
Matching worktrees are provisional claims. Resolve overlaps rather than racing.
For this repo, open PR bodies are the authoritative shared claim mechanism:
include the named owner, exact scope, dependencies, and applicable markers. A
local branch alone is not a globally visible claim. If GitHub is unavailable,
retain the queue entry and disclose the visibility/publication limitation.

Use a dedicated branch and worktree for every task; concurrent writers have
disjoint ownership. After the
first meaningful commit publish a draft PR; keep source entries while work is
underway. Small factual doc corrections may use proportionate review/checks.
Abandoned work releases its claim and retains/restores its queue entry.

## PR markers and resolution

Use only applicable exact markers, with stable IDs:

```text
Claims TODO: <task-id>
Claims review backlog: <backlog-id>
Claims review finding: <finding-id>
```

A promoted review batch claims its backlog ID and every finding in scope. Explicitly
assigned raw-finding work may claim only that finding, explaining the exception.

After verifying the complete outcome and independent review, remove the fully
resolved mutable queue entry, repair references, and change Claims to Resolves:

```text
Resolves TODO: <task-id>
Resolves review backlog: <backlog-id>
Resolves review finding: <finding-id>
```

For partial completion replace the original scheduling entry with one assessed
remainder using a new ID, `Remaining from: <original-id>`, and retained unresolved
finding IDs. Use paired `Partially resolves TODO: <original-id>` / `Remaining TODO:
<new-id>` markers (or the same pair for `review backlog`). Report the actual remainder.
Rejected/obsolete work needs an evidence-backed reason in the removing PR.

Before parallel subsets claim work, land an authoritative queue-only split: retain
the original ID on one subset and give others new IDs with `Split from`. Drafting
the split is insufficient. If landing needs the user, leave subset claims pending.

Ready PRs have complete implementation, relevant checks, and independent review
with no unresolved actionable findings. Mark them ready, but do not merge without
user delegation. If gates fail later, restore draft and the appropriate queue/claim
mapping. Implementation resolution does not rewrite historical review snapshots.

Use one exact marker per line, without backticks or trailing explanations. Filed
discoveries use `Files TODO: <slug>`. Run
`bash scripts/workflow/check-pr-markers.sh --body <file>` before publication;
CI validates the body against base/head queues. The installed tools implement
claim discovery, branch/worktree creation, queue validation and cleanup so workers
without the global skill use the same process.

Entry areas are `[BROWSER]`, `[STATE]`, `[ACCEPTANCE]`, `[CLIENT]`, `[SERVICE]`,
`[TRANSPORT]`, `[TOOLING]`, and `[DOCS]`. Use ``Depends on: `slug` `` only for
unresolved queued work and `Blocked by:` for external conditions. Stable slugs and
Source lines survive moves. Run `bash scripts/workflow/check-queues.sh --strict`
after editing either queue. Once a blocker clears, drop the line and reassess
readiness; preserve acceptance conditions when splitting or partially resolving.
