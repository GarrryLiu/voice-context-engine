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
