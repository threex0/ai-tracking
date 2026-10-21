# AI News Monitoring Strategy (Spec)

## 1. Objective

Track AI/ML across curated sources to achieve three outcomes:

| Outcome | Definition | Success signal |
|---------|-----------|----------------|
| **News** | Meaningful events: model releases, products, funding, policy, hires | Seen within 24h of publication |
| **Discoveries** | New research / techniques / models, caught *before* they're widely echoed | Seen within ~48h of hitting ArXiv |
| **Relationships & opportunities** | Links between papers, models, benchmarks, companies, and people that imply next moves | Clustered into "stories" instead of isolated links |

## 2. Source tiers (from priorities)

| Tier | Files | Role |
|------|-------|------|
| **1 — core signal (daily)** | `frontier-labs.csv`, `academic-papers.csv` | Primary sources; where news and discoveries originate |
| **2 — opportunities (daily)** | `analysis-commentary.csv`, `industry-news.csv`, `communities.csv` | Who is thinking/shipping; market framing |
| **3 — blind spots (weekly)** | `chinese-labs.csv`, `syntheses.csv` | Under-covered frontier + distillation layer |
| **Aux — verify only** | `benchmarks.csv` | Confirm who is actually winning |
| **Skip** | `code-discovery.csv` | Lowest signal |

## 3. Check cadence

| Cadence | Sources | Why |
|---------|---------|-----|
| **On publish (RSS/API poll, sub-hour)** | frontier-labs, industry-news | These are the "don't miss" events |
| **Daily (morning)** | academic-papers (ArXiv), HN, Reddit subs | High-velocity; new submissions/votes overnight |
| **Every 2–3 days** | analysis-commentary long-form (SemiAnalysis, Interconnects, Quanta, MIT TR, The Batch) | Publication cadence is slower, posts are longer |
| **Weekly** | chinese-labs, syntheses (newsletters), benchmarks | Aggregated/release-cadence content |
| **Monthly / on demand** | code-discovery, Distill, LMArena | Distill is dormant; GitHub Trending is noisy |

## 4. Fetch mechanism per source

Prefer **RSS/Atom and JSON APIs** over HTML scraping (more robust, respects rate limits and ToS).

### Tier 1
| Source | Method | Endpoint / notes |
|--------|--------|------------------|
| OpenAI | Scrape (or sitemap diff) | `https://openai.com/news/` — no official RSS; filter by Research/Engineering tags |
| Google DeepMind | RSS | `https://deepmind.google/blog/rss.xml` *(verify)* |
| Anthropic | Scrape | `https://www.anthropic.com/research` *(check for RSS)* |
| Meta AI | Scrape / RSS | `https://ai.meta.com/blog/` *(verify feed)* |
| ArXiv (cs.AI/CL/CV/LG) | RSS + API | `https://export.arxiv.org/rss/cs.AI` (also `.CL`, `.CV`, `.LG`); API: `export.arxiv.org/api/query` |
| Hugging Face Daily Papers | JSON API | `https://huggingface.co/api/daily_papers` |
| Papers with Code | Scrape | `https://paperswithcode.com` (no stable public feed) |
| BAIR | RSS | `https://bair.berkeley.edu/blog/feed.xml` *(verify)* |
| Stanford HAI | Scrape | `https://hai.stanford.edu/news` *(verify feed)* |
| Distill | Skip | Dormant |

### Tier 2
| Source | Method | Endpoint / notes |
|--------|--------|------------------|
| SemiAnalysis | RSS | `https://semianalysis.com/feed` (Substack) |
| Interconnects | RSS | `https://www.interconnects.ai/feed` (Substack) |
| LessWrong | GraphQL / RSS | `https://www.lesswrong.com/feed.xml` *(verify)*; GraphQL API available |
| Hacker News | API | Firebase `https://hacker-news.firebaseio.com/v0/newstories.json`; filtered search via Algolia `https://hn.algolia.com/api/v1/search?tags=story&query=...`; or keyword RSS via `hnrss.org` |
| The Batch | RSS / email | `https://www.deeplearning.ai/the-batch/` *(verify feed)* |
| Quanta | RSS | `https://www.quantamagazine.org/feed/` |
| MIT Tech Review | RSS | `https://www.technologyreview.com/feed/` |
| TechCrunch AI | RSS | `https://techcrunch.com/category/artificial-intelligence/feed/` |
| VentureBeat AI | RSS | `https://venturebeat.com/category/ai/feed/` |
| The Verge AI | RSS | `https://www.theverge.com/rss/ai-artificial-intelligence/index.xml` |
| r/LocalLLaMA | JSON API | `https://www.reddit.com/r/LocalLLaMA/new.json` (set a real User-Agent, respect rate limits) |
| r/MachineLearning | JSON API | `https://www.reddit.com/r/MachineLearning/new.json` |

