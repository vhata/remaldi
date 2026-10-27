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

- [TOOLING] `scan-history-without-filename-blind-spots` — **Scan historical content without losing relevant filename contexts.** A rename to a filename excluded by detect-secrets must not hide content previously committed under a scanned name.
  - Source: [full review, 2026-10-24](2026-10-24-0249-full.md).
  - Findings: `historical-secret-filename-suppression`
  - Starting point: `history_blobs` and historical temporary-file naming in `scripts/audit-secrets.py`.
  - Acceptance: a synthetic keyword fixture committed as `config.py`, renamed to `poetry.lock` and deleted is detected by a cold audit; no credential values are printed.

- [SERVICE] `normalize-runtime-directory` — **Use the same absolute runtime path in the client and detached daemon.** Relative overrides currently split socket and lock ownership after the child's working-directory change.
  - Source: [full review, 2026-10-24](2026-10-24-0249-full.md).
  - Findings: `relative-runtime-splits-client-daemon`
  - Starting point: `runtime_dir` in `remaldi/runtime.py` and `start_service` in `remaldi/client.py`.
  - Acceptance: first-use startup from outside the package root with a relative runtime override reaches one daemon at the intended path; status/stop reuse it and absolute socket length is validated.

- [TOOLING] `publish-audit-cache-concurrently` — **Publish clean secret-audit caches safely across simultaneous worktrees.** A fixed shared temporary filename currently makes one clean audit fail.
  - Source: [full review, 2026-10-24](2026-10-24-0249-full.md).
  - Findings: `secret-cache-shared-temporary-file`
  - Starting point: cache publication at the end of `main` in `scripts/audit-secrets.py`.
  - Acceptance: synchronize two audit processes at cache publication in a disposable repository; both exit successfully and the final cache contains only complete clean entries.
