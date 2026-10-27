# Initial experiments

Run with `PYTHONPATH=src python3 experiments/run.py`. Raw output is committed in
`experiments/results.json`, including the host platform, Python version and seed.
Reruns overwrite that file; local timing naturally varies. The fixture is
synthetic and tiny. It establishes correctness properties, not production scale.

## Observed on the initial local run

- 500 unique structured events materialized; 100 identical retries deduplicated.
- Database reopened successfully; no processed events replayed a second time.
- 100 parent-branch queries returned their expected original decisions after
  conflicting updates were written to a child branch: 100/100 correct.
- A deliberately branch-blind latest-write-wins baseline returned the child
  values: 0/100 correct. This fixture is designed to expose branch contamination;
  it does not measure general retrieval quality.
- A 60-word packing budget selected 20 records totaling 60 words.
- Local SQLite ingestion p50 about 0.26 ms, p95 about 1.00 ms; materialization
  about 2,235 events/second; retrieval p50 about 1.06 ms in this one run.

Timing uses `perf_counter` around individual durable ingestion calls and
materialization wall time. It excludes audio, network calls, external services,
embeddings and model inference. There is no latency baseline or statistical
confidence interval, so no speedup is claimed.

## Routing arithmetic scenario

1,000 tasks: 100 interactive replies, 700 extractions and 200 reconciliations.
Assumed normalized cost per call is 3 for realtime, 1 for small, and 10 for
reasoning. Routing costs 3,000 units against 10,000 for always reasoning, or
70% lower **under those assumptions**. These are invented scenario inputs,
not prices or measured savings. No model quality or provider latency was tested.

## Test coverage

The unit suite checks exact retries, conflicting retries, version history,
parent/child isolation, fork snapshot behavior, pending-event recovery after
reopen, source retention, packing limits, unknown branch rejection and routing.
It does not prove distributed crash safety or simultaneous writer behavior.

Real Kafka/PostgreSQL/Redis and voice/model experiments remain pending until
those adapters and workloads are implemented. Results from this prototype must
not be represented as validation of those systems.
