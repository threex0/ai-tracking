# AI Tracking — Improvement Roadmap

A phased plan for `ai-tracking`. It builds on what's already shipped (see
`docs/improvements.md` for the full itemized list with rationale) and sequences
work by value-per-effort and dependency order. Effort: **S** small, **M**
medium, **L** large.

## Current state (what's already in place)

- Concurrent multi-source fetcher (`fetch.py`): feeds/arXiv/HN/Reddit/HF, conditional GET, retries, dedup, cross-source clustering, keyword-taxonomy tags.
- LLM opportunity synthesizer (`ideas.py`, DeepSeek via OpenRouter).
- Rolling 14-day window (`data/items.json`), per-source state (`data/state.json`).
- Eleventy static site (`site/`), plus a machine-readable artifact (`output/latest.json`).
- Daily CI pipeline (`.github/workflows/daily.yml`): fetch → ideas → export → site build → commit artifact. Public repo, artifact served at a raw GitHub URL.
- vramdb integration consumes `latest.json` (external).
- Tests: 34 stdlib `unittest` cases.

Known gaps this roadmap closes: RSS-less tier-1 sources missing, no per-source
cadence, no scoring/triggers, no alerts, no week-over-week view, silent errors.

---

## Phase 0 — Stabilize & close coverage gaps (complete 2026-10-21)

All Phase 0 items are done — the table is retired.
Done (2026-10-21):
- Reddit switched to Old Reddit RSS (`.rss`) — no OAuth, no 403s.
- **0.1** Sitemap-diff scrapers: OpenAI, Anthropic, DeepSeek wired via `type: "sitemap"` (sitemapindex recursion, `url_filter`, polite title fetch, dedup-before-title). Qwen/Meta/PwC have no usable sitemap and are skipped (may need scraping).
- **0.2–0.4** Persistent `data/errors.log` + `fetch.py --strict`; `ideas.py` skip-when-unchanged (fingerprint + `--force`) and retry/backoff with truncation retry.
- **0.5** CI cache uses a per-run key + `restore-keys` (rolling window persists), cache-hit status step, and opt-in `NOTIFY_URL` failure webhook.

Exit criteria: tier-1 RSS-less labs covered (OpenAI/Anthropic), failed runs are loud (webhook + strict + error log), ideas step is idempotent/cost-aware.

---

## Phase 1 — Signal quality (weeks 2–3)

Make the output more discriminating before adding more surface area.

| # | Item | Why | Effort |
|---|------|-----|--------|
| 1.1 | **Item scoring + trigger flags** (implements `monitoring-strategy.md:103-114`) — `score = source_weight × (1+engagement) × freshness`, then `discovery`/`opportunity`/`watch` flags | Tags already exist; this is the highest signal multiplier still missing | M |
| 1.2 | **Tiered cadence** (`cadence` field per source + last-fetched in state) | Honors the strategy's sub-hour/daily/weekly table; reduces load on slow sources; enables faster polling of frontier labs | M |
| 1.3 | **Clustering quality**: stem/weight tokens, fix `canonical_url` query handling, cap token-pair index | Better stories (the core "relationships" feature) | M |
| 1.4 | **Watch-item loop** — promote `ideas.py` "watch items" back into source keyword filters / new sources | Closes the loop; the tool starts tracking what it told you to watch | M |
| 1.5 | **Taxonomy v2**: synonyms, per-tag keywords on sources, tag confidence | Cleaner tags → better scoring (1.1) and site browse | S–M |

Exit criteria: digest/story output ranks the obvious "must-reads" first; clusters
survive title paraphrase; watch items become tracked sources.

### Phase 1 implementation spec

