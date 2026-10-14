# Working on Remaldi

Remaldi is a local control client and on-demand daemon for an already-running
Vivaldi browser. Follow the user's selected task, [SPEC.md](SPEC.md) and
[ARCHITECTURE.md](ARCHITECTURE.md); never describe an unsupported or unverified
capability as delivered browser behaviour.

<!-- docket:begin -->

## Docket

This project is run with docket. Read [docket/CONTRACT.md](docket/CONTRACT.md) before any work; it is the authoritative workflow, and this section records only this project's settings. The installer keeps this section current: the text above the list is rewritten on every run, the list keeps the values this project has set, and the section may sit anywhere in this file.

- Queue areas: `[BROWSER]` (target discovery, connections and reconnection; `browser.py`), `[STATE]` (snapshots, capabilities and event invalidation; `adapter.py`), `[ACCEPTANCE]` (live browser acceptance scenarios), `[CLIENT]` (CLI and socket client; `__main__.py`, `client.py`), `[SERVICE]` (operation registry, runtime paths and locks; `service.py`, `runtime.py`), `[TRANSPORT]` (DevTools request correlation and event routing; `transport.py`), `[TOOLING]` (scripts, hooks, CI, dependencies), `[DOCS]`.
- Concurrency cap: 2 heavy checks (full `scripts/check.sh` runs or package builds) at once.
- Merging and releases: the user owns final review, merges, releases, tags, deploys and hosting settings unless they delegate one explicitly in that turn. There is no standing delegation.
- Optional pieces in force: both queues (no roadmap queue), the review ledger (installed, with no baseline until a separately requested codebase review), scheduled validation of `main`, and stacked PRs when needed; an unlanded parent prevents landing, not completion of the child's own checks and review.
- Environment: never launch or restart the browser, never replay a command whose outcome is uncertain, and never publish credentials or private browser captures (tab titles, URLs, workspace names, profile data) in PRs, evidence or commits. Live browser scenarios run only when the user selects and authorises one, against a debug-enabled browser the user is already running; see [docs/QUALITY.md](docs/QUALITY.md#live-browser-acceptance). uv manages the project's own `.venv` from `uv.lock` with the Python 3.12 that `.python-version` pins, locally, in CI and in the hooks; run tools with `uv run --locked`. `scripts/setup.sh` installs dependencies and hooks and `scripts/check.sh` is the shared gate.
- Commits: bodies record the problem, the result and the validation. Preserve unrelated changes and historical commits. No generated-with footers.
- Reports: name active ownership and claims alongside the checks run.

<!-- docket:end -->

## Where to find what

- `README.md`: running the client, state and protocol, development setup.
- `SPEC.md`: accepted scope, evidence boundaries, remaining acceptance.
- `ARCHITECTURE.md`: boundaries, interfaces and ownership, failure and acceptance invariants.
- `docs/DECISIONS.md`: non-obvious choices and their trade-offs. Read before changing one.
- `docs/QUALITY.md`: Python setup, the gates, evidence boundaries, live browser acceptance, CI and hosting, and the review inputs.
- `TODO.md`, `review/`: deferred work and the review ledger.
