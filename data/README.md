# Research data

`raw/<query-hash>/<content-sha256>.json` contains immutable response envelopes: endpoint, query parameters, retrieval timestamp and the complete parsed OpenRouter response including source metadata. Filenames are SHA-256 checksums of the exact saved bytes. No API keys or authorization headers are saved.

`derived/index.json` is the reproducible validated dashboard dataset; `public/data/index.json` is its deployment copy. Run `python scripts/pipeline.py rebuild` to regenerate both from snapshots. Arithmetic uses exact Python integers for token/request sums; counts are serialized as decimal strings. Ratios and visualization use floating point approximations.

Data source: OpenRouter. Dataset response attribution is recorded per query in the generated index and in each raw `payload.meta.as_of`. Licensed under CC BY 4.0 for the aggregated dataset endpoints. Model catalog snapshots retain their original metadata and pricing strings; they are forward-looking observations, not historical billed spend.