**1.1 — Scoring + trigger flags (`fetch.py`)**
- Structured engagement: `parse_hn` emits `points` / `comments` as real fields (instead of only in the summary string); stored on items.
- `compute_score(tier, published, points, comments)` = `tier_weight × (1 + engagement_boost) × freshness_decay`, where tier_weight {1:3, 2:2, 3:1}, boost = `log1p(points)/10 + log1p(comments)/50`, decay = `exp(-age_hours/48)`. Stored as `score` on every item (serialize + one-time backfill for existing window items).
- `story_trigger(categories, latest)`: `discovery` when academic-papers + (frontier|analysis|community), `opportunity` when industry-news + (frontier|community|benchmark), both gated to `latest` within 7 days. Set as `trigger` on stories in `build_stories`.
- Digest "High Signal" section (top): triggered story links + `watch` = high-score community items (`score ≥ 2.5`) not yet present in any story (deterministic proxy for the strategy's contrarian/watch signal; full disagreement-detection deferred).
- Build order dependency: none.

**1.2 — Tiered cadence (`fetch.py`, `sources.json`)**
- `cadence` per source (`hourly|daily|weekly`, default daily); `state["meta"][sid]["fetched_at"]` updated per fetch.
- In `main()`, skip sources not yet due (`last + cadence > now`); `--all` forces every source. Enables an extra hourly cron for tier-1 without re-polling slow sources.
- Dependency: none (can pair with 1.1 in the same fetch run).

**1.3 — Clustering quality (`fetch.py` `cluster_items`/`tokenize`/`canonical_url`)**
- `tokenize`: tiny stemmer (strip `-ing/-ed/-es/-s`) + drop pure-digit tokens; weight tokens by **IDF** across the window; replace plain Jaccard with a weighted similarity (cosine) retuned against `TITLE_SIM`.
- `canonical_url`: strip only tracking params (`utm_*`, `fbclid`, `gclid`, `ref`), keep meaningful queries; treat no-query ≠ query as distinct keys.
- Scale guard: cap the token-pair index (skip tokens shared by >N items) to bound the O(n²) pair set.
- Dependency: none; guarded by paraphrase-clustering tests.

**1.4 — Watch-item loop (`ideas.py` → `fetch.py`)**
- Reuse the ideas section parser to emit `data/watch.json` (`[{title, keywords}]`) from the "Watch items" section.
- `fetch.py` merges watch keywords into the HN/community keyword filter, with 7-day expiry (`data/watch.json` stores `added_at`). `ideas.py --clear-watch` resets.
- Dependency: 1.1 (watch candidates already highlighted in the digest).

**1.5 — Taxonomy v2 (`fetch.py` TAXONOMY)**
- TAXONOMY becomes `tag → {keywords, weight}` with regex support and per-tag confidence (kept only if ≥1 strong or ≥2 weak matches). Aggregate member tags onto stories; add `tags` to story entries.
- One-time `--retag` pass over the existing window.
- Dependency: 1.1/1.3 outputs settled (tags feed scoring and cluster tags).

**Build order:** 1.1 → 1.2 → 1.4 → 1.3 → 1.5 (1.3 and 1.4 are independent).

Done (2026-10-21): **1.1** — item `score` (tier × engagement × freshness, backfilled for existing window items), structured HN `points`/`comments`, `trigger` on stories (fresh discovery/opportunity), digest **High Signal** section (triggered stories + watch candidates). Tests: 60 stdlib cases.

---

## Phase 2 — Depth & browsing (weeks 4–6)

Turn the daily digest into a browsable, queryable research surface.

| # | Item | Why | Effort |
|---|------|-----|--------|
| 2.1 | **Weekly synthesis mode** (`ideas.py --weekly`): week-over-week cluster diff, "new relationships noticed" | The strategy's Sunday report; cheap once 1.1/1.2 exist | M |
| 2.2 | **Site search + RSS**: client-side search (tiny static index) + per-tag/per-section RSS feeds | Makes the static site a real dashboard, not just pages | M |
| 2.3 | **Longer history**: item store beyond 14 days (monthly archive in `data/`), trend detection (rising tag/source) | The window cap hides momentum; trends are high-signal | M–L |
| 2.4 | **Alerts** (opt-in notifier: ntfy/Discord/Slack/email) for tier-1 posts, trigger flags, and errors | The strategy's "seen within 24h" guarantee; pairs with 0.6 | M |
| 2.5 | **Prompt/result versioning for `ideas.py`** (prompt hash in `ideas.md` header, model/cost logged) | Reproducibility + cost transparency | S |

Exit criteria: you can answer "what moved this week" and "what's hot in X" in
seconds; alerts reach you before you check the digest.

---

## Phase 3 — Productization & integration (quarter)

Make it a dependable, shareable research radar.

| # | Item | Why | Effort |
|---|------|-----|--------|
| 3.1 | **Deploy the site** (GitHub Pages or Cloudflare Pages) on each CI run | The tool has a public site capability with no public home | S–M |
| 3.2 | **vramdb artifact v2**: richer contract (trends, scores, per-tag summaries) + version field | Keeps the consumer contract stable while features grow | M |
| 3.3 | **Long-term history DB** (SQLite or JSONL) + query tooling | Enables research-grade queries and charting; unblocks 2.3 at scale | L |
| 3.4 | **Multi-model synthesis**: compare Pro vs Flash ideas, configurable model/prompt per section | Higher-quality, cheaper default with an escape hatch | M |
| 3.5 | **graphify/knowledge-graph hook** (optional): emit paper↔model↔company relations to `graphify-out` | Cross-pollinates with the rest of the workspace | M |

Exit criteria: a deployed site, a stable versioned artifact, and a history store
that supports "was this signal new last week?"

---

## Cross-cutting

- **Tests** — add snapshot tests for digest/stories rendering and the JSON artifact shape (guards every Phase 1–2 change to clustering/scoring).
- **Observability** — one `run.log` per run with timing per source + token cost (feeds 0.3/2.5).
- **Docs** — keep `monitoring-strategy.md` in sync as cadence/scoring land.

## Success metrics

- Frontier-lab + top-tier coverage: **0 missing "don't-miss" sources** (Phase 0).
- Signal: **≤5 minutes to identify the day's top 3 stories** from the digest (Phase 1).
- Autonomy: **digest/stories/ideas/site all fresh without manual runs**, errors paged (Phase 0–2).
- Cost: ideas step **skips or downgrades on unchanged days** (Phase 0).

## Suggested order

Phase 0 (0.3 → 0.1 → 0.4 → 0.6) → Phase 1 (1.1 → 1.2 → 1.3) → Phase 2 (2.1 → 2.2 → 2.4) → Phase 3.
