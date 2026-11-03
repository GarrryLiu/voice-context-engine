# Product session maps

Voiceline has two separate surfaces: a staged voice runtime, and a product for capturing, organizing and continuing spoken thinking. This iteration builds the product workflow without changing model routing policies.

## Demonstration flow

1. Open `/product` and speak in the existing voice interface. Finish with **Finish & organize**.
2. The product collects this branch's active voice-note documents into a session map. Each imported node links to its original document. It does not invent semantic relationships or call a summarizer.
3. Return to **All sessions**. Select categories, search, switch between Map and List, select a session, then **Open session map** (or double-click a session).
4. Drag nodes; pan the canvas; zoom or reset the map to fit the visible nodes. Select a node to edit its title and working content. Add thoughts, connect nodes, remove connections, or remove a node/session from the map. Removing a map item retains original documents and runtime records.
5. **Continue with voice** resumes the session's branch. Newly created product sessions get independent root branches rather than inheriting another session's context. **Finish & organize** appends new source documents once each, retaining manual map edits.

The existing Documents view remains a secondary source editor with version history. Map node content is an editable working copy: it is not a live two-way mirror of the source document. Edited nodes are not automatically added to LLM context or approved memory. Continuing from an arbitrary node with its edited content as prompt context is not implemented in this iteration.

## Example workspace

**Explore example** explicitly adds labeled synthetic sessions in Product, Research, and Personal. Examples are never loaded automatically, never presented as recorded conversations and never injected into a model. They can be edited or removed like other map items. Continuing an example creates an empty spoken branch; the example text remains presentation content.

## Storage and interface

`ProductWorkspace` stores one bounded local workspace snapshot in `product_workspace`, with an optimistic version. Categories, product sessions, node coordinates, node content, source-document references and explicit links survive browser/server restarts. The product session ID is distinct from the runtime browser interaction ID. A product session references a branch, which can outlive individual voice connections.

- `GET /api/workspace`: `{version,data}`.
- `POST /api/workspace`: replace a validated snapshot with an expected version; stale writers receive 409.
- Existing token, loopback Host and Origin guards protect both routes.
- Invalid identities, dangling or duplicate links, invalid coordinates and oversized payloads are rejected.
- Writes are serialized in the UI; failures retain the visible working map. Export map downloads JSON. After a conflict, export then reload the latest saved state; there is no silent last-writer-wins overwrite.

This is a single-user local presentation build, not multi-user collaboration. Snapshot storage is deliberately bounded (200 sessions, 300 nodes per session, 2 MB total). Large-workspace indexing, graph diff operations, auto-layout and access control belong to later iterations.

## Verification

`tests/test_product_workspace.py` covers restart persistence, conflicting writers and malformed graphs. The server tests cover authorization, conflicts and independent branch context. The browser graph test uses a synthetic microphone and fixture providers, verifying spoken content collection, example browsing, editing, dragging, reload persistence, adding nodes, resuming voice and collecting a new utterance. Existing lab/document browser tests run alongside it. No paid model calls are needed.

Local validation passed 142 tests (80.539 s), followed by four browser regressions after interaction changes and a final graph-flow run after the mobile layout correction. Desktop and mobile screenshots were visually reviewed. See `experiments/product-session-maps-validation.json` for exact scope, source hashes and retained local log paths.
