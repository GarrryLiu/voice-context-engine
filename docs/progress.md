# Five implementation blocks

Each block is tested and committed/pushed separately. This extends the local
SQLite reference backend; production services and audio transport remain pending.

1. Version history and explicit three-way child-to-parent merge. Conflicts apply
   no writes until callers choose source or target; merges retain source-event
   provenance and advance a checkpoint. Old databases remain readable, but forks
   predating the baseline table cannot be merged without a recorded baseline.
2. Retrieval now weights rare matches, supports Chinese character/bigram matching,
   and boosts exact memory keys. Context packing includes serialized provenance
   overhead, reports omitted records and accepts a model tokenizer cost function;
   its default budget is UTF-8 bytes, not tokens.
3. Durable SQLite task queue: deduplicated requests, lease-based claiming,
   attempt limits, exponential retry delay, dead-letter state and cancellation.
   Stale workers cannot acknowledge after expiration. Handlers run outside the
   queue transaction and must use idempotent side effects; leases do not interrupt
   running network calls. The reference worker is single-task, not a parallel DAG.
4. Pluggable model extraction (pending).
5. Transcript gateway and end-to-end experiments (pending).
