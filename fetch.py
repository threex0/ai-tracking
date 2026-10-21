import collections
import html
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from paths import (DIGEST_FILE, DIGESTS_DIR, ITEMS_FILE, SOURCES_FILE, STATE_FILE,
                   STORIES_DIR, STORY_FILE, ensure_dirs)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, application/xml, text/xml, application/rss+xml, application/atom+xml, */*",
}
TIMEOUT = 30
SEEN_CAP = 1000
SNAPSHOT_PER_SOURCE = 5
DIGEST_ITEMS_PER_SOURCE = 30
WINDOW_DAYS = 14
MAX_ITEMS = 4000
TITLE_SIM = 0.4
RETRIES = 2
MAX_WORKERS = 6
STOPWORDS = set(
    "a an and are as at be but by for from had has have he her him his i if in is it its "
    "may might more most must no not of on or our so that the their them they this those to "
    "was we were what when which who will with would you your".split()
)
ARXIV_RE = re.compile(r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b")
TAXONOMY = [
    ("agents", ["agent", "agents", "tool use", "tool-use", "computer use", "harness", "autonomous", "multi-agent"]),
    ("rl", ["reinforcement learning", "rlhf", "reward model", "reward modeling", "policy gradient"]),
    ("multimodal", ["multimodal", "vision-language", "text-to-image", "image generation", "video generation", "diffusion", "vlm", "t2i"]),
    ("reasoning", ["reasoning", "reasoner", "chain-of-thought", "chain of thought", "cot", "test-time", "inference-time", "thinking"]),
    ("evals", ["benchmark", "benchmarks", "eval", "evaluation", "leaderboard"]),
    ("synthetic-data", ["synthetic data", "data generation", "data curation", "distillation"]),
    ("safety", ["alignment", "safety", "interpretability", "red team", "jailbreak", "guardrail", "steering"]),
    ("open-source", ["open source", "open-source", "open-weights", "open weights", "open-weight", "llama", "qwen", "mistral"]),
    ("hardware", ["gpu", "compute", "chip", "silicon", "tpu", "datacenter", "cluster", "inference engine", "transformer engine"]),
    ("policy", ["regulation", "policy", "lawsuit", "copyright", "legislation", "government", "executive order"]),
    ("funding", ["funding", "raise", "raised", "valuation", "series a", "series b", "acquisition", "merger", "ipo"]),
    ("speech-audio", ["speech", "audio", "voice", "tts", "asr", "speaker"]),
]


def local(tag):
    return tag.rsplit("}", 1)[-1]


def http_get_with_meta(url, etag=None, last_modified=None):
    headers = dict(HEADERS)
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    req = urllib.request.Request(url, headers=headers)
    last_exc = None
    for attempt in range(RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return (resp.read(),
                        resp.headers.get("ETag"),
                        resp.headers.get("Last-Modified"))
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return None, None, None
            if exc.code == 429 or exc.code >= 500:
                last_exc = exc
                retry_after = exc.headers.get("Retry-After")
                try:
                    wait = float(retry_after)
                except (TypeError, ValueError):
                    wait = 2 ** attempt
                time.sleep(min(wait, 30))
                continue
            raise
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, ssl.SSLCertVerificationError):
                ctx = ssl._create_unverified_context()
                try:
                    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
                        return (resp.read(),
                                resp.headers.get("ETag"),
                                resp.headers.get("Last-Modified"))
                except urllib.error.HTTPError as exc2:
                    if exc2.code == 304:
                        return None, None, None
                    raise
            last_exc = exc
            time.sleep(2 ** attempt)
            continue
    raise last_exc if last_exc else RuntimeError(f"GET {url} failed")


def http_get(url):
    data, _, _ = http_get_with_meta(url)
    return data


def http_get_json(url):
    return json.loads(http_get(url).decode("utf-8", "replace"))


def parse_date(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    try:
        return parsedate_to_datetime(s)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    return None


def parse_feed(text):
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    items = []
    for node in root.iter():
        if local(node.tag) not in ("item", "entry"):
            continue
        item = {"guid": None, "title": None, "link": None, "published": None, "summary": None}
        for child in node:
            cname = local(child.tag)
            if cname == "title" and item["title"] is None:
                item["title"] = "".join(child.itertext()).strip()
            elif cname == "link":
                href = child.get("href")
                if href and item["link"] is None:
                    item["link"] = href.strip()
                elif child.text and item["link"] is None:
                    item["link"] = child.text.strip()
            elif cname in ("guid", "id") and item["guid"] is None:
                item["guid"] = (child.text or "").strip() or None
            elif cname in ("pubDate", "published", "updated", "date") and item["published"] is None:
                item["published"] = parse_date(child.text)
            elif cname in ("description", "summary", "content") and item["summary"] is None:
                item["summary"] = clean("".join(child.itertext()))
        if item["link"] is None and item["guid"]:
            item["link"] = item["guid"]
        if item["guid"] is None:
            item["guid"] = item["link"]
        if item["title"] and item["link"]:
            items.append(item)
    return items


def parse_hn(obj):
    items = []
    for h in obj.get("hits", []):
        oid = h.get("objectID")
        title = (h.get("title") or "").strip()
        url = h.get("url") or h.get("story_url") or f"https://news.ycombinator.com/item?id={oid}"
        items.append({
            "guid": str(oid),
            "title": title,
            "link": url,
            "published": parse_date(h.get("created_at")),
            "summary": f"{h.get('points') or 0} points, {h.get('num_comments') or 0} comments",
        })
    return items


def parse_hf(obj):
    items = []
    for it in obj:
        paper = it.get("paper", {})
        pid = paper.get("id") or it.get("id")
        items.append({
            "guid": f"hf:{pid}",
            "title": (it.get("title") or paper.get("title") or "").strip(),
            "link": f"https://huggingface.co/papers/{pid}",
            "published": parse_date(it.get("publishedAt")),
            "summary": clean(it.get("summary") or ""),
        })
    return items


def fetch_arxiv(src):
    items = []
    seen_ids = set()
    for cat in src.get("categories", []):
        url = (f"https://export.arxiv.org/api/query?search_query=cat:{cat}"
               f"&sortBy=submittedDate&sortOrder=descending&max_results={src.get('max_results', 40)}")
        text = http_get(url).decode("utf-8", "replace")
        for it in parse_feed(text):
            aid = extract_arxiv_id(it.get("guid") or it.get("link") or "")
            if not aid or aid in seen_ids:
                continue
            seen_ids.add(aid)
            it["guid"] = aid
            it["link"] = f"https://arxiv.org/abs/{aid}"
            items.append(it)
    return items


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def match_keywords(title, keywords):
    if not keywords:
        return True
    t = title.lower()
    return any(k.lower() in t for k in keywords)


def tag_item(title, summary):
    text = f"{title} {summary}".lower()
    return [tag for tag, kws in TAXONOMY if any(k in text for k in kws)]


def fmt_dt(dt):
    if dt is None:
        return "unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def canonical_url(url):
    if not url:
        return ""
    u = url.strip().lower()
    u = re.sub(r"#.*$", "", u)
    u = "?".join(u.split("?")[:1])
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def extract_arxiv_ids(text):
    return set(ARXIV_RE.findall(text or ""))


def extract_arxiv_id(url):
    m = ARXIV_RE.search(url or "")
    return m.group(1) if m else None


def tokenize(text):
    t = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    return {w for w in t.split() if w and w not in STOPWORDS and not w.isdigit()}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def items_linked(a, b):
    if a.get("url_key") and a["url_key"] == b.get("url_key"):
        return True
    if a.get("arxiv_ids") and b.get("arxiv_ids") and (a["arxiv_ids"] & b["arxiv_ids"]):
        return True
    if a.get("source_id") and a["source_id"] == b.get("source_id"):
        return False
    ta, tb = a.get("tokens"), b.get("tokens")
    if ta and tb and len(ta) >= 4 and len(tb) >= 4 and jaccard(ta, tb) >= TITLE_SIM:
        return True
    return False


def cluster_items(items):
    n = len(items)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for it in items:
        title = it.get("title") or ""
        summary = it.get("summary") or ""
        link = it.get("link") or ""
        it["url_key"] = canonical_url(link)
        it["arxiv_ids"] = extract_arxiv_ids(" ".join([title, summary, link]))
        it["tokens"] = tokenize(title)

    buckets = collections.defaultdict(list)
    for i, it in enumerate(items):
        if it["url_key"]:
            buckets[it["url_key"]].append(i)
        for aid in it["arxiv_ids"]:
            buckets["arx:" + aid].append(i)
    for idxs in buckets.values():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                union(idxs[a], idxs[b])

    token_index = collections.defaultdict(set)
    for i, it in enumerate(items):
        for tok in it["tokens"]:
            token_index[tok].add(i)
    pairs = set()
    for idxs in token_index.values():
        idxs = list(idxs)
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                pairs.add((idxs[a], idxs[b]) if idxs[a] < idxs[b] else (idxs[b], idxs[a]))
    for i, j in pairs:
        if find(i) != find(j) and items_linked(items[i], items[j]):
            union(i, j)

    groups = collections.defaultdict(list)
    for i, it in enumerate(items):
        groups[find(i)].append(it)
    return list(groups.values())


def story_info(members):
    sources, categories, tiers = set(), set(), set()
    latest = None
    for m in members:
        sources.add(m.get("source_name") or m.get("source_id"))
        categories.add(m.get("category"))
        tiers.add(m.get("tier"))
        p = parse_date(m.get("published"))
        if p and (latest is None or p > latest):
            latest = p
    return sources, categories, tiers, latest


def canonical_title(members):
    def key(m):
        comm = 1 if m.get("category") == "communities" else 0
        return (-comm, len(tokenize(m.get("title"))))
    return clean(max(members, key=key).get("title"))


def story_tag(categories, sources):
    if "academic-papers" in categories and (categories & {"frontier-labs", "analysis-commentary", "communities"}):
        return "discovery"
    if "industry-news" in categories and (categories & {"frontier-labs", "communities", "benchmarks"}):
        return "opportunity"
    if len(sources) >= 2:
        return "corroborated"
    return "story"


def build_stories(items):
    stories = []
    for cluster in cluster_items(items):
        if len(cluster) < 2:
            continue
        sources, categories, tiers, latest = story_info(cluster)
        if len(sources) < 2:
            continue
        cluster.sort(key=lambda m: (m.get("tier") if m.get("tier") is not None else 9, m.get("published") or ""))
        stories.append({
            "title": canonical_title(cluster),
            "tag": story_tag(categories, sources),
            "sources": sources,
            "categories": categories,
            "latest": latest,
            "members": cluster,
        })
    stories.sort(key=lambda s: (-len(s["sources"]),
                                min((m.get("tier") or 9) for m in s["members"]),
                                -(s["latest"].timestamp() if s["latest"] else 0)))
    return stories


def render_stories(stories):
    lines = ["# AI Stories - Cross-Source Clusters", ""]
    lines.append("Items that mention the same story across sources, rolled up into one entry. "
                 "Multi-source clusters are the relationship/discovery signal.")
    lines.append("")
    if not stories:
        lines.append("No multi-source stories yet (need >=2 items from distinct sources).")
        lines.append("")
    for st in stories:
        srcs = len(st["sources"])
        cnt = len(st["members"])
        lines.append(f"## [{st['tag']}] {st['title']}  ({srcs} sources, {cnt} items)")
        lines.append("")
        for m in st["members"]:
            lines.append(f"- {m['source_name']} ({m['category']}) - {fmt_dt(parse_date(m.get('published')))} - "
                         f"[{clean(m['title'])}]({m['link']})")
        lines.append("")
    return "\n".join(lines)


def serialize_item(it, src):
    return {
        "key": it["key"],
        "source_id": src["id"],
        "source_name": src["name"],
        "category": src["category"],
        "tier": src["tier"],
        "title": it["title"],
        "link": it["link"],
        "published": it["published"].isoformat() if it["published"] else None,
        "summary": it.get("summary") or "",
        "tags": tag_item(it["title"], it.get("summary") or ""),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def load_items():
    if ITEMS_FILE.exists():
        try:
            return json.loads(ITEMS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_items(items):
    ITEMS_FILE.write_text(json.dumps(items, indent=1), encoding="utf-8")


def prune_items(items):
    now = datetime.now(timezone.utc)
    keep = []
    for x in items:
        fa = parse_date(x.get("fetched_at"))
        if fa is None or (now - fa).total_seconds() <= WINDOW_DAYS * 86400:
            keep.append(x)
    keep.sort(key=lambda x: x.get("fetched_at") or "", reverse=True)
    return keep[:MAX_ITEMS]


def load_sources():
    return json.loads(SOURCES_FILE.read_text(encoding="utf-8"))["sources"]


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"last_run": None, "seen": {}}


def render_digest(sources, new_by_source, snapshot_by_source, is_baseline, errors):
    lines = []
    if is_baseline:
        lines.append("# AI News - Initial Snapshot")
        lines.append("")
        lines.append("First run: listing latest items per source as a baseline. Subsequent runs will show only *new* items since the last run.")
        lines.append("")
        data = snapshot_by_source
    else:
        lines.append("# AI News - New Since Last Run")
        lines.append("")
        if not any(new_by_source.values()):
            lines.append("No new items since the last run.")
        data = new_by_source

    for tier in (1, 2, 3):
        tier_srcs = [s for s in sources if s["tier"] == tier and s["id"] in data and data[s["id"]]]
        if not tier_srcs:
            continue
        lines.append(f"## Tier {tier}")
        lines.append("")
        for s in tier_srcs:
            lines.append(f"### {s['name']} ({s['category']})")
            lines.append("")
            for it in data[s["id"]][:DIGEST_ITEMS_PER_SOURCE]:
                title = clean(it["title"])
                link = it.get("link", "#")
                dt = fmt_dt(it.get("published"))
                summary = clean(it.get("summary") or "")
                extra = f" -- {summary[:160]}" if summary else ""
                tags = it.get("tags") or []
                if tags:
                    extra += f" [tags: {', '.join(tags)}]"
                lines.append(f"- [{title}]({link}) - {dt}{extra}")
            lines.append("")
    if errors:
        lines.append("## Errors")
        lines.append("")
        for sid, err in errors:
            lines.append(f"- {sid}: {err}")
        lines.append("")
    return "\n".join(lines)


def write_outputs(digest_md, stories_md):
    run_date = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
    STORIES_DIR.mkdir(parents=True, exist_ok=True)
    DIGEST_FILE.write_text(digest_md, encoding="utf-8")
    STORY_FILE.write_text(stories_md, encoding="utf-8")
    (DIGESTS_DIR / f"{run_date}.md").write_text(digest_md, encoding="utf-8")
    (STORIES_DIR / f"{run_date}.md").write_text(stories_md, encoding="utf-8")


def fetch_source(src, meta):
    sid = src["id"]
    if src["type"] == "arxiv":
        items = fetch_arxiv(src)
        return items, meta
    if src["type"] == "feed":
        data, etag, last_mod = http_get_with_meta(src["url"], meta.get("etag"), meta.get("last_modified"))
        items = parse_feed(data.decode("utf-8", "replace")) if data else []
    else:
        kind = src.get("kind")
        data, etag, last_mod = http_get_with_meta(src["url"], meta.get("etag"), meta.get("last_modified"))
        obj = json.loads(data.decode("utf-8", "replace")) if data else {}
        if kind == "hn":
            items = parse_hn(obj)
        elif kind == "hf_papers":
            items = parse_hf(obj)
        else:
            raise ValueError(f"unknown json kind: {kind}")
    if data is not None:
        new_meta = {"etag": etag, "last_modified": last_mod}
    else:
        new_meta = meta
    return items, new_meta


def main():
    ensure_dirs()
    sources = load_sources()
    state = load_state()
    is_baseline = not state.get("last_run")
    errors = []
    new_by_source = {}
    snapshot_by_source = {}
    store_by_key = {x["key"]: x for x in load_items()}
    state_meta = state.setdefault("meta", {})
    seen_by_source = state.setdefault("seen", {})

    def process(src):
        sid = src["id"]
        try:
            items, new_meta = fetch_source(src, state_meta.get(sid, {}))
            return items, new_meta, None
        except Exception as exc:
            return [], {}, exc

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(process, sources))

    for src, (items, new_meta, exc) in zip(sources, results):
        sid = src["id"]
        if exc is not None:
            errors.append((sid, str(exc)))
            continue
        if new_meta:
            state_meta[sid] = new_meta

        seen = set(seen_by_source.get(sid, []))
        items = [it for it in items if it.get("title") and it.get("link") and it.get("guid")]
        items = [it for it in items if match_keywords(it["title"], src.get("keywords"))]
        for it in items:
            it["key"] = f"{sid}::{it['guid']}"
            store_by_key[it["key"]] = serialize_item(it, src)

        newly = [it for it in items if it["key"] not in seen]
        for it in items:
            seen.add(it["key"])

        seen_by_source[sid] = list(seen)[-SEEN_CAP:]
        if newly:
            new_by_source[sid] = newly
        snapshot_by_source[sid] = items[:SNAPSHOT_PER_SOURCE]

    state["last_run"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    store = prune_items(list(store_by_key.values()))
    save_items(store)

    digest_md = render_digest(sources, new_by_source, snapshot_by_source, is_baseline, errors)
    stories = build_stories(store)
    stories_md = render_stories(stories)
    write_outputs(digest_md, stories_md)

    total = sum(len(v) for v in new_by_source.values())
    if is_baseline:
        print(f"Baseline established ({len(sources) - len(errors)}/{len(sources)} sources OK).")
    else:
        print(f"{total} new item(s) across {len(new_by_source)} source(s).")
    print(f"{len(stories)} multi-source story/stories; {len(store)} items in rolling window.")
    for sid, err in errors:
        print(f"  ERROR {sid}: {err}")


if __name__ == "__main__":
    main()