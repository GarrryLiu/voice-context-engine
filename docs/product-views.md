# Talk and Workspace product entry

`/product` opens Talk. Users can speak immediately in connected mode, or submit labeled typed examples in demo mode. No title, category or product-session creation dialog precedes a conversation. The lab remains at `/` and `/lab`.

The sidebar has two primary destinations:

- **Talk**: current conversation, microphone controls, playback and Review notes.
- **Workspace**: Records and Documents subviews, including record maps, categories, source documents and editing/version history.

Recent records open their content in Workspace. They do not silently switch the spoken context. **Continue in Talk** explicitly restores that record's branch. The optional **Clear focus** action then returns to a new independent context without a naming dialog or empty Workspace record; previous content stays saved.

Confirmed speech is saved as voice-note documents immediately. Stopping the microphone pauses capture, not the user's thought. **Review notes** pauses active playback/capture and manually collects the current branch's active source documents into a record for review. Repeated review deduplicates source documents and preserves edited graph nodes. Reviewing before any confirmed content opens Documents without creating an empty record.

This iteration changes the entrance and review workflow, not semantic organization. It does not automatically detect topics, route passages to multiple records, merge ideas, or inject edited graph content into model memory. The interface states that topic filing is manual. Records use the existing product-session storage shape internally so old workspace data and APIs remain compatible.

Canonical links are `/product#library`, `/product#library/<record-id>` and `/product#library/documents/<document-id>`. Existing `#workspace` and `#documents` links still resolve. New record creation is a Workspace management action, not a prerequisite to talking.

Validation covers the two-item sidebar, direct conversation, immediate access to confirmed documents, no empty records, source editing and recovery, record continuation, clearing focus, microphone pause, mobile layouts and preservation of the lab flow. Product tests use isolated demo data; connected integration tests use fixture providers. No paid model calls are needed.

The product label is Workspace. Existing `#library` URLs and internal element IDs remain compatible; this naming change does not migrate user data.


## On-the-go continuity iteration

Talk now offers recent non-example topics without requiring an upfront session. Continue talking restores the record's runtime branch but does not start the microphone automatically. Resuming fences/stops active playback before switching context. Workspace shows review/continue cards above the existing map.

Finish & review pauses capture, collects durable source documents using the existing version-checked workspace write, then opens a review dialog with source excerpts. It does not invent summaries, plans, or decisions. Source voice notes remain intact; record-node edits are separate. Empty conversations create no record. Dialog dismissal leaves the saved record available.

Reproduce in demo: submit a typed thought, Finish & review, inspect the source excerpt, Continue talking, submit another thought, finish again, review the record, return to Talk and clear focus, then use the recent-topic card to resume. Demo still uses fixed replies and silent audio. Real hands-free commands, spoken finish recaps, automatic summary/plan generation, offline capture and mobile background audio remain unimplemented. Live capture retains its existing two-minute limit; this iteration does not establish commute readiness.


## Graph-first Workspace

Workspace opens directly into the global topic map. The continuity cards remain only in Talk. One click enters a topic; the left topic tree exposes its individual thoughts for quick selection. The inspector is hidden until a node or Topic details is selected, and can be dismissed without leaving the map. Topic details supports renaming, category changes and explicit cross-topic links; thought editing and original-source access remain unchanged. Selected thoughts emphasize their stored neighbors. No inferred or automatic connections are shown. Category labels identify spaces without changing saved node positions. Search/category filters, map/list mode, pan/zoom, export and version-checked persistence remain available.

Browser validation includes global → topic navigation, source-node editing, neighbor emphasis, inspector dismissal, sidebar selection, topic renaming and desktop/mobile visual inspection. Examples remain labeled and separate from real notes. The underlying records still reference runtime branches; automatic assignment of one conversation to multiple topics is future work.

## Real-model semantic map suggestions

