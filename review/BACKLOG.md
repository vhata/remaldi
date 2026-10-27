# Promoted review work

Implementation-ready work promoted from the first full codebase review.
These entries are available for separate claims; this review does not
implement them. Follow [the review guide](../docket/CODE_REVIEW_GUIDE.md)
and [claim rules](../docket/TODO_GUIDE.md) before selection.

## Unprioritized

- [BROWSER] `reject-empty-explicit-target` — **Reject an empty explicit target instead of dispatching to the UI.** Default target selection must distinguish omission from an invalid explicit ID.
  - Source: [full review, 2026-10-24](2026-10-24-0249-full.md).
  - Findings: `empty-explicit-target-defaults-to-ui`
  - Starting point: `Browser.request` in `remaldi/browser.py` and raw parameter validation in `remaldi/service.py`.
  - Acceptance: a fake-server request with `target: ""` returns a structured error with no transmitted DevTools request; omitted target still selects the UI.

- [TOOLING] `publish-audit-cache-concurrently` — **Publish clean secret-audit caches safely across simultaneous worktrees.** A fixed shared temporary filename currently makes one clean audit fail.
  - Source: [full review, 2026-10-24](2026-10-24-0249-full.md).
  - Findings: `secret-cache-shared-temporary-file`
  - Starting point: cache publication at the end of `main` in `scripts/audit-secrets.py`.
  - Acceptance: synchronize two audit processes at cache publication in a disposable repository; both exit successfully and the final cache contains only complete clean entries.
