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
