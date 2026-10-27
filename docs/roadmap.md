# Product and routing work order

The work below is planned, not shipped. Deliver each as an independently tested
branch and Draft PR; do not combine the whole roadmap into one implementation PR.

| Order | Track | Deliverable | Depends on |
|---|---|---|---|
| 1 | Product | Inspect/confirm/correct memory with history in the M1 flow | Workflow setup |
| 2 | Research | Versioned pilot dataset manifest, labeling rubric and frozen conversation splits | M1 contracts |
| 3 | Shared infrastructure | Live provider evaluation harness and fixed small/strong baselines | Dataset |
| 4 | Research | Cascade vs fixed/random/heuristic study with measured quality/cost/latency | Baselines |
| 5 | Product | Final transcript/voice entry and session resume, initially on stable policy | M1 + failure UX |

Routing promotion is a separate decision after the evaluation gate. Learned
policies, agent topology selection and best-of-N are later experiments, not
requirements for the first usable product slice.

See CONTRIBUTING.md, docs/product/m1.md and docs/research/protocol.md.