### Tier 3
| Source | Method | Endpoint / notes |
|--------|--------|------------------|
| Qwen | Scrape (or RSS) | `https://qwen.ai/blog` *(verify feed)* |
| DeepSeek | Scrape | `https://api-docs.deepseek.com/news` |
| Two Minute Papers | YouTube RSS | `https://www.youtube.com/feeds/videos.xml?channel_id=<ID>` |
| AI Explained | YouTube RSS | `https://www.youtube.com/feeds/videos.xml?channel_id=<ID>` |
| Simon Willison | Atom | `https://simonwillison.net/atom/everything/` |
| Import AI (Jack Clark) | RSS | `https://jack-clark.net/feed` *(verify)* |

### Aux
| Source | Method | Endpoint / notes |
|--------|--------|------------------|
| Open LLM Leaderboard | JSON API | `https://huggingface.co/api/spaces/open-llm-leaderboard/open_llm_leaderboard` (poll weekly) |
| Artificial Analysis | Scrape / API | `https://artificialanalysis.ai` |
| LMArena | Scrape | Leaderboard page, low cadence |
| GitHub Trending | API / scrape | `search/repositories?sort=stars`; low priority |

## 5. Change detection & dedup

1. **Watermark per source**: store a "last-seen" cursor per source:
   - RSS/Atom: store the feed `GUID`/`id`; use `ETag` / `Last-Modified` headers to avoid re-fetching.
   - JSON APIs: store max item ID or timestamp; query `since=<cursor>` where supported.
   - Scraped pages: diff the ordered list of `(title, url)`; treat any new (title, url) as an item.
2. **Normalize**: canonicalize URLs (strip tracking params, trailing slash, resolve `www`).
3. **Cross-source clustering (key for "relationships")**: group items into "stories" when they share:
   - the same ArXiv ID, or
   - near-duplicate titles (e.g., a paper + a blog post + a HN thread about it), or
   - high string-similarity on the title/abstract.
   This turns "5 separate links" into "1 story with 5 corroborating sources", which is exactly how discoveries and relationships surface.

## 6. Filtering & triage (signal extraction)

**Keyword taxonomy** (tag every item):
`agents`, `RL / reinforcement learning`, `multimodal`, `vision`, `speech/audio`, `reasoning`, `inference`, `evals / benchmarks`, `synthetic data`, `distillation`, `safety / alignment`, `open-source / open-weights`, `hardware / compute`, `policy / regulation`, `funding / M&A`.

**Scoring** (rank items):
```
score = source_weight × (1 + engagement_boost) × freshness_decay
```
- `source_weight`: Tier 1 > Tier 2 > Tier 3.
- `engagement_boost`: log-scaled HN points, Reddit score, HF upvotes.
- `freshness_decay`: newer = higher.

**Trigger rules for surfacing opportunities:**
- **Discovery cluster**: a new ArXiv paper AND a frontier-lab/blog mention AND a benchmark entry appearing within ~7 days → flag as "breakthrough."
- **Opportunity cluster**: funding/product launch (industry-news) + personnel moves + open-weight model releases (chinese-labs / frontier-labs / r/LocalLLaMA) → flag for deeper read.
- **Contrarian signal**: high-engagement HN/Reddit item that *disagrees* with a Tier 1 announcement → flag as "watch."

## 7. Output & review workflow

| Output | Cadence | Content |
|--------|---------|---------|
| **Alert** | Real-time | Any frontier-lab post, model release, or top-voted community item |
| **Daily digest** | Morning | Tier 1 new items + top HN/Reddit stories, deduped into clusters |
| **Weekly synthesis** | Sunday | Long-form/newsletters, clustered into themes; list "new relationships noticed" (paper↔model↔company↔person) |
| **Anti-goals** | — | Posting, writing full summaries, or auto-replies — this tool only *fetches and ranks* |

## 8. Implementation approach

Recommended build order:

1. **RSS/API fetcher** for the ~15 feeds/JSON endpoints that support it (most of Tier 1–2). This covers 80% of value with minimal fragility.
2. **Scrapers** only for the handful without feeds (OpenAI, Anthropic, Papers with Code, Qwen, DeepSeek, Artificial Analysis) — use a deterministic selector + a `<1 req/min` polite rate.
3. **Dedup + clustering** layer (URL canonicalization + title similarity).
4. **Scoring + digest renderer** (markdown summary is sufficient for v1).

Start with Tier 1 + `communities.csv` + `industry-news.csv`; add the rest incrementally.

## 9. Risks & notes

- **Rate limits / ToS**: Reddit requires proper User-Agent and throttling; GitHub has API limits; Hugging Face/ArXiv have friendly APIs — prefer them.
- **Anti-bot**: some sites (Anthropic, OpenAI) may block naive scrapers; use RSS/sitemap or a headless client with conservative delays.
- **Dormant sources**: Distill is effectively dead; don't allocate polling to it.
- **Chinese-lab cadence**: release-driven, not daily — a weekly poll misses nothing important.
- **Verification**: entries marked *(verify)* need the exact feed/endpoint confirmed before wiring the fetcher.