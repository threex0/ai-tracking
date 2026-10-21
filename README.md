# AI Tracking

A tool that checks a curated set of AI/ML sources, reports what's new, rolls related items across sources into "stories", synthesizes opportunities with an LLM, and publishes everything as a static site.

## Requirements

- Python 3.12+ (fetcher and ideas generator: standard library only)
- Node.js 18+ (static-site build via Eleventy, in `site/`)

## Quick start

```powershell
python fetch.py            # fetch new items + build cross-source stories
python ideas.py            # synthesize ideas/opportunities (run after fetch.py)
# or the whole pipeline in one shot (fetch -> ideas -> static site):
./run.ps1
# build only the site from existing data:
cd site; npm run build
```

`python fetch.py` on the **first run** establishes a baseline (shows the latest items per source). On **every later run** it shows only what's *new* since the last run. `run.ps1` runs fetch → ideas → site build in sequence, which is what the scheduled task uses.

## What it produces

All generated files live under `output/`; all state under `data/`.

| File | Purpose |
|------|---------|
| `output/digest.md` | New items since last run, grouped by tier → source (overwritten each run) |
| `output/stories.md` | Cross-source clusters — the "relationships" view (overwritten each run) |
| `output/ideas.md` | LLM-generated opportunities/directions from the rolling window (via `ideas.py`) |
| `output/digests/YYYY-MM-DD.md` | Dated archive of each day's digest |
| `output/stories/YYYY-MM-DD.md` | Dated archive of each day's stories |
| `output/ideas/YYYY-MM-DD.md` | Dated archive of each day's ideas |
| `output/site/` | Static HTML site built by Eleventy from the above |

