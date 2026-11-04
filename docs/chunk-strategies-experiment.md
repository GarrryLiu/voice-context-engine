# Chunk scheduling experiment 002

## Scope and decision

Builds on experiment 001 / the text-prefetch branch. Keep all policies experimental and opt-in. No product UI, browser feedback transport or default runtime behavior is changed. The existing native segmenter is retained for the default path. Explicit scheduler chunks go directly through the existing segment journal and ordered TTS loop, avoiding a second native text split; native audio buffering and epoch fencing remain active.

## Policies and API

```python
conversation.respond("reply-id", text_provider, tts_provider,
                     chunk_strategy="short_first")
# Other strategies: sentence, buffer_aware. None retains the native baseline.
# Optional: playback_state(ticket) returns the feedback dictionary below.
```

- `sentence`: sentence boundaries, with safe whitespace fallback after 600 ms or at the 1600-character bound. This is not an infinite-wait sentence baseline.
- `short_first`: first chunk may use a phrase boundary after 12 characters; subsequent chunks use sentence policy.
- `buffer_aware`: same first-chunk rule; subsequent phrase dispatch uses playback urgency. No feedback or stale feedback falls back to sentence behavior after the first chunk.

Feedback is `{epoch, sequence, at, seconds}`: current reply epoch, increasing sequence, timestamp in the same server monotonic-clock domain, and queued playable seconds. The caller must normalize browser timestamps before injection. Wrong epochs, old sequences, future timestamps, nonfinite values and feedback older than 1 second are ignored. Remaining seconds are aged locally assuming uninterrupted playback; browser pauses require new feedback. No browser adapter is implemented here.

Urgency enters below estimated TTS first-block time + 0.2 seconds and exits above estimate + 0.8 seconds. The estimate starts at 0.25 seconds and uses a 0.2-weight exponential update. These are exploratory constants, not tuned or statistically calibrated. Decisions happen on new text or 20 ms polling ticks; TTS remains serialized and queued chunks are not concurrently synthesized. Timing decisions can therefore depend on the preceding TTS duration.

One-character lookahead protects decimal points and common abbreviations. An incremental UTF-8 decoder accepts byte-fragment boundaries. The rules do not constitute a complete linguistic parser. Unbroken text with no safe boundary beyond the provider limit fails explicitly instead of cutting a word. Whitespace is preserved by the scheduler; whitespace-only chunks are not sent to TTS.

## Reproduction

```sh
python3 scripts/build_runtime.py
.venv/bin/python experiments/chunk_strategies.py
# Makes paid API requests; keep the private environment file out of Git:
.venv/bin/python experiments/chunk_strategies.py --live --env-file /path/to/private.env
.venv/bin/python scripts/check.py infra --native --strict
```

The tracked JSON files contain fixtures, every text/PCM timing event, configuration, source SHA-256 hashes, runtime environment and creation timestamp. Each run uses a disposable database. Only synthetic public text is sent. Credentials, model responses from private conversations and audio files are not stored.

## Live TTS pilot

Model: `gpt-4o-mini-tts`; voice: `coral`. Four texts, one trial per policy/text, alternating policy order by fixture. Text replay delivers one character every 10 ms. There is no live LLM. Eight response-level trials made 24 TTS requests total. Character and PCM counts are local measurements, not supplier billing.

| Fixture | Sentence first queued audio (s) | Short-first first queued audio (s) | Sentence / short-first requests |
|---|---:|---:|---:|
| 0 | 1.930 | 1.158 | 4 / 3 |
| 1 | 0.817 | 0.940 | 2 / 3 |
| 2 | 1.383 | 1.051 | 3 / 4 |
| 3 | 1.019 | 0.878 | 3 / 2 |

Descriptive median across four different fixtures: sentence 1.201 s, short-first 0.995 s. Short-first was earlier in three fixtures and later in the Chinese fixture. Both made 12 total TTS requests, but their per-fixture counts differed. This small heterogeneous sample, with network and connection warm-up variation, does not establish a significant or generalizable improvement. Keep the default unchanged.

## Simulated feedback comparison

| Strategy | Median first queued audio (s) | Total requests |
|---|---:|---:|
| sentence | 0.707 | 10 |
| short_first | 0.522 | 11 |
| buffer_aware | 0.508 | 11 |

All simulated runs reported zero gaps under the chosen idealized PCM-duration model. Consequently this experiment does NOT show that buffer-aware scheduling improves underruns over short-first. A starvation/stale-feedback sweep is needed next; do not present the small timing differences as adaptive-policy superiority.

## Measurement limits and follow-up

- First audio means accepted into the local native queue, not audible speaker onset.
- The idealized gap fields consume PCM at 24 kHz mono PCM16 and assume immediate decoding and playback. They are not browser underrun measurements. Ignore their very short gaps as acoustic evidence.
- No listening evaluation was performed. Naturalness, prosody and pronunciation remain unverified.
- Input text is preserved in every trial. Request counts may change because real synthesis delays affect waiting timers and queue backpressure.
- No claim of p95 improvement, billed-cost reduction, or production readiness.
- Next: repeated randomized paired live trials, a no-network regression replay, browser playback feedback with pause/epoch handling, and human audio comparison before enabling a default strategy.

## Validation

100 native infra tests passed, including exact text conservation, decimal/abbreviation boundaries, short-first scope, stale/old feedback, bounded pending text, timer flush during provider stalls, bytewise UTF-8 input and interruption cleanup. Contract and connected regression results are reported in the accompanying pull request.

Final regression: 4 strict contract tests and 48 strict connected integration tests with native runtime, browser, PostgreSQL, Kafka and Redis also passed (152 total). The simulated provider sleeps 80 ms per request and supplies 18 ms of nominal audio per input character; these deliberately simple assumptions explain why this run did not stress buffer depletion.
