"""Seeded synthetic experiment. Model costs and latency are assumptions, not measurements."""
import argparse
import json
import platform
import random
import statistics
import tempfile
import time
from pathlib import Path
from voice_context.engine import Engine, route


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="experiments/results.json")
    args = parser.parse_args()
    rng = random.Random(42)
    with tempfile.TemporaryDirectory() as d:
        engine = Engine(str(Path(d) / "experiment.db")); engine.fork("main")
        ingest_ms = []
        for i in range(500):
            start = time.perf_counter()
            engine.ingest(f"e{i}", "main", f"s{i // 50}", key=f"topic{i}", value=f"decision original{i}")
            ingest_ms.append((time.perf_counter() - start) * 1000)
        # Simulate client retries before materialization.
        retries = sum(not engine.ingest(f"e{i}", "main", f"s{i // 50}", key=f"topic{i}", value=f"decision original{i}") for i in range(100))
        start = time.perf_counter(); applied = engine.drain()
        process_seconds = time.perf_counter() - start
        engine.fork("alternative", "main")
        for i in range(100):
            engine.ingest(f"alt{i}", "alternative", "new-session", key=f"topic{i}", value=f"decision alternative{i}")
        engine.drain(); engine.close()
        engine = Engine(str(Path(d) / "experiment.db"))
        scoped_correct = flat_correct = 0
        recall_ms = []
        for i in range(100):
            start = time.perf_counter()
            record = engine.recall("main", f"topic{i}", limit=1)[0]
            recall_ms.append((time.perf_counter() - start) * 1000)
            scoped_correct += record["value"] == f"decision original{i}"
            # Baseline: a global latest-write-wins map that discards branch identity.
            global_latest = engine.db.execute("SELECT value FROM memory WHERE key=? ORDER BY version DESC, branch ASC LIMIT 1", (f"topic{i}",)).fetchone()[0]
            flat_correct += global_latest == f"decision original{i}"
        compact = engine.compact("main", word_budget=60)
        assert applied == 500 and retries == 100 and scoped_correct == 100
        assert engine.drain() == 0 and compact["words"] <= 60
        engine.close()
    tasks = ["respond"] * 100 + ["extract"] * 700 + ["merge"] * 200
    rng.shuffle(tasks)
    # Arbitrary normalized cost per call, fixed input/output size, no quality model.
    cost = {"realtime": 3, "small": 1, "reasoning": 10}
    routed_cost = sum(cost[route(t).model] for t in tasks)
    result = {
        "seed": 42, "python": platform.python_version(), "platform": platform.platform(),
        "scope": "Synthetic structured text events on local SQLite; no audio, Kafka, PostgreSQL, Redis or model calls",
        "persistence": {"events": 500, "duplicate_retries_deduplicated": retries, "events_applied": applied,
                        "pending_after_reopen": 0},
        "branch_retrieval": {"queries": 100, "scoped_accuracy": scoped_correct / 100,
                             "global_latest_baseline_accuracy": flat_correct / 100,
                             "fixture": "100 parent decisions contradicted in a child branch"},
        "local_measurements": {"ingest_p50_ms": statistics.median(ingest_ms),
                               "ingest_p95_ms": sorted(ingest_ms)[int(.95 * (len(ingest_ms)-1))],
                               "materialize_events_per_second": applied / process_seconds,
                               "recall_p50_ms": statistics.median(recall_ms)},
        "compaction": {"budget_words": 60, "packed_words": compact["words"], "records": len(compact["records"]),
                       "limitation": "Word packing only; no semantic summarization or tokenizer budget"},
        "routing_simulation": {"calls": len(tasks), "assumed_cost_units_per_call": cost,
                               "all_reasoning_cost": len(tasks) * 10, "routed_cost": routed_cost,
                               "cost_reduction": 1-routed_cost/(len(tasks)*10),
                               "limitation": "Arithmetic scenario only; quality, actual cost and latency unmeasured"}}
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
