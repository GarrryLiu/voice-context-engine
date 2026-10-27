# Five implementation blocks

Each block is tested and committed/pushed separately. This extends the local
SQLite reference backend; production services and audio transport remain pending.

1. Version history and explicit three-way child-to-parent merge. Conflicts apply
   no writes until callers choose source or target; merges retain source-event
   provenance and advance a checkpoint. Old databases remain readable, but forks
   predating the baseline table cannot be merged without a recorded baseline.
2. Retrieval and context assembly (pending).
3. Durable background task orchestration (pending).
4. Pluggable model extraction (pending).
5. Transcript gateway and end-to-end experiments (pending).
