# Product and infra development

Read `docs/product-infra-development.md` before changing module boundaries or development profiles.

- Work on one short-lived branch in one checkout. Product and infra chats use separate worktrees, virtual environments, ports and `.local/` databases. Start new features from updated `origin/main`.
- Product owns categories, product sessions, graphs and editable documents. Runtime owns interaction sessions, epochs, branches, cancellation and model execution. Keep product session IDs distinct from runtime client handles.
- Product modules use explicit ports. Do not import runtime/HTTP implementations into product services, reach into playback globals from product UI, or replace another view's functions.
- Contracts are versioned and standard-library-only. Preserve existing paths/import compatibility during migration. Land additive interfaces before updating consumers.
- Confirmed transcript and voice-note persistence remain atomic. Do not introduce eventual consistency into immediate conversation visibility as part of a refactor. Stale generations and unacknowledged replies must not become current playback/context.
- Use `python scripts/check.py contracts --strict` for shared-boundary changes. Use `product --browser --strict`, `infra --native --strict`, or `integration --native --browser --services --strict` for the affected track. New tests must have an owner in the test runner. Report missing dependencies or skipped checks explicitly.
- Product demo uses labeled typed input, fixed responses and silent audio. Keep its database separate. Use fixtures for routine checks; demo timings are not infra benchmarks or model-quality evidence.
- Infra optimization PRs include fixed scenarios, a baseline, correctness/quality checks and measured outcomes. Product UI changes include a reproducible interaction and visual review when appearance changes.
- Keep credentials out of source, fixtures, logs and artifacts. Preserve user workspace data; use temporary databases for tests.
