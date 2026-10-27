# Hierarchical extraction routing

This implementation is an engineering baseline inspired by model routing and
cascades, not a reproduction of any paper or a trained router.

## Implemented

`Tier` registers ordered providers and declared cost units. `CascadeRouter` uses
an interchangeable policy's `select(features, tiers)` to choose a starting index,
then attempts each subsequent tier until the quality gate accepts. The default
policy selects rules for entirely explicit commands, skips to the top tier for
caller-marked complex requests, and otherwise starts at the first model tier.
A custom learned policy can implement the same interface; none has been trained.

The default gate validates schema and exact evidence and detects missing explicit
`remember` records. An empty output without an explicit command is unresolved and
escalates; this may waste calls on ordinary chatter. It does not measure semantic
correctness, negation, contradictions or natural-language recall. Implement a
calibrated `check(text, records)` gate to extend it. Verifier model calls must be
accounted separately if added; the built-in gate makes no model calls.

Budgets limit provider calls and cumulative declared cost units. Units are
configuration estimates, not currency or provider billing. They are charged even
for failed calls. The elapsed-time deadline is checked before/after provider
calls; it **does not preempt** a blocking provider. Configure provider timeouts
and worker leases appropriately. Overdue output is rejected. There is no
parallel speculative execution, hard process cancellation or budget across task
retries; each retry is a new routed request with its own limits and audit row.

Every success or handled cascade exhaustion has a trace: request ID, input hash,
feature counts, policy/gate versions, attempts, elapsed times, estimated costs,
error classes and final status. No transcript or provider error message is copied
to this audit log. Successful results retain traces in task results; `AuditLog`
persists failure traces too. Audit write failure fails the operation rather than
silently dropping observability. Existing default routing remains available.

## Run

Offline rules-only cascade:

```sh
PYTHONPATH=src python3 -m voice_context.gateway --db context.db --cascade
```

To register already-installed Ollama models, substitute real local model names:

```sh
PYTHONPATH=src python3 -m voice_context.gateway --db context.db --cascade \
  --model SMALL_MODEL --standard-model MEDIUM_MODEL --reasoning-model STRONG_MODEL \
  --route-cost-units 20 --route-deadline 45
```

No models are downloaded by these changes. Default model-tier costs are 1, 3 and
8 arbitrary units; Python callers can supply calibrated values using `Tier`.
The original JSON-lines `submit/work/status/approve/context` commands work with
this mode. Final results are candidates; explicit confirmation is still required
for memory writes. Realtime voice replies are not passed through this cascade.
The gateway's SQLite `routing_audit` table retains failure and success traces.

## Controlled experiment

```sh
PYTHONPATH=src python3 experiments/routing.py
```

100 requests use explicit command fixtures and scripted provider capacities.
These are not LLMs; the gate can directly inspect explicit commands. This is a
control-flow test, not a measure of semantic quality or real savings.

| Policy | Complete correct outputs | Unresolved | Provider calls | Declared units |
|---|---:|---:|---:|---:|
| Always small | 60 | 40 | 100 | 100 |
| Always strongest | 100 | 0 | 100 | 800 |
| Random single model | 81 | 19 | 100 | 394 |
| Heuristic single call | 80 | 20 | 100 | 200 |
| Heuristic plus cascade | 100 | 0 | 120 | 260 |

Raw results: `experiments/routing-results.json`. No cost reduction or latency
improvement on real models is claimed. Forty total tests include upgrade paths,
exceptions, budget stops, late-result rejection, durable failure audits and
pipeline integration.

## Research grounding and next experiment

- [RouteLLM (2024)](https://arxiv.org/abs/2406.18665): learned pre-call routing;
  use as a future baseline after collecting domain-specific labeled outcomes.
- [FrugalGPT (2023)](https://arxiv.org/abs/2305.05176): quality-gated cascades.
- [Unified routing and cascading (2024)](https://arxiv.org/abs/2410.10347):
  combine pre-call decisions with output-based continuation.
- [MasRouter (ACL 2025)](https://aclanthology.org/2025.acl-long.757/):
  collaboration, role and model selection; agent topology selection is not implemented here.
- [BEST-Route (2025)](https://arxiv.org/abs/2506.22716): model plus sample-count
  decisions; best-of-N sampling is not implemented here.
- [LLMRouter (2026 preprint)](https://arxiv.org/abs/2608.06867): broader multi-turn
  and memory-oriented routing; useful for future state representation.
- [LLMRouterBench (2026 preprint)](https://arxiv.org/abs/2601.07206): motivation
  for retaining simple fixed and heuristic baselines.

Next collect real, source-labeled memory extraction tasks and evaluate every
candidate model on identical inputs. Split train/calibration/test by conversation,
not adjacent turns. Include extraction coverage, unsupported claims, contradictions,
branch leakage, total tokens/compute and p95 latency including routing/verifier
work. Calibrate thresholds on held-out data, then compare fixed models, random,
heuristic, cascade and learned policies. Serving multiple school-GPU models and
training/calibrating a router remain future work; no such result is fabricated.
