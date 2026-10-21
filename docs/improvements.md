# AI Tracking — Potential Improvements

Candidates for improving the tool and its workflow, ordered roughly by impact. Each item says what the change is, why it matters, and how to do it. Items are grounded in the current code (`fetch.py`, `ideas.py`) and the design spec (`monitoring-strategy.md`).

## Status

Implemented (2026-10-20):

- **1.1** Layout — `fetch.py` moved to the project root next to its data files; `docs/` now holds only documentation.
- **1.2** Scheduling — `run.ps1` runs `fetch.py` + `ideas.py`; README scheduler entries updated (task itself not created).
- **2.1** Concurrent fetching via `ThreadPoolExecutor` (6 workers).
- **2.2** Conditional GET — per-source `etag`/`last_modified` stored in `state.json["meta"]`, `304` → no refetch.
- **2.3** Broader retries — 429/5xx with backoff + `Retry-After`, TLS-fallback preserved.
- **3.1** Keyword taxonomy — 12 tags stored on each item in `items.json`, rendered in `digest.md`, surfaced to `ideas.py`.
- **6.1** Tests — `tests/test_fetch.py` (29 stdlib `unittest` cases): parsers, clustering/dedup, tags, story tags, HTTP retry/304. Run with `python -m unittest discover -s tests -t .`.
- **Layout** — restructured to `data/` (state + rolling window), `output/` (generated markdown + site), `references/` (csv + sites.txt); shared `paths.py` centralizes all path references in `fetch.py`/`ideas.py`; `.gitignore` added.
- **Static site** — `site/` is an Eleventy project (`npm run build`): home dashboard, per-date digest/stories/ideas pages, all-items list, per-tag and per-source pages. `site/sync.mjs` feeds the pipeline output into content. `run.ps1` chains fetch → ideas → site build.

## 1. Immediate fixes (correctness / fragility)

### 1.1 Resolve the layout mismatch between `fetch.py` and its data files
`fetch.py` resolves every path relative to the script directory (`BASE = Path(__file__).resolve().parent`, `fetch.py:15`), so it expects `sources.json`, `state.json`, `items.json`, `digests/`, and `stories/` next to it. Right now the script lives under `docs/` while the data files and output directories sit at the repo root — and the README/scheduler reference a root-level `fetch.py`. Running the tool as documented will fail.

- Decide on one canonical layout: either move the scripts next to the data, or make paths configurable (`--data-dir`, defaulting to `BASE`).
- Update the README "Quick start" and the Task Scheduler/cron entries to match the real path.
- This is the cheapest fix and the one that most directly breaks daily operation.

### 1.2 Schedule `ideas.py`, not just `fetch.py`
The README scheduled task (`README.md:108`) runs only `fetch.py`. `ideas.md` therefore goes stale unless someone runs `ideas.py` by hand. Add a second task, or a tiny `run.ps1`/`run.cmd` that runs `fetch.py` then `ideas.py` and schedule that instead. `ideas.py` already errors helpfully if the window is empty (`ideas.py:200`), so chaining is safe.

### 1.3 Same-day re-runs overwrite the dated archive
Both scripts write `digests/YYYY-MM-DD.md`, `stories/YYYY-MM-DD.md`, `ideas/YYYY-MM-DD.md` by simple overwrite (`fetch.py:479`, `ideas.py:179`). This is documented ("built for a daily cadence") but any second run — retry after a partial failure, mid-day check — destroys the first run's record. Options: append a run counter/timestamp (`YYYY-MM-DD--HMM`) or keep the day file but only write it on the first run of the day.

## 2. Reliability & performance (`fetch.py`)

### 2.1 Fetch sources concurrently
Sources are fetched sequentially, each with a 30s timeout and a 3s sleep on 429 (`fetch.py:45-62`). Worst case ~16 sources × (timeout + retry) is minutes of wall time. Use `concurrent.futures.ThreadPoolExecutor` (still stdlib) with a small pool (4–8) and keep per-source timeouts. Fetching is I/O-bound, so threads are fine.

### 2.2 Conditional GET / caching
The strategy calls for `ETag` / `Last-Modified` on feeds (`monitoring-strategy.md:88`), but the fetcher always pulls the full body. Store per-source `etag`/`last_modified` in `state.json` and send `If-None-Match` / `If-Modified-Since`; treat `304 Not Modified` as "no change". Cuts bandwidth, latency, and the chance of tripping rate limits.

### 2.3 Broader retry/backoff than 429-only
Only HTTP 429 gets one retry (`fetch.py:51-55`). Add:
- Retry on `ConnectionResetError`, `TimeoutError`, and 5xx with a short exponential backoff (1s, 2s, 4s, capped).
- Respect `Retry-After` when present.

### 2.4 Reddit OAuth
Reddit currently fails with `403 Blocked` for unauthenticated datacenter IPs (documented in `README.md:119`); the entries are wired but unauthenticated. Implement the OAuth client-credentials flow (public `client_id`/`client_secret` from a script app in `.env`) and send `Authorization: Bearer` on the JSON requests. Cheap to add, unlocks two tier-2 sources.

