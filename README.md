# Agent Token Index

**Tracking the rise of machine-consumed intelligence.** A static research dashboard built from OpenRouter public aggregate telemetry.

- Website: https://harni555.github.io/agent-token-index/
- Repository: https://github.com/harni555/agent-token-index
- Refresh: Mondays at **12:00 UTC** (08:00 EDT / 07:00 EST), plus manual **Refresh data** workflow.

## What this measures

| Series | Source subcategories | Aggregation |
|---|---|---|
| PATI | `personal-agent` | Distinct canonical app IDs |
| CATI | `cli-agent`, `cloud-agent` | Union, deduplicated by canonical app ID |
| BAWI | All three above | Union, deduplicated by canonical app ID |
| IDE comparison | `ide-extension` | Separate series, excluded from BAWI |

These series overlap; PATI + CATI can exceed BAWI if an app belongs to both. No hand-curated label guesses are made. Category membership comes from the source filter **at retrieval time**, not a verified point-in-time taxonomy. Historical rankings may reflect current categories and canonical aliases. Conflicting counts for an overlapping app fail validation rather than being silently summed.

## Data sources and coverage

Official contract: https://openrouter.ai/docs/cookbook/administration/data-api

1. `GET /api/v1/datasets/rankings-daily`: daily top 50 public models plus `other`, token totals as decimal strings. Calendar-month requests backfill January 1, 2025 through the latest complete Sunday. All daily rows form the platform denominator and platform model mix.
2. `GET /api/v1/datasets/app-rankings`: one request per subcategory and weekly date window using `sort=popular&limit=100&offset=0`. If full, retrieve `offset=100`. The documented offset ceiling is 100; we do **not** pretend this is unlimited pagination. A full second page marks the affected series as capped and a lower bound.
3. `GET /api/v1/models`: current catalog with pricing strings, captured on each refresh. No historical list prices or realized spending are inferred.

The dataset endpoints require an OpenRouter API key. No inference is requested. Documented dataset quotas are 30 requests/minute/key and 500/day/account. The collector spaces requests by at least 2.15 seconds and has a conservative 450-call run budget. Other uses of the same account consume its quota too. HTTP 429 stops the run and preserves progress; retry after the provider's quota reset. Requests time out after 60 seconds and transient connection/5xx failures retry up to four attempts. HTTP 401 and schema errors fail immediately.

The initial backfill can exceed one day's quota if many subcategories need second pages. Run **Refresh data** again after quota reset; cached historical windows resume without recollection. No partially completed backfill replaces the live dataset. Last four weeks are fetched again on each refresh to capture restatements; older raw windows remain cached. Month-level model windows overlapping that interval are refetched. Delete nothing to force revisions: add an explicit force policy and preserve original snapshots.

## Formulas

Weeks are Monday–Sunday UTC, both endpoints inclusive. Only completed weeks enter charts, indices, growth, and moving averages. The first partial source window, January 1–5, 2025, is retained for provenance. The current partial week is excluded.

- **Weekly tokens**: sum of prompt + completion tokens for distinct observed canonical apps in the series.
- **Requests**: sum of reported `total_requests` over the same app union.
- **Tokens/request**: token sum / request sum; undefined for zero requests.
- **Normalized index**: 100 × weekly tokens / baseline. Baseline is mean weekly tokens across all three fully contained January 2025 weeks (Jan 6–12, 13–19, 20–26), only if all have positive observations. Otherwise use the first available positive complete week. Each series has its own baseline and label.
- **WoW growth**: 100 × (W / W−1 − 1).
- **4-week growth**: 100 × (W / W−4 − 1); this is not growth between rolling four-week sums.
- **4-week MA**: trailing arithmetic mean of four consecutive complete weekly observations. No interpolation or skipping missing weeks.
- **Observed agent share**: 100 × observed series tokens / same-window public OpenRouter rankings tokens including `other`. A result outside 0–100% fails publication because it indicates population/schema mismatch.

Missing or empty category responses remain unavailable rather than assumed zero. All subcategories in a union must have observations for its aggregate to be displayed. This conservative rule can withhold a broad index when one category has no historical records. Genuine reported zero counts are retained. Undefined growth (including a zero denominator) is null. Python uses exact integers for sums; serialized counts are strings. Ratios and browser charts use floating point approximations.

## Limitations

- OpenRouter is one venue, **not a global inference census**.
- App attribution is opt-in; unattributed, hidden and private apps are not measured. Coverage and changing composition can drive growth.
- Rankings are capped. Even uncapped observed app totals do not cover unattributed usage.
- Current taxonomy applied to historical queries can introduce reclassification and survivorship bias. No point-in-time category claim is made.
- Model rankings exclude private models, private endpoints and zero-data-retention traffic. The denominator is the **published public dataset**, not all OpenRouter activity.
- Platform model mix is **not agent-only model mix**. The selected app series does not change its population.
- Providers use different tokenizers. Input repetition, context lengths, caching, retries, free models and routing can change totals without equivalent changes in economic activity.
- **Token growth does not equal vendor revenue, spending, intelligence quality or productivity.** Catalog prices are neither historical prices nor actual transaction prices. No spend chart is fabricated.
- Upstream historical aggregates can be revised. `meta.as_of` is source response time, not a guarantee of immutable historical truth.

