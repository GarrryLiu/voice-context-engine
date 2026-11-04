# Text/TTS overlap: experiment 001

## Decision

Keep overlap opt-in through `Conversation(..., overlap_text=True)`. The web runtime keeps its default serial mode. This experiment establishes bounded text prefetch, not a new sentence segmentation policy. Short-first-segment work is deferred.

## Baseline and implementation

The baseline reads a text fragment, drains its TTS segments synchronously, then reads the next fragment. The experimental path reads text on one producer thread while the original coordinator performs TTS. The C++ segmenter, TTS ordering, audio queue, epoch checks and playback acknowledgement rules are unchanged.

The text queue holds at most four fragments plus one producer-held fragment. The existing total response byte cap bounds accepted text. A process-wide eight-slot semaphore bounds lingering provider threads. Cancellation/deadlines stop queue consumption; providers must still enforce their own network timeouts. Python cannot forcibly terminate a blocked SDK call. Iterator cleanup runs on its owning producer thread. The reason-stage timer measures provider iteration work rather than consumer queue wait; interrupted in-flight work may not be fully accounted for.

## Reproduce

Use the commit containing this report. Exact source SHA-256 fingerprints, Python/platform versions, fixed inputs, configuration and every event trace are in [raw results](../experiments/text-tts-overlap-results.json). Run from the repository root:

```sh
python3 scripts/build_runtime.py
python3 experiments/text_tts_overlap.py
.venv/bin/python scripts/check.py infra --native --strict
```

The experiment itself uses only the Python standard library and compiled native runtime. No API key, microphone or cloud service is used. Each trial creates and removes its own temporary SQLite database.

## Fixed design

Four synthetic English/Chinese inputs; three repetitions per strategy, alternating strategy order. Each text fragment sleeps 40 ms; each synthetic TTS request sleeps 80 ms, then returns UTF-8 bytes as a stand-in for audio. The output bytes must exactly equal the original input in order. There is no real speech or playback simulation.

| Fixture | Baseline completion median (ms) | Overlap completion median (ms) |
|---|---:|---:|
| 0 | 393.64 | 304.60 |
| 1 | 400.04 | 316.39 |
| 2 | 135.30 | 131.61 |
| 3 | 261.69 | 224.15 |

Across all 12 trials per strategy:

| Metric | Baseline | Overlap |
|---|---:|---:|
| median_first_audio_seconds | 0.132087 | 0.131440 |
| median_completion_seconds | 0.327680 | 0.264743 |
| total_tts_requests | 27.000000 | 27.000000 |

## Interpretation and limits

The controlled delayed-provider workload demonstrates that reading later text no longer waits for prior TTS completion. First audio should remain similar: both strategies still wait for the same first fragment and first synthesis. No first-response latency improvement is claimed.

The synthetic text generator advances only when read. A remote LLM server may already generate and buffer tokens independently, so these completion-time gains cannot be extrapolated to API traffic. Audio arrival intervals are saved, but they are not audible playback gaps. We did not measure acoustic quality, API cost, physical microphone/speaker latency, p95, or real TTS. Identical request counts do not establish identical billed cost. Small sample timing differences should not be interpreted as significant.

Correctness tests cover concurrent text progress during TTS, exact ordering, final text without punctuation, provider error abort, bounded lookahead, cancellation, deadline and owner-thread iterator cleanup.

## Next experiment

Use a thread-safe real-provider adapter and controlled text replay with the same fixtures; record first playable PCM, actual playback underruns, provider usage and cancellation cleanup. Only then consider exposing an opt-in web setting. Keep first-segment splitting unchanged until this comparison is understood.

## Validation for this revision

- `scripts/check.py infra --native --strict`: 92 passed.
- `scripts/check.py contracts --strict`: 4 passed.
- `scripts/check.py integration --native --browser --services --strict`: 48 passed using explicitly configured local PostgreSQL/Kafka/Redis and Chrome. This verifies default-path regressions; the new overlap path is exercised by the targeted native tests and experiment.
- Paid provider calls: zero. Real TTS comparison and perceptual listening remain future work.
