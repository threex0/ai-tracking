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

## Phase 0 — Stabilize & close coverage gaps (this week)

Highest value-per-effort; mostly small, mostly independent.

| # | Item | Why | Effort |
|---|------|-----|--------|
| 0.1 | **Sitemap-diff scrapers** for OpenAI, Anthropic, Meta AI, Papers with Code, Qwen, DeepSeek | The strategy's "don't miss" tier-1 sources have no RSS and are absent entirely | M |
| 0.2 | **Persistent error log** + exit-code on partial failure | Today fetch errors go to stdout + digest tail only; a silent cron failure is invisible | S |
| 0.3 | **`ideas.py` skip-when-unchanged** (fingerprint digest of window/stories) | Each daily run spends LLM tokens even when nothing changed | S |
| 0.4 | **Retry/backoff + `finish_reason=length` handling in `ideas.py`** | Prevents failed/truncated idea runs and wasted cost | S |
| 0.5 | **CI hardening**: cache `data/` with a mutable key + cache-hit awareness; add a run-failure notification | Makes the daily pipeline self-monitoring | S–M |

Done (2026-10-21): Reddit switched to Old Reddit RSS (`.rss`) — no OAuth, no 403s.

Exit criteria: tier-1 RSS-less labs covered, failed runs are loud,
ideas step is idempotent/cost-aware.

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
