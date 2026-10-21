import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from paths import (ENV_FILE, IDEAS_DIR, IDEAS_FILE, IDEAS_STATE_FILE, ITEMS_FILE,
                   STORY_FILE, WATCH_FILE, ensure_dirs)

from export_json import parse_ideas

MODEL_PRO = "deepseek/deepseek-v4-pro-0813"
MODEL_FLASH = "deepseek/deepseek-v4-flash-0731"
API_URL = "https://openrouter.ai/api/v1/chat/completions"

MAX_ITEMS = 400
PER_CATEGORY = 60
SUMMARY_CHARS = 180


def load_env():
    env = dict(os.environ)
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_items():
    if ITEMS_FILE.exists():
        try:
            return json.loads(ITEMS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def clean(text):
    return " ".join((text or "").split())


def fmt_date(value):
    if not value:
        return "?"
    return str(value)[:10]


def item_line(it):
    title = clean(it.get("title") or "")
    summary = clean(it.get("summary") or "")[:SUMMARY_CHARS]
    cat = it.get("category") or ""
    src = it.get("source_name") or it.get("source_id") or ""
    date = fmt_date(it.get("published"))
    line = f"- [{src}] ({date}) {title}"
    tags = it.get("tags") or []
    if tags:
        line += f" [tags: {', '.join(tags)}]"
    if summary:
        line += f" -- {summary}"
    return line


def build_context(items, days, max_items=MAX_ITEMS):
    now = datetime.now(timezone.utc)
    cutoff = None
    if days:
        cutoff = now.timestamp() - days * 86400

    def rec(it):
        raw = it.get("published") or it.get("fetched_at") or ""
        try:
            return datetime.fromisoformat(raw).timestamp()
        except (ValueError, TypeError):
            return 0

    items = [it for it in items if it.get("title")]
    if cutoff is not None:
        items = [it for it in items if rec(it) >= cutoff]
    items.sort(key=rec, reverse=True)

    buckets = {}
    for it in items:
        buckets.setdefault(it.get("category") or "other", []).append(it)

    lines = []
    total = 0
    for cat, group in buckets.items():
        if total >= max_items:
            break
        lines.append(f"## {cat} ({len(group)} items)")
        lines.append("")
        for it in group[:PER_CATEGORY]:
            lines.append(item_line(it))
            total += 1
            if total >= max_items:
                break
        lines.append("")
    return "\n".join(lines)


def build_prompt(context, stories):
    prompt = PROMPT
    if stories:
        prompt += "\n### Cross-source stories (clusters)\n\n" + stories + "\n\n"
    prompt += "### Items by category\n\n" + context
    return prompt


def load_stories():
    if STORY_FILE.exists():
        text = STORY_FILE.read_text(encoding="utf-8")
        return text.strip()
    return ""


def compute_fingerprint(items, stories, days=None):
    h = hashlib.sha256()
    h.update(f"{days}|{len(items)}|".encode())
    fetched = [it.get("fetched_at") or "" for it in items if it.get("fetched_at")]
    if fetched:
        h.update(max(fetched).encode())
    h.update("|".encode())
    h.update((stories or "").encode())
    return h.hexdigest()


def load_fingerprint():
    if IDEAS_STATE_FILE.exists():
        try:
            return json.loads(IDEAS_STATE_FILE.read_text(encoding="utf-8")).get("fingerprint")
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_fingerprint(fp):
    IDEAS_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    IDEAS_STATE_FILE.write_text(json.dumps({
        "fingerprint": fp,
        "last_run": datetime.now(timezone.utc).isoformat(),
    }, indent=2), encoding="utf-8")


PROMPT = """You are an AI research strategist. Below is a snapshot of recent AI/ML research and news pulled automatically from arXiv, Hugging Face, frontier-lab blogs, industry press, and community discussions.

Synthesize this into concrete, NON-OBVIOUS ideas and opportunities about what is now possible, worth building, or worth studying, given the current state of the field.

Rules:
- Ground every idea in the items/stories below. Cite the source inline as [SourceName].
- Do not just restate the news. Identify gaps, adjacencies, combinations, and under-exploited directions the data implies.
- Be specific and actionable: what, why now, what it would take, who benefits.

Output Markdown with exactly these sections:

## 1. Research directions & gaps
## 2. Product / startup opportunities
## 3. Contrarian bets & falsifiable predictions
## 4. Watch items

For each idea: a bold one-line title, then 2-4 sentences of reasoning with citations, then (where useful) a "signal:" line naming the underlying items.

Snapshot:
"""


class TruncatedError(RuntimeError):
    """Raised when the model output was cut off (finish_reason=length)."""


def call_llm(prompt, model, api_key, max_tokens=20000):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "You produce sharp, well-grounded research strategy. Output Markdown only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ai-tracking/ideas.py",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if "error" in data:
        raise RuntimeError(f"API error: {json.dumps(data['error'])[:400]}")
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError):
        raise RuntimeError(f"Unexpected API response: {json.dumps(data)[:400]}")
    content = message.get("content")
    if not content:
        reason = data["choices"][0].get("finish_reason")
        if reason == "length":
            raise TruncatedError("finish_reason=length (output cut off)")
        raise RuntimeError(f"Empty content finish_reason={reason}. Raw: {json.dumps(data)[:400]}")
    return content


