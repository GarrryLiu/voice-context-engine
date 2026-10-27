# Candidate extraction

Default execution uses `RuleExtractor`, not a real model. It recognizes explicit
full lines `remember key: value` and returns extractive candidates. Other prose
produces no candidates. This makes the local end-to-end path deterministic.

`ExtractionRouter` accepts providers implementing `name` and `extract(text)`.
Configure `small` and `reasoning` independently; the labels are policies, not
claims about the models actually used. Optional fallback must be supplied
explicitly and is recorded in the result. No model cost savings are measured.

To use an already-running Ollama server and installed model:

```python
from voice_context.models import ExtractionRouter, OllamaExtractor
router = ExtractionRouter(providers={
    'small': OllamaExtractor('your-installed-model'),
    'reasoning': OllamaExtractor('your-installed-model'),
})
result = router.extract('We decided to use PostgreSQL for persistent memory.')
```

The [official Ollama chat API](https://docs.ollama.com/api/chat) defines the
non-streaming request and JSON output used by the adapter. Only transport mocks
were tested here; no Ollama server/model was installed or invoked in this work.
The adapter has a per-request timeout and a maximum response size. Queue retries
handle exceptions; there is no token-price budget, stream cancellation or provider
health-based routing yet. Configure endpoints as trusted application settings.

Every value must appear verbatim in evidence that appears verbatim in the source
transcript. This rejects unsupported generated text, but cannot establish truth,
negation handling, relevance or resistance to prompt injection. The pipeline
persists candidates for caller approval before memory writes. Keep model-derived
candidates distinct from user-confirmed memory.
