# Architecture and implementation boundaries

## Local contracts

`ingest(event_id, branch, session, key=..., value=...)` commits one structured
memory-update event without running extraction or retrieval. Repeating the exact
request returns false; reusing an ID for different content raises ValueError.
The event table is a durable local queue, not a Kafka implementation.

`process_one()` obtains a SQLite write transaction, applies one queued event,
and marks it processed in the same transaction. A rollback leaves the event
pending. Multiple Engine instances may compete for the database lock; processing
is serialized. Lock timeout handling, bounded retries and dead-letter handling
remain future work. The current transaction is intentionally simple and is not
a distributed exactly-once guarantee.

Memory is append-only by `(branch, key, version)`. `source` points to the original
event ID. `fork` copies all existing parent versions atomically; this trades
storage for simple snapshot semantics. Child updates cannot mutate parent state.
Forks before pending parent events are materialized exclude those events.

Retrieval first selects the current version for every key within one branch,
then ranks by keyword overlap. It is not semantic retrieval. Chinese matching uses characters and bigrams; it is still lexical, not semantic. Packing preserves
whole records and provenance but may omit important records; it is not a learned
summary. The word budget does not equal a model token budget.

## Production adapters to implement

1. Realtime gateway: audio transport, cancellation, barge-in, backpressure and
   transcript finalization. Partial transcripts must not overwrite durable facts.
2. PostgreSQL event/memory store: schema migrations, tenant/workspace isolation,
   optimistic version checks and transactional outbox publishing.
3. Kafka transport: key ordering by workspace/branch, commit offsets only after
   durable effects, event-ID deduplication, retry policy and dead-letter topics.
4. Redis cache: cache keys include workspace, branch and memory revision; only
   cache derived state, invalidate after durable commits, tolerate cache loss.
5. Model adapters: structured extraction, source validation, reconciliation and
   semantic retrieval. Keep user decisions distinct from model inferences.

## Orchestration plan

The `route` function selects logical model classes. `ExtractionRouter` now
accepts provider implementations, including an optional Ollama HTTP adapter;
the default is a deterministic parser. No live LLM quality evaluation has run. Proposed background task graph:

final transcript -> extract candidates -> validate sources -> detect conflicts
-> append memory revision -> invalidate cache -> refresh compacted context.

Run independent extraction jobs concurrently with bounded worker capacity. Order
writes to the same memory key or reject stale revisions. Deduplicate jobs with
(event ID, task type, policy version); record attempt, timeout, input revision,
model identifier and output provenance. Cancel obsolete context refreshes while
preserving source events. Direct-child changes can be reconciled by the implemented three-way merge;
conflicts require explicit source/target selections.

Route interactive replies to a latency-oriented provider, routine extraction to
a lower-cost provider and ambiguous conflicts to a reasoning provider. Enforce
budgets and deadlines before dispatch; use bounded retries and deterministic
fallbacks. Routing quality must be evaluated before treating cheaper dispatch as
an optimization.

## Next acceptance gates

- Real infrastructure: crash/restart consumer, duplicate delivery, cache eviction,
  two concurrent writers, poison event and delayed outbox publishing.
- Model quality: labeled extraction and branch retrieval, false memories,
  source attribution, contradiction detection and summary omissions.
- Voice: first-audio latency, interruption recovery and concurrent sessions.
- Compare one-model and routed policies on identical workloads, report measured
  cost, p50/p95 latency and quality together; version prompts and providers.
