# Promoted review work

Implementation-ready work promoted from full codebase reviews.
These entries are available for separate claims; this review does not
implement them. Follow [the review guide](../docket/CODE_REVIEW_GUIDE.md)
and [claim rules](../docket/TODO_GUIDE.md) before selection.

## Unprioritized

- [BROWSER] `exclude-known-private-ui-target` — **Keep a positively classified Private target ineligible when it becomes the only UI candidate.** The single-candidate shortcut currently discards an earlier incognito classification and can reroute default requests to the Private context.
  - Source: [2026-10-27 full review](2026-10-27-1620-full.md), 2026-10-27.
  - Starting point: `Browser._select_ui` in `remaldi/browser.py`.
  - Findings: `known-incognito-single-target-selected`
  - Acceptance: classify synthetic regular and Private UI targets, remove the
    regular one, refresh, and verify that default requests do not reach the
    known Private target. Keep the documented compatibility policy for an
    unclassified sole target explicit; cover recovery to a regular target.

- [TOOLING] `quote-current-secret-audit-paths` — **Handle valid current filenames when hashing secret-audit inputs.** Newline-containing or leading-quote paths currently crash the mandatory audit instead of being scanned.
  - Source: [2026-10-27 full review](2026-10-27-1620-full.md), 2026-10-27.
  - Starting point: `working_files` in `scripts/audit-secrets.py`.
  - Findings: `secret-audit-current-path-quoting`
  - Acceptance: audit clean and synthetic secret-bearing current files whose
    names contain newlines or begin with a double quote. Hash each exact path,
    return structured audit output, preserve finding detection, and retain
    historical-context and concurrent-cache regression coverage.