## Architecture and files

The frontend is Vite + plain ES modules/CSS/SVG, with no application server or API credentials in the browser. Its complete static output lives in `dist/`. Charts support 3M/6M/1Y/All, raw/normalized, weekly/4-week MA, and an optional IDE overlay. Click a chart week or use the keyboard-accessible week selector to inspect its metrics and app/model rankings. Filter state persists in the URL. Responsive layouts include stacked cards and scrollable data tables. A dynamic freshness indicator becomes stale when the data-through date is more than nine days old.

```
scripts/pipeline.py       collection, snapshots, validation, derivation
data/raw/                append-only hashed response envelopes
data/derived/index.json  validated series and source metadata
public/data/index.json   deployable copy (bootstrap is explicitly empty)
src/                     interface and charts
tests/                   synthetic unit fixtures only; never published as data
.github/workflows/       scheduled collection and static deployment
```

Every snapshot contains its endpoint, query parameters, retrieval timestamp and entire parsed response, including source `meta`. The filename hashes its saved bytes. Replay verifies checksums before derivation. Rebuilding requires all historical weekly app windows and all model days; it refuses gaps, malformed integers, mismatched response windows, duplicate rows, conflicting overlaps, or invalid shares. A validated candidate replaces derived outputs atomically per file, only after the full computation succeeds.

## Development

Requires Node **22.12+** and Python **3.10+**. Python has no external dependencies.

```sh
npm ci
npm test
npm run validate
npm run dev
npm run build
```

To collect locally, set `OPENROUTER_API_KEY` securely in the process environment; `.env` files are ignored but not automatically loaded. Prefer Actions so the key stays in GitHub Secrets.

```sh
python scripts/pipeline.py refresh
python scripts/pipeline.py rebuild
python scripts/pipeline.py validate --require-fresh
python scripts/pipeline.py prices
```

`prices` alone records today's catalog without requiring a dataset key. `rebuild` uses existing snapshots without network calls and requires coverage through the current latest completed Sunday. The bootstrap dashboard intentionally passes structural validation while showing no data; it never passes `--require-fresh`.

## Deployment and automation

1. Repository Settings → Secrets and variables → Actions: add **OPENROUTER_API_KEY**.
2. Settings → Pages → Source: **GitHub Actions**.
3. Actions → **Refresh data** → Run workflow. This performs tests, backfill/refresh, validation, index rebuild, production build, commits source snapshots and derived data, uploads evidence, and deploys Pages.
4. Mondays at 12:00 UTC repeat automatically. GitHub schedules can be delayed; public-repository scheduled workflows can be disabled after prolonged inactivity. Check Actions periodically and re-enable if necessary.

`Validate and deploy site` runs on source changes and manual dispatch, with validation on PRs but deployment only from main. Both workflows share a non-cancelling concurrency group, preventing data/code publication races. Data commits made with `GITHUB_TOKEN` do not recursively trigger workflows; the refresh workflow deploys its own built artifact. Only the refresh step receives the OpenRouter key. GitHub token permissions are restricted to repository data commits and Pages/OIDC deployment. No secrets are stored in snapshots or browser assets.

**Failure behavior:** upstream/auth/quota/schema/staleness failures block refresh deployment and retain the last good website. Already collected raw snapshots are committed even after a collection failure, and evidence is retained as an Actions artifact for 30 days. Failed candidate series are not promoted. Site-only source fixes can still deploy an existing snapshot; its visible freshness indicator continues to disclose its age.

## Maintenance

- Inspect failed runs under Actions; check authentication, provider quota, response-contract changes and incomplete windows.
- Rotate the secret in GitHub; never put keys into issues, commits or logs.
- When changing classification/formulas, version the methodology, add meaningful fixture tests and rebuild; do not overwrite raw history.
- Monitor repository size. The catalog is a forward price snapshot; weekly full copies and raw backfill may eventually warrant an archival storage tier while retaining hashes and manifests.
- For price research, use catalog `fetchedAt`, model ID, original pricing dimensions and currency/unit definitions. Future spending analysis needs time-aligned usage dimensions and realized billing evidence, not total tokens × today's advertised price.

## Attribution

Source: OpenRouter (openrouter.ai/apps), as of each response's `meta.as_of`.

Source: OpenRouter (openrouter.ai/rankings), as of each response's `meta.as_of`.

Aggregated dataset content is licensed under **CC BY 4.0**. Exact per-query timestamps are retained in `data/raw` and the derived `sources` array, with latest source timestamps displayed in the footer. This independent dashboard is not an official OpenRouter product.