`Finish & organize` reads saved voice-note sources in chronological order and requests a compact, structured map. The preview includes topic summaries, typed nodes, explicit uncertainty/revision states, and exact source quotations. Saving is explicit; closing the preview leaves the workspace unchanged. Original voice notes remain in Documents. Node source access opens all cited excerpts. Map edits remain product artifacts, separate from confirmed runtime memory.

Connected mode enables the lazy map adapter. Ordinary product demo stays offline and never reads model credentials. To explicitly combine typed/fixed-response voice demo with real map generation:

```sh
python scripts/dev.py product --map-llm --env-file /absolute/path/to/private/.env
```

The banner distinguishes simulated voice from real map calls. Use the configured `LLM_MODEL` and `LLM_API_KEY`; no credentials are copied. The adapter uses OpenAI Responses structured output, `store=False`, no automatic request retries, a 120-second timeout, and a 10,000-output-token cap. The product validates every source quotation and graph reference. Exact quotes establish provenance, not semantic correctness; users still review suggestions. Input is bounded to 200 active voice notes and 60,000 characters, and output to 8 topics / 48 nodes. Longer inputs are rejected explicitly, not silently truncated.

Additive HTTP v1 endpoints: `GET /api/maps/status`, `POST /api/maps/propose {branch}`, `POST /api/maps/apply {id}`, `GET /api/maps/provenance?node=...`. Proposals persist separately. Apply atomically checks source fingerprint and workspace version before changing the graph, marks the proposal applied, and is idempotent on retry. Generation releases the runtime/store lock during model execution and permits only one in-flight map request per server. Errors are redacted and preserve sources. No background model calls run merely from opening the page.

Current scope: create new topic maps from a conversation. Incremental semantic merging into existing topic maps and topic-isolated runtime context are not implemented. Generated topics reference the same original conversation branch; the preview explicitly explains this. Semantic state appears in the editable node content. Relations and all citations remain in the saved proposal, while existing v1 graph edges display untyped connections.

Offline verification: `python scripts/check.py contracts --strict` and `python scripts/check.py product --browser --strict`. The regression browser uses an injected fixture provider, tests preview/cancel/apply/source access and never contacts a model. Real-model experiment: `PYTHONPATH=src python experiments/semantic_map_poc.py --env-file /absolute/path/to/private/.env`; synthetic sources and temporary database only. The experiment saves a real model response first, then replays that exact response through the proposal API and browser, so repeated UI checks do not pay for another generation. Use `--refresh-model` for a new model call. Review its recorded results separately from deterministic test pass counts. Known cross-topic node references are normalized into the existing topic-level graph; unknown/ambiguous references are rejected.

The two recorded model iterations exposed missing uncertainty coverage and incorrect revision typing in the first prompt. The second run produced four topics, 23 concepts, one internal revision edge and two cross-topic edges. It preserved the explicit open choices and the tentative status of the superseded plan. See `experiments/semantic-map-poc-results.json` for source checks, usage and manual review; this is one synthetic scenario, not a production quality claim.

## Local daily-use build

This is a single-user, loopback-only local beta. It does not offer account isolation,
remote/mobile hosting, cross-conversation automatic merging, or topic-isolated
model context. The connected build supports real provider calls, but automated
microphone tests use synthetic audio/providers; they do not establish live speech
accuracy or commute reliability.

From the product checkout (with voice dependencies installed):

```sh
.venv/bin/python scripts/build_runtime.py
.venv/bin/python scripts/dev.py daily --env-file /absolute/path/to/private/.env
```

Open `http://127.0.0.1:8768/product`. This uses a separate
`.local/daily/workspace.db`; the typed demo at 8766 keeps its existing database.
Real model/audio requests incur the configured provider's charges only when used.
Each daily-profile restart validates configuration and creates a verified SQLite
snapshot of an existing database under `.local/daily/backups/` before startup.
Backups include conversation sources, document history, graphs, and proposal
provenance. They are private local files and should be retained with the same care
as the original notes. No backups are automatically deleted.

