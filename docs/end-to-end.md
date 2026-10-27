# Five-block integration experiment

Run on 2026-10-27 with Python 3.14.7 on macOS:

```sh
PYTHONPATH=src python3 experiments/end_to_end.py
```

Raw result: `experiments/end-to-end-results.json`.

The fixture contains 40 synthetic Chinese transcript lines in explicit
`remember key: value` syntax across four sessions. Ten exact duplicate
submissions were rejected as duplicates. The database was closed with work still
pending, reopened, and all 40 tasks completed through the durable queue. No
candidate was written to memory before caller confirmation. The experiment
confirmed all 40 records, closed/reopened again, and retrieved the correct
current value for all 40 exact-key queries.

It then forked a child, wrote contradictory parent/child decisions through the
same pipeline, detected one merge conflict without applying any writes, and
explicitly selected the child value. One merge revision was appended. The
serialized context, including provenance, used 359 UTF-8 bytes within a 512-byte
budget. Elapsed time is captured as a local observation, not a performance claim.

The full suite has 33 tests spanning history/merge checkpoints, multilingual
matching, context budget and revision invalidation, queue retries/leases,
cancellation, provider contract mocks, evidence rejection, candidate confirmation,
restart recovery and JSON-lines gateway execution across processes.

This does not test real microphones, speech recognition, semantic embeddings,
Kafka/PostgreSQL/Redis, production concurrency, live Ollama/model quality, actual
model cost or a parallel agent DAG. Rule parsing on an exact-key fixture is not
evidence of natural-language memory extraction quality.
