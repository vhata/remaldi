# Review evidence and continuity

Every change needs a separate reviewer of actual changes and surrounding code;
authors own fixes, reviewers report and verify them. Record scoped PR review and
checks in the PR/conversation. Such reviews do not create permanent snapshots or
require another reviewer solely for reviewing.

## Full and incremental codebase reviews

These are separately selected tasks. Start by recording the reviewed revision and
reading scope/contracts. A full review inspects maintained code, tests, and relevant
configuration, dividing independent areas where practical. Baseline checks support
inspection; reproduce serious failures where possible and distinguish executed
evidence from reading or unavailable tools.

An incremental review starts from the latest snapshot revision. Recheck every
standing finding and claimed fix; rerun original reproductions before marking
Fixed. Inspect the entire delta and cross-module effects and broaden checks only
as risk warrants. Use a full review after major structural change or proven drift.

Write `review/YYYY-MM-DD-HHMM-full.md` or `-incremental.md` using UTC. Include type,
reviewed revision, previous review/revision, commands/results, scope/invariants,
findings with evidence, backlog mappings or inventory-only reasons, suggested
order, and verification limits. Index newest first in review/README.md with type,
revision, and unresolved count. The newest snapshot is current inventory.
Once merged, historical snapshots are immutable except factual corrections.

## Findings and promotion

Each independently fixable finding has a stable ID, current path/line/symbol,
evidence-based severity, failure scenario/impact, reproduction or inspection
evidence, suggested bounded correction, and disposition/mapping.

States are Open, Moved (still unresolved), Fixed, Accepted, Invalid, and Superseded.
Non-open states require evidence: fix revision/current location and independent
verification, acceptance rationale, invalidating evidence, or replacement ID.
Carry IDs forward as code moves; keep original IDs and evidence on closed entries.

Every unresolved finding must map to existing promoted work, be promoted as a
coherent ready item, or remain inventory-only with an explicit reason. One finding
maps to at most one backlog item. Promotion is scheduling, not authorization to
implement all findings; ordinary feature discoveries stay in TODO.

Promoted backlog entries list area, stable task ID, priority (default Unprioritized),
bounded outcome, source snapshot, `Findings:` IDs, dependencies, and verification.
They are ready work, without TODO's triage/prototype stages.

## Closure

A fix supplies a human-runnable scenario: setup, action, old failure, expected
behavior, actual checks, and limits. Independent PR review verifies the correction
before readiness; applicable claim/resolution markers follow the TODO guide.
A subsequent independent incremental review confirms historical closure by
inspecting current code and rerunning the original executed reproduction. Merge
alone does not close a historical finding. If verification fails or is unavailable,
keep the finding Open/Moved and restore/update mappings rather than claiming closure.
