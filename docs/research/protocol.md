# Routing research protocol v1

Question: can adaptive routing reduce total inference resources while preserving
source-backed memory quality and staying within the task's latency budget?
This is not a request to optimize price without quality constraints.

## Dataset setup

Begin with a proposed pilot of 100 labeled extraction tasks; this dataset does
not exist yet. Include no-decision chatter, explicit decisions, corrections,
negation, long context, cross-session references and branch contradictions, in
English and Chinese. Use consented or appropriately licensed material. Mark
synthetic examples separately. Do not upload personal conversations by default.

Each JSONL record should contain:
`id`, `conversation_id`, `session_id`, `branch_id`, `split`, `text`,
`source_description`, `synthetic`, `expected_records` and `notes`.
Expected records contain stable key, value and exact evidence. Label acceptable
variants and deliberately absent memories. Use the same memory snapshot for all
models on a task. Record and hash that snapshot.

Split by conversation into train/calibration/test; freeze IDs before threshold
selection. Do not tune on test outcomes. Keep private/raw data out of Git when
required; commit manifests and hashes instead. Have a reviewer resolve ambiguous
labels; record explicit self-review when a second reviewer is unavailable.

## Comparison setup

Use identical prompts, input snapshots, output caps and frozen model versions.
Evaluate fixed small, fixed strong, seeded random, heuristic single-call and
cascade. Add a learned router only after collecting training labels. Retain raw
per-request responses, failures, route decisions and provider usage.

Report coverage, unsupported/contradicted claims, branch leakage, empty-output
handling, task completion, upgrade rate and p50/p95 total latency. Count router,
verifier, retries and failed calls. Separate billed API cost from local GPU time;
use declared units only in explicitly synthetic control-flow experiments.
Alternate condition order and repeat measured runs. Publish uncertainty and
negative results. Report generation budgets and model/context truncation.

## Promotion gate

Before evaluating, agree numeric quality non-inferiority and latency thresholds
for the product task, using the calibration split. Those numeric thresholds are
still undecided; no policy is eligible for default promotion until they are set.
A new policy stays opt-in. Propose a separate rollout PR only after the frozen
held-out evaluation meets quality and latency requirements and improves measured
resource use. Include rollback to the prior policy.

## First artifacts

1. Dataset manifest and labeling rubric (no real conversations committed yet).
2. Real small/strong model outputs and fixed-model baselines.
3. Cascade results under the same workload and budget.
4. Decision record using [run template](run-template.md).

Existing `experiments/routing.py` uses scripted providers and arbitrary units;
it is a regression fixture, not evidence for the promotion gate.
