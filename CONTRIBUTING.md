# Development workflow

Track product and research work separately, connected through shared provider,
candidate, routing-trace and memory APIs. Start with an issue describing the
problem and observable acceptance criteria.

1. Branch from current `main`: `product/<topic>`, `research/<topic>`, or
   `infra/<topic>`. Push the branch and open a Draft PR early. Do not push feature
   work directly to `main`.
2. Keep each PR independently reviewable and runnable. Link its issue and state
   dependencies. Prefer additive interfaces and feature flags for experiments.
3. Run the checks below. Provide product examples for product changes and
   reproducible data/config/results for research changes.
4. Mark the PR ready after acceptance criteria pass. Review behavior, source
   attribution, data handling, tests and limitations. A solo maintainer may
   self-review explicitly; do not invent a second reviewer.
5. Merge through GitHub after CI passes and review is recorded. Squash merging
   is the recommended convention; do not rewrite previously shared history.

These are repository conventions. Branch protection and merge-method settings
are not automatically enforced by the files in this PR. Until configured in
GitHub Settings, the maintainer is responsible for following them.

## Local verification

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m voice_context
PYTHONPATH=src python3 experiments/run.py --output /tmp/structured.json
PYTHONPATH=src python3 experiments/end_to_end.py --output /tmp/end-to-end.json
PYTHONPATH=src python3 experiments/routing.py --output /tmp/routing.json
```

CI runs these checks on Python 3.11–3.13, plus source compilation, and uploads
per-version experiment artifacts. Offline synthetic results test control flow;
they are not proof of live model quality or savings.

Product acceptance: [M1 specification](docs/product/m1.md).
Research acceptance: [evaluation protocol](docs/research/protocol.md).
Work order: [roadmap](docs/roadmap.md).