### 2.5 Scrapers / sitemap-diff for the RSS-less tier-1 sources
`monitoring-strategy.md:40-48` lists OpenAI, Anthropic, Meta AI, Papers with Code (and tier-3 Qwen, DeepSeek) as having no reliable RSS. These are exactly the "don't miss" sources and are currently absent from `sources.json`. Add a `"type": "sitemap"` (or HTML-diff) source kind that:
- fetches the sitemap,
- collects `(title, url)` pairs,
- emits only new ones, honoring a polite `<1 req/min` rate.

A sitemap-diff is far more robust than CSS scraping and needs no per-page selectors.

### 2.6 Harder dedup that survives `guid` changes
Dedup keys are `f"{sid}::{guid}"` (`fetch.py:519`) against a per-source `seen` list capped at 1000 (`fetch.py:526`). If a feed changes its `guid` format, every old item re-appears as "new" and the cap means older keys fall out entirely. Add a content-hash fallback key (e.g. sha1 of `canonical_url(title, link)`) so near-identical items collapse, and make the seen-window time-based (e.g. keep 30 days) rather than a raw count.

## 3. Close the gap between `monitoring-strategy.md` and the implementation

The spec describes a substantially richer system than what ships. The highest-value theme is implementing the parts of the strategy the code doesn't yet have:

| Spec feature | Spec reference | Status |
|---|---|---|
| Keyword taxonomy tagging | `monitoring-strategy.md:100-101` | Not implemented |
| Scoring + freshness decay | `:103-106` | Not implemented |
| Trigger rules (breakthrough / opportunity / watch) | `:111-114` | Not implemented |
| Tiered cadence (sub-hour / daily / weekly) | `:23-31` | Not implemented — every run fetches everything |
| Real-time alerts | `:118-120` | Not implemented |
| Weekly synthesis | `:122` | Not implemented |
| RSS-less scrapers | `:40-48, 70-75` | Not implemented |
| Reddit OAuth | `:64` | Not implemented |

### 3.1 Keyword taxonomy tagging
Tag every item with one or more of the strategy's taxonomy (`agents`, `RL`, `multimodal`, `vision`, `reasoning`, `inference`, `evals`, `synthetic data`, `distillation`, `safety`, `open-source`, `hardware`, `policy`, `funding`) by scanning title + summary. Store tags on items in `items.json`; render them in the digest and let `ideas.py` see them. Turns free-text into queryable structure.

### 3.2 Scoring + trigger flags
Implement `score = source_weight × (1 + engagement_boost) × freshness_decay` (`monitoring-strategy.md:103-106`), then surface the strategy's trigger rules:
- **discovery/breakthrough**: new arXiv paper echoed by a frontier-lab/blog and a benchmark entry within ~7 days.
- **opportunity**: funding/product launch + personnel moves + open-weight release.
- **watch/contrarian**: high-engagement community item that disagrees with a tier-1 announcement.

These can be computed as extra story tags / a "high-signal" section at the top of the digest rather than a separate pipeline. Clustering infrastructure (`build_stories`) already exists — the rule logic is the missing part.

### 3.3 Tiered cadence
Add a per-source `cadence` field (`hourly` | `daily` | `weekly`) to `sources.json` and a `last_fetched` timestamp in `state.json`. Skip sources whose next fetch isn't due yet. This honors the strategy's cadence table, reduces load on slow sources (SemiAnalysis, Quanta, MIT TR), and lets fast sources be polled more often without hammering everything each run.

### 3.4 Alerts (optional, opt-in)
Add a tiny notifier (ntfy.sh, Discord/Slack webhook, or email) that fires on:
- any tier-1 frontier-lab post or model release,
- a `discovery`/`opportunity` story tag,
- fetch errors.

Keep it opt-in via `.env` keys so the tool stays dependency-free by default. This is the piece that turns a daily digest into the strategy's "seen within 24h" guarantee.

### 3.5 Weekly synthesis
The strategy wants a weekly long-form rollup ("new relationships noticed", paper↔model↔company↔person). Build it as a `--weekly` mode on `ideas.py` (or a `weekly.py`) that reads the full 14-day window + archived `stories/` and emits a comparison of what clustered *this week* vs. last. Cheap to add once item tags (3.1) exist.

## 4. Clustering & signal quality

### 4.1 Scale the token-pair index
Clustering builds a `set` of all co-occurring index pairs from the token index (`fetch.py:288-297`). A stopword-filtered token shared by many items (e.g. "learning") generates O(k²) pairs; with 4000 items this can balloon. Mitigations:
- Cap pairs per token bucket (e.g. sample/drop tokens shared by >200 items),
- only union when both items have ≥4 tokens (already gated in `items_linked`),
- or switch to a MinHash/LSH over token sets so near-duplicate detection is sub-quadratic.

