# Independent product and infra development

## Stable baseline and ownership

PRs #12–#15 were checked on their exact heads (all CI green) and merged in dependency order into `main`, preserving ancestry. Product sessions/graphs are user artifacts; interaction sessions, replies/epochs and context branches belong to the runtime. A product session references a context branch, not a browser connection.

Five small refactor stages: contract definitions, backend composition, frontend module boundaries, connected/demo adapters, then independent test/development entry points. Keep existing HTTP paths, `python -m voice_context.voice_server`, and transcript/voice-note atomic persistence compatible throughout. Do not move confirmed speech capture onto an eventually consistent queue as a side effect of reorganizing files.

## HTTP contract v1

Authenticated `GET /api/capabilities` describes routes, mode and limits. API responses include `X-Voice-Contract: 1`. Existing body shapes and error codes are retained. `contracts/` imports only the standard library. Workspace validation lives there; storage enforces optimistic versions atomically.

- Create an independent branch for a new product session; fork only when inheritance is intended.
- Confirmed speech is durable before acknowledgement. Partial speech is not saved as a note.
- Replies enter recovery context only after explicit playback acknowledgement.
- Cancellation/branch changes fence old response generations.
- Editing a map is separate from editing a source document or approving model memory.
- Additive changes can ship independently. Breaking changes require a new supported contract version and a consumer transition before removing v1.

## Backend composition

`server/app.py` owns security and lifecycle; `server/routes/` separates voice, product data and static resources. `infra/runtime/service.py` owns execution. `product/services.py` depends on a store-access port; `server/adapters.py` binds it to the existing serialized connection without changing transaction semantics. Product models live in `product/`; old Python import paths and `VoiceService` methods remain compatibility facades. The transcript-capture bridge still shares a transaction intentionally; removing that bridge is a separate migration, not an automatic queue conversion.

## Frontend module boundary

Product scripts are ES modules bootstrapped by `product-entry.js`. `client/runtime.js` exposes explicit read-only runtime/live ports; product code no longer assigns runtime globals or replaces another view's functions. Navigation owns shared guards, microphone checks and view transitions. The capture/playback implementation remains in the existing scripts to preserve tested timing behavior; a later internal rewrite can keep the same port.

## Connected and demo modes

`python -m voice_context.voice_server --mode demo --port 8766` starts with a separate `voice-demo.db`, without loading `.env`, opening model clients, requiring a native library, or connecting to Kafka/Redis. The banner labels typed input, fixed replies and silent audio as simulated. The same authenticated HTTP routes, product stores, context branches, reply format and explicit ACK semantics are exercised. Audio upload and live STT are refused in demo mode. A database already initialized for connected mode is rejected rather than populated with fixtures.

Connected mode remains the default and keeps the previous startup/configuration behavior. Demo verifies product flows; its timing and fixed content are not infra performance or model-quality measurements. It cannot replace connected-mode integration tests.

## Daily commands

Install the extras needed by your track in its own virtual environment (`pip install -e '.[voice,dev]'` for product, add `infra` for integration). Install the Playwright Chromium browser for UI checks. The product track does not require a C++ compiler or native-library environment variable.

```sh
python scripts/dev.py product                 # demo, 8766, .local/product/workspace.db
python scripts/dev.py infra                   # connected lab, 8767, .local/infra/workspace.db
python scripts/dev.py integration             # connected product, 8765, .local/integration/workspace.db

python scripts/check.py contracts --strict
python scripts/check.py product --browser --strict
python scripts/check.py infra --native --strict
python scripts/check.py integration --native --browser --services --strict
python scripts/check.py all --list
```

Connected profiles need local model configuration; keep `.env` private or pass an existing configuration path with `--env-file`. Never commit credentials or copy them into fixtures. `--services` requires all three explicitly configured `VOICE_TEST_POSTGRES`, `VOICE_TEST_KAFKA`, `VOICE_TEST_REDIS` variables and probes readiness; it does not create/restart Docker services. CI supplies isolated services. On macOS, `VOICE_CHROME_PATH` can select an installed Chrome for tests.

`check.py` assigns every test file to one track and rejects newly added unassigned root test files. `--strict` rejects skipped checks, so a green profile cannot silently omit a requested feature. Product/contracts profiles remove native and external-service test settings to prove their independence. CI runs contract, product, infra matrix and connected integration jobs separately; shared-interface changes receive all checks.

## Branches and worktrees

Use one product worktree and one infra worktree, each with a separate virtual environment and `.local/` database. Keep the existing presentation checkout as the integration environment. Start each feature from updated `origin/main`, use a short-lived feature branch and open an ordinary PR to `main`. Working branches in the two initial worktrees are just checkout anchors, not permanent product/infra release branches. Do not edit the same checkout from two chats.

Product PRs include a reproducible UI flow and screenshots when appearance changes. Infra PRs include the hypothesis, fixed baseline/scenarios, quality checks and measured results. Performance runs remain in `experiments/`; ordinary correctness checks do not claim performance gains. Contract changes land additively before consumers adopt them. Merge after relevant checks pass, then update the other worktree when it needs the interface change.

## Remaining migration boundaries

Only the runtime execution service has moved under `infra/`; context, broker and persistence modules retain compatible paths until a feature needs their migration. Capture/playback internals remain in the lab scripts behind explicit ports. These compatibility bridges are intentional and documented; the product can already be developed and tested independently through demo mode. No collaboration/account system, automatic semantic graph extraction or new routing optimization is introduced by this refactor.

The root `AGENTS.md` carries these boundaries into future chats. Each PR should say which track changed and which profile passed; the shared contract job protects both consumers.
