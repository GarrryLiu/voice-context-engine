# Voiceline Documents

## Product model

A thought is a conversation branch. A document is an editable artifact linked to a thought. The library is workspace-wide, with filters for thought, kind, status and search. It contains four kinds:

| Kind | How it arrives | What is kept |
| --- | --- | --- |
| Voice note | Every finalized utterance, including live STT | Editable note plus immutable original transcript |
| Draft | “Save reply as draft” after full playback acknowledgement | Editable reply plus its frozen original utterance |
| Document | “New document” | User-authored title and content |
| Reference | Import a UTF-8 `.txt` or `.md` file, at most 128 KB | Editable copy, original text and source filename |

Existing unrevoked transcripts are backfilled as voice notes when a workspace opens. This never replaces an existing edited, archived or trashed voice note. Legacy transcript timestamps are unavailable; backfilled notes have the migration time, not an invented capture date.

## Primary flows

1. **Say it → find it.** Confirmed speech and its voice note commit in one transaction. Partial STT does not create a note. Reasoning/TTS failure does not erase a previously confirmed utterance.
2. **Reply → working draft.** Saving a reply uses server-side response segments and frozen context. The entire reply must be sealed and fully acknowledged. Repeated saves return the same draft, and cannot attach it to a different utterance.
3. **Edit → keep versions.** Rename, edit content, link a thought and set a collection. Each change saves a snapshot with an expected version. A stale editor gets HTTP 409; its local edits remain available for export or manual reconciliation.
4. **Revisit → restore.** Preview earlier text before restoring. Restore creates another version; it does not erase history or replace the immutable original source.
5. **Organize → recover.** Archive hides a document from the active list; Trash is reversible. These operations affect the document, not its source conversation. No permanent-delete endpoint is provided.
6. **Take it elsewhere.** Markdown export includes the current editor content, including unsaved edits. Imported content is displayed as plain text, never executable HTML.

Switching documents or leaving for Thoughts prompts Save / Discard / Keep editing if there are unsaved changes. A browser close/refresh uses the native unsaved-changes guard. Opening Documents ends continuous capture or interrupts an active reply, so a hidden microphone does not keep recording.

## Data and reliability

`documents` holds the current editable state, original-source snapshot, transcript/reply IDs and source branch. `document_versions` holds immutable title/content/association/status snapshots. The existing SQLite/PostgreSQL adapter is reused. Source fields are not accepted by update APIs.

- Capture is part of `Transcripts.append_in_transaction`; failure rolls back both transcript/outbox and voice note.
- Updates compare the supplied version under the database transaction lock.
- List pages contain 100 rows plus a next-page cursor, not full document bodies. Search input, text bytes and revision counts are bounded.
- Titles: 320 UTF-8 bytes; content: 128 KiB; collections: 80 bytes; maximum 1000 revisions per document in this local prototype.
- All document APIs reuse loopback Host/Origin checks and the local page token. The library is shared by the local workspace, not a new multi-tenant account system.
- Documents do not automatically become approved memory or enter model prompts. Archiving or trashing a document does not revoke its source transcript from conversation context.
- Raw microphone audio is still not retained. “Original source” means original confirmed transcript or imported text, not an audio recording.

## Current boundary and next iterations

This version manages text artifacts. It does not yet parse PDF/Word, render rich Markdown, generate long-form documents in a new model call, perform document-grounded retrieval/citations, or apply spoken edit commands to an open document. “Draft” is a saved existing assistant reply, not a claim that the system already creates a full formatted report.

The next product iteration can add **Continue this document by voice**: choose the target document, collect new speech as a source, preview an append/rewrite proposal, then apply it with the same expected-version check. PDF/Word extraction should separately preserve file identity and page/paragraph anchors before document-grounded voice discussion is enabled.

## Validation

Tests cover atomic capture/rollback, duplicate ingestion, migration without resurrection, edits preserving source, concurrent-version conflicts, history restoration, archive/trash recovery, literal search and pagination. PostgreSQL uses isolated schemas. API tests check acknowledgement-gated drafts, retry deduplication, auth and payload limits.

The browser flow uses fake STT/LLM/TTS: speak/upload, save a reply draft, edit, inspect original text, restore a version, export, guard unsaved changes, archive, trash/restore, import untrusted plain text, search and reload the selected document on mobile. No paid model calls or real microphone data are used by these tests.