def _is_retryable(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or exc.code >= 500
    if isinstance(exc, urllib.error.URLError):
        return True
    return False


def call_llm_with_retries(prompt, model, api_key, retries=3):
    last = None
    for attempt in range(retries):
        try:
            return call_llm(prompt, model, api_key)
        except TruncatedError:
            raise
        except Exception as exc:
            if not _is_retryable(exc) or attempt == retries - 1:
                raise
            last = exc
            wait = 2 ** attempt
            print(f"  retrying in {wait}s after: {exc}", file=sys.stderr)
            time.sleep(wait)
    raise last


def generate(items, stories, model, api_key, days, max_items=MAX_ITEMS, include_stories=True):
    context = build_context(items, days, max_items=max_items)
    prompt = build_prompt(context, stories if include_stories else "")
    try:
        return call_llm_with_retries(prompt, model, api_key)
    except TruncatedError:
        print("  output truncated; retrying once with a smaller context", file=sys.stderr)
        context = build_context(items, days, max_items=max_items // 2)
        prompt = build_prompt(context, "" if include_stories else "")
        return call_llm_with_retries(prompt, model, api_key)


def write_outputs(markdown):
    header = (
        "# AI Ideas & Opportunities\n\n"
        f"Generated {datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M')} "
        f"from the rolling research window.\n\n"
    )
    full = header + markdown.rstrip() + "\n"
    IDEAS_FILE.write_text(full, encoding="utf-8")
    IDEAS_DIR.mkdir(parents=True, exist_ok=True)
    run_date = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    (IDEAS_DIR / f"{run_date}.md").write_text(full, encoding="utf-8")
    return full


WATCH_STOPWORDS = set(
    "the a an and or but of in on for to is are was were be will it its this that with "
    "about from into over under as at by do does did not no yes how what when where which "
    "who why claim claims watch whether".split()
)


def watch_keywords(title):
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return sorted({w for w in words
                   if w not in WATCH_STOPWORDS and len(w) >= 5 and not w.isdigit()})


def write_watch_items():
    """Extract the 'Watch items' section into data/watch.json so fetch.py can
    surface related community discussion. Entries expire after 7 days."""
    if not IDEAS_FILE.exists():
        return
    ideas = parse_ideas(IDEAS_FILE.read_text(encoding="utf-8"))
    watch = [{"title": i["title"], "keywords": watch_keywords(i["title"]),
              "added_at": datetime.now(timezone.utc).isoformat()}
             for i in ideas if "watch" in i["section"].lower()]
    WATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    WATCH_FILE.write_text(json.dumps(watch, indent=2, ensure_ascii=False), encoding="utf-8")
    if watch:
        print(f"Wrote {len(watch)} watch item(s) to {WATCH_FILE}")


def main():
    parser = argparse.ArgumentParser(description="Generate ideas/opportunities from the AI research digest.")
    parser.add_argument("--flash", action="store_true", help="Use the cheaper/faster DeepSeek Flash model.")
    parser.add_argument("--model", default=None, help="Override the OpenRouter model id.")
    parser.add_argument("--days", type=int, default=None, help="Restrict to items from the last N days.")
    parser.add_argument("--force", action="store_true", help="Regenerate even if nothing has changed since the last run.")
    parser.add_argument("--clear-watch", action="store_true", help="Clear the watch-item keywords file.")
    parser.add_argument("--print", dest="print_only", action="store_true", help="Print to stdout instead of writing files.")
    args = parser.parse_args()

    if args.clear_watch:
        ensure_dirs()
        WATCH_FILE.write_text("[]", encoding="utf-8")
        print(f"Cleared {WATCH_FILE}")
        return

    ensure_dirs()
    env = load_env()
    api_key = env.get("OPENROUTER_API_KEY")
    if not api_key:
        print("Missing OPENROUTER_API_KEY (set it in .env or the environment).", file=sys.stderr)
        sys.exit(1)

    model = args.model or (MODEL_FLASH if args.flash else MODEL_PRO)

    items = load_items()
    if not items:
        print("No items in the rolling window yet. Run fetch.py first.", file=sys.stderr)
        sys.exit(1)

    stories = load_stories()
    fp = compute_fingerprint(items, stories, days=args.days)

    if not args.print_only and not args.force and fp == load_fingerprint():
        print("Nothing new since the last ideas run; skipping (use --force to regenerate).")
        return

    print(f"Building prompt from {len(items)} items (model={model})...")
    markdown = generate(items, stories, model, api_key, args.days)

    if args.print_only:
        print(markdown)
    else:
        full = write_outputs(markdown)
        write_watch_items()
        save_fingerprint(fp)
        run_date = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
        print(f"Wrote {IDEAS_FILE} and {IDEAS_DIR}/{run_date}.md")


if __name__ == "__main__":
    main()
