# Talk and Library product entry

`/product` opens Talk. Users can speak immediately in connected mode, or submit labeled typed examples in demo mode. No title, category or product-session creation dialog precedes a conversation. The lab remains at `/` and `/lab`.

The sidebar has two primary destinations:

- **Talk**: current conversation, microphone controls, playback and Review notes.
- **Library**: Records and Documents subviews, including record maps, categories, source documents and editing/version history.

Recent records open their content in Library. They do not silently switch the spoken context. **Continue in Talk** explicitly restores that record's branch. The optional **Clear focus** action then returns to a new independent context without a naming dialog or empty Library record; previous content stays saved.

Confirmed speech is saved as voice-note documents immediately. Stopping the microphone pauses capture, not the user's thought. **Review notes** pauses active playback/capture and manually collects the current branch's active source documents into a record for review. Repeated review deduplicates source documents and preserves edited graph nodes. Reviewing before any confirmed content opens Documents without creating an empty record.

This iteration changes the entrance and review workflow, not semantic organization. It does not automatically detect topics, route passages to multiple records, merge ideas, or inject edited graph content into model memory. The interface states that topic filing is manual. Records use the existing product-session storage shape internally so old workspace data and APIs remain compatible.

Canonical links are `/product#library`, `/product#library/<record-id>` and `/product#library/documents/<document-id>`. Existing `#workspace` and `#documents` links still resolve. New record creation is a Library management action, not a prerequisite to talking.

Validation covers the two-item sidebar, direct conversation, immediate access to confirmed documents, no empty records, source editing and recovery, record continuation, clearing focus, microphone pause, mobile layouts and preservation of the lab flow. Product tests use isolated demo data; connected integration tests use fixture providers. No paid model calls are needed.