### 4.2 Better title similarity
`TITLE_SIM = 0.4` is a fixed Jaccard over raw unigram sets (`fetch.py:32`, `:248-250`). Add light stemming and common-word weighting so "fine-tuning vs. fine tune" and "Mamba-2 vs. Mamba 2" still cluster; today they don't. A cheap normalization pass on `tokenize()` would lift recall without a real embedding model.

### 4.3 `canonical_url` strips all query params
`canonical_url` (`fetch.py:210-218`) drops the query string entirely, so distinct URLs differing only by a meaningful query collapse into one `url_key`. Keep known-tracking params stripped (`utm_*`, `ref=`, `fbclid=`, `gclid=`) but preserve the rest, or treat "no-query ≠ query" as separate keys.

### 4.4 Log & surface fetch errors persistently
Errors currently go to stdout and the digest tail only (`fetch.py:462-467`). Write them to a `errors.log` (or `state.json["last_errors"]`) so a quiet scheduler failure is visible later, and expose a `--last-status` / summary line. Pairs with 3.4 alerting.

## 5. `ideas.py` improvements

### 5.1 Skip the call when nothing changed
Each run spends tokens even if the window and stories are identical to the last ideas run. Compare a cheap fingerprint (count + newest `fetched_at` + max story title) against a stored one in `state.json`; if unchanged, exit early with "nothing new — skipping" and leave `ideas.md` untouched. Saves money and noise on unchanged days.

### 5.2 Handle truncation / empty-content properly
The empty-content guard already exists (`ideas.py:164-165`) and flags `finish_reason=length`, but there's no retry or fallback. Add:
- retry with backoff on transient OpenRouter errors (429/5xx),
- on `finish_reason=length`, retry once with a smaller context (raise `--days`-style pruning or drop stories) rather than failing,
- surface `max_tokens`/usage in the output header so cost is visible.

### 5.3 Close the loop: fold "watch items" back into the pipeline
The ideas output has a "Watch items" section, but nothing feeds them back. Add a mechanism to promote watch items into source keyword filters (e.g. a `watch.json` that `fetch.py` merges into HN/community keyword matching), so the tool starts tracking what it told you to watch. This is the one improvement that makes the tool self-improving rather than report-only.

### 5.4 Consistent date handling between the two scripts
`fetch.py` prunes the window by `fetched_at` (`fetch.py:409-417`) while `ideas.py --days N` filters by `published` (falling back to `fetched_at`) (`ideas.py:75-83`). Align on one timestamp (use `published` for the window, `fetched_at` only as fallback) so `--days 7` matches what's actually in the window.

## 6. Workflow / ops

### 6.1 Tests for the core logic
The parsers (`parse_feed`, `parse_hn`, `parse_reddit`, `parse_hf`), clustering (`cluster_items`, `items_linked`), and dedup are pure functions with no coverage. Add a `tests/` directory with fixture-based tests for each parser and a handful of clustering/dedup cases. This is high-leverage: a change to dedup or clustering (2.6, 4.1, 4.2) can silently change every story without any red flag today.

### 6.2 Version the config and track outputs
The directory isn't a git repo. Per the workspace convention, real code should get `git init`. At minimum, commit `sources.json`, `.csv` reference files, and the scripts; gitignore `state.json`, `items.json`, generated `*.md`, `digests/`, `stories/`, `ideas/`, `.env`. This makes config changes reviewable and gives a history of source drift (added/removed sources).

### 6.3 One runner for the whole workflow
Currently `fetch.py` and `ideas.py` are two separate invocations with different flags. A single `run.py` (or `run.ps1`) that runs fetch → (optional) ideas, with `--ideas` / `--flash` / `--no-ideas` flags, simplifies the scheduler, CI, and ad-hoc use, and gives one exit code to monitor.

### 6.4 Resolve the "Prefer NodeJS" convention note
`AGENTS.md` says prefer NodeJS, but the tool is deliberately Python-stdlib-only (README "Requirements"). Either keep Python and note the deliberate exception in `AGENTS.md`, or plan a rewrite (the logic is small; a Node port would also make the webhook/alerting integration and JSON handling marginally easier). This is a decision to make explicitly, not a blocker.

## Quick wins vs. bigger projects

| Effort | Items |
|---|---|
| **Small** | 1.1 layout fix, 1.2 run `ideas.py` on schedule, 1.3 archive overwrite, 2.3 broader retries, 5.1 skip-unchanged, 4.4 error logging |
| **Medium** | 2.1 concurrency, 2.2 conditional GET, 2.4 Reddit OAuth, 3.1 taxonomy tagging, 3.3 tiered cadence, 5.2 truncation retry, 6.1 tests |
| **Large** | 2.5 scrapers, 3.2 scoring/triggers, 3.4 alerts, 3.5 weekly synthesis, 4.1/4.2 clustering overhaul, 5.3 watch-loop, 6.2 git init |

Recommended order: 1.1 → 1.2 → 6.1 → 2.1/2.2/2.3 (fetch reliability) → 3.1/3.3 (structure + cadence) → 3.2/3.4 (signal + alerts) → 2.5/3.5 (coverage + synthesis).