State files (created automatically — don't edit by hand):

| File | Purpose |
|------|---------|
| `data/state.json` | Per-source dedup markers, ETag/Last-Modified cursors, last-run timestamp |
| `data/items.json` | Rolling 14-day window of items (with keyword tags) used to build stories |
| `data/errors.log` | Append-only log of per-source fetch errors (also shown in the digest) |
| `data/ideas_state.json` | Fingerprint of the last ideas run (drives skip-when-unchanged) |

**Flags.** `fetch.py --strict` exits non-zero if any source failed to fetch (for CI/watchdogs); `fetch.py --all` ignores per-source cadence and fetches everything (by default, sources not yet due are skipped — sources that previously failed are retried every run). `ideas.py --force` regenerates even when nothing has changed.

## Static site

`site/` is an [Eleventy](https://www.11ty.dev/) project that turns the pipeline output into a browsable site:

- **Home** — latest reports, top tags, recent items
- **Digests / Stories / Ideas** — archive lists plus one page per dated report
- **Items** — everything in the rolling window
- **Tags** — a page per keyword-taxonomy tag, listing matching items
- **Sources** — a page per source, listing its items

`site/sync.mjs` copies the generated markdown reports into `site/src/content/` (adding frontmatter) before Eleventy runs, so `npm run build` is all you need after a fetch. Output goes to `output/site/` — serve it with any static host (`python -m http.server output/site`, or `npm run serve` for a live-reload dev server).

## Reading `digest.md`

Items are listed as `[title](link) - date -- summary`, ordered by tier (1 = core signal, 2 = opportunities, 3 = blind spots), then by source. Sources that failed to fetch appear at the bottom under `## Errors`.

Items are also tagged with a keyword taxonomy — `agents`, `rl`, `multimodal`, `reasoning`, `evals`, `synthetic-data`, `safety`, `open-source`, `hardware`, `policy`, `funding`, `speech-audio` — shown as `[tags: ...]`. The tags are stored on each item in `data/items.json` and fed into the ideas step.

## Reading `stories.md`

Each entry is one story seen across multiple sources:

```
## [discovery] <title>  (2 sources, 3 items)
- arXiv (...) - date - [title](link)
- Hacker News (...) - date - [title](link)
```

The tag tells you *why* it matters:

| Tag | Meaning |
|-----|---------|
| `discovery` | Research + frontier-lab/community echo — a new paper gaining traction |
| `opportunity` | Industry news + frontier-lab/community — market signal |
| `corroborated` | Same story in 2+ sources (validation) |
| `story` | 2+ items, single source (low signal) |

Tags fill in over time: a paper typically appears on arXiv (day 0), then HF/HN (day 1-3). Run daily and the `discovery`/`opportunity` clusters accumulate.

## Configuration

The fetcher reads `sources.json` (the `.csv` files in `references/` are the human reference; `sources.json` is what actually runs). Each source:

```json
{
  "id": "deepmind",
  "name": "Google DeepMind Blog",
  "category": "frontier-labs",
  "tier": 1,
  "type": "feed",
  "url": "https://deepmind.google/blog/rss.xml"
}
```

Supported fields:

- `id` — unique identifier
- `name`, `category` — display labels
- `tier` — 1, 2, or 3 (affects ordering in the digest)
- `type` — one of:
  - `"feed"` — RSS/Atom feed (`url` required)
  - `"arxiv"` — arXiv API (`categories` list + optional `max_results`)
  - `"json"` — JSON API (`kind` = `"hn"` or `"hf_papers"`)
  - `"sitemap"` — sitemap diff for RSS-less sites (`url` = sitemap URL; optional `url_filter` — substring or list to keep; `max_items`; `lastmod_days`). Titles come from the page `<title>` (fetched politely) or the URL slug. Used for OpenAI, Anthropic, DeepSeek.
- `keywords` — optional list; only items whose title contains one of these are kept (used to filter Hacker News)
- `cadence` — `"hourly"`, `"daily"` (default), or `"weekly"`; a source is only fetched when its cadence + last-fetched time is due, so an hourly cron can re-poll tier-1 sources without hammering slow ones. `fetch.py --all` forces everything.

To add a source, append an entry and re-run.

## Generating ideas & opportunities

`ideas.py` reads the rolling research window (`data/items.json`) plus the cross-source clusters (`output/stories.md`) and asks DeepSeek (via OpenRouter, using the key in `.env`) to synthesize non-obvious opportunities: research gaps, product/startup ideas, contrarian bets, and watch items. It writes `output/ideas.md` and `output/ideas/YYYY-MM-DD.md`.

```powershell
python ideas.py            # uses DeepSeek v4 Pro
python ideas.py --flash    # cheaper/faster Flash model
python ideas.py --days 7   # only items from the last week
python ideas.py --print    # print to stdout instead of writing files
python ideas.py --force    # regenerate even if nothing changed
```

If nothing changed since the last run, `ideas.py` skips the LLM call (it fingerprints the item window + stories; pass `--force` to override). `--print` always runs and prints to stdout. Transient API errors are retried with backoff, and a truncated response (`finish_reason=length`) retries once with a smaller context.

It's stdlib-only (uses `urllib`), so it keeps the same no-third-party dependency rule as `fetch.py`. Run it *after* `fetch.py` so the window is fresh.

## Machine-readable artifact & CI

`export_json.py` writes a single JSON artifact, `output/latest.json`, that downstream consumers (e.g. vramdb) can fetch without scraping the markdown:

```jsonc
{
  "generated_at": "...", "window_days": 14,
  "items":   [{ "title", "url", "source_id", "source_name", "date", "tier", "tags", "summary" }],
  "stories": [{ "title", "discovery", "sources", "items", "links": [{ "url", "source_name" }] }],
  "ideas":   [{ "title", "section", "body", "signal" }]
}
```

Run it after `ideas.py`: `python export_json.py`.

A GitHub Actions workflow (`.github/workflows/daily.yml`) runs the full pipeline daily (cron 08:00 UTC): fetch → ideas → export_json → Eleventy build, then commits `output/latest.json` back to the repo. The rolling window persists between runs via the Actions cache (`data/`) — the cache key is unique per run with a prefix `restore-keys`, so each run saves the updated state and restores the most recent one on the next run (a cache miss means that run establishes a fresh baseline). `OPENROUTER_API_KEY` must be set as a repo secret; optionally set `NOTIFY_URL` (e.g. a ntfy/Discord/Slack webhook) to get pinged when a run fails. Trigger manually with **Actions → daily-pipeline → Run workflow**.

## Scheduling

Run it on a timer so the rolling window fills, clusters form, and the site stays fresh.

**Windows (Task Scheduler), daily 8am** (runs fetch → ideas → site build):

```powershell
schtasks /Create /TN "AI Tracking" /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\Dev\kitch\ai-tracking\run.ps1" /SC DAILY /ST 08:00
```

**macOS/Linux (cron), daily 8am:**

```
0 8 * * * cd /path/to/ai-tracking && python fetch.py && python ideas.py && cd site && npm run build
```

## Testing

Tests use the standard library only (`unittest`):

```powershell
python -m unittest discover -s tests -t .
```

Covers the parsers (RSS/Atom, HN, Reddit, HF), URL/token normalization, clustering/dedup, story tags, keyword taxonomy, and the HTTP retry/conditional-GET logic.

## Troubleshooting

- **Reddit** — r/LocalLLaMA and r/MachineLearning are fetched via Old Reddit's RSS feeds (`.rss`), which need no OAuth. (The JSON API 403s unauthenticated; RSS returns the ~25 most recent posts per subreddit and can be throttled occasionally.)
- **`certificate verify failed` / `429 Too Many Requests`** — the fetcher retries once and falls back to an unverified TLS context for public news sites; these resolve automatically.
- **Re-running the same day** overwrites that day's dated archive (built for a daily cadence, not multiple runs/day).
- **Sparse stories early on** — clusters need the 14-day window to fill. Expect mostly `corroborated` for the first few days.

## File map

```
sources.json               active source config (what fetch.py reads)
fetch.py                   the fetcher (concurrent, conditional GET, keyword tags)
ideas.py                   LLM opportunity synthesizer (uses .env OPENROUTER_API_KEY)
export_json.py             writes output/latest.json (the machine-readable artifact)
paths.py                   shared path config (data/, output/, references/, site/)
run.ps1                    full-pipeline runner (fetch.py + ideas.py + site) for the scheduler
.github/workflows/         daily cron pipeline (fetch -> ideas -> export -> site -> commit)
references/                human reference: *.csv source lists + sites.txt
data/                      state.json + items.json (generated; don't edit)
output/                    digest.md / stories.md / ideas.md + dated archives + latest.json + site/
site/                      Eleventy project (site build; npm run build)
tests/                     stdlib unit tests
docs/                      monitoring-strategy.md, improvements.md
```