### Recovering from failed saves

Map changes submitted for saving are also stored in this browser tab's session
storage. After a failed save, refresh in the same tab recovers that draft. Use
**Retry save** after connectivity returns. A version conflict never overwrites a
newer workspace: export the local map, then **Reload** to explicitly discard the
local draft and load the saved version. Unsaved inspector form fields still require
Save changes; session storage is not a durable backup and closing the tab may lose
it. Document edits retain their existing explicit save/version conflict behavior.

**Export map** exports graph structure only. For a complete backup, including
original notes and evidence, run:

```sh
PYTHONPATH=src .venv/bin/python -m voice_context.product.backup \
  .local/daily/workspace.db .local/daily/backups/manual-copy.db
```

To restore, stop the daily server, snapshot the backup to a **new** database path,
then start `scripts/dev.py daily --db /absolute/path/to/restored.db --env-file ...`.
The snapshot command never overwrites an existing destination. It checks SQLite
integrity and captures committed WAL data, including when the source is live.

### Verification for the local-beta hardening

- Product strict browser profile: 24 tests (includes failed-save refresh/retry,
  conflict rejection, explicit reload, backups and source-preserving restore).
- Contract strict profile: 4 tests.
- Connected voice HTTP/browser/fault scenarios: 31 tests; streaming STT: 6 tests.
  Three stale UI expectations were updated to the current Talk/outcome/single-click
  flow and rerun successfully. No external Kafka/PostgreSQL/Redis services were
  tested in this iteration.
- `experiments/daily_product_smoke.py` performs an explicitly paid, isolated real
  API smoke with a supplied fixed WAV. The recorded result is in
  `experiments/daily-product-smoke-results.json`: real speech transcription,
  reply audio, reviewed map save, evidence view and reload passed. The input was
  synthetic speech; this is a functional smoke, not a quality or latency benchmark.

## Recursive sessions and full documents

The outer map holds complete sessions and standalone documents. A session can
contain sections/subsessions and full document leaves; containers can themselves
contain further containers. Clicking a container enters its graph, and clicking
a document opens a full-text editor. Breadcrumbs, the sidebar tree and Back move
between scopes. Container paths survive reload. Add section creates another level;
Expand into a section preserves the original document in a new child document.
Existing flat maps and original source documents remain readable without a migration.

New AI suggestions save one complete session, rather than one top-level record
per topic. The optional semantic `parent` field places subordinate topics within
broader ones. A single topic does not create a redundant intermediate topic level.
Containment is independent of association: links render in the nearest shared
scope, and original model evidence remains in the saved proposal. Cyclic parents,
unknown parents, invalid references and leaves containing child graphs are rejected.

The additive workspace fields are root `kind` (`session`/`document`), optional
root `content`/`source`/`document_id`, and recursive node `kind: session` with
`nodes`/`edges`. Legacy roots without `kind` remain sessions. Edges reference
siblings in their scope. There is no two-level product restriction; defensive
limits are 32 nested container levels, 2,000 descendants per root and the existing
2 MB workspace cap. Model suggestions retain their bounded eight-topic/48-note
budget; this is separate from manually building deeper structures.

Map document text is currently stored with the versioned workspace, not duplicated
into the separate Documents catalog. Existing `document_id` references open that
catalog's editor; original evidence always points to the preserved source document.
Per-document revision history for embedded map documents, arbitrary reparenting,
and automatic multi-session merging are not part of this iteration.

Verification: 27 product tests, four contract tests and four connected voice browser
tests. The new browser scenario enters five nested sections, reloads, edits a full
document, expands it to another section, navigates back and creates a top-level
document. `experiments/recursive_map.py --env-file ...` is the explicit paid smoke;
the recorded synthetic conversation produced one root session and three node levels.
That run verifies the real schema/API path, not a general hierarchy-quality score.
