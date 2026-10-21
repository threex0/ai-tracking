import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

from paths import ENV_FILE, IDEAS_DIR, IDEAS_FILE, ITEMS_FILE, STORY_FILE, ensure_dirs

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


def build_context(items, days):
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
        if total >= MAX_ITEMS:
            break
        lines.append(f"## {cat} ({len(group)} items)")
        lines.append("")
        for it in group[:PER_CATEGORY]:
            lines.append(item_line(it))
            total += 1
            if total >= MAX_ITEMS:
                break
        lines.append("")
    return "\n".join(lines)


def load_stories():
    if STORY_FILE.exists():
        text = STORY_FILE.read_text(encoding="utf-8")
        return text.strip()
    return ""


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


def call_llm(prompt, model, api_key):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "You produce sharp, well-grounded research strategy. Output Markdown only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 20000,
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
        raise RuntimeError(f"Empty content finish_reason={reason} (reasoning model likely exhausted max_tokens). Raw: {json.dumps(data)[:400]}")
    return content


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


def main():
    parser = argparse.ArgumentParser(description="Generate ideas/opportunities from the AI research digest.")
    parser.add_argument("--flash", action="store_true", help="Use the cheaper/faster DeepSeek Flash model.")
    parser.add_argument("--model", default=None, help="Override the OpenRouter model id.")
    parser.add_argument("--days", type=int, default=None, help="Restrict to items from the last N days.")
    parser.add_argument("--print", dest="print_only", action="store_true", help="Print to stdout instead of writing files.")
    args = parser.parse_args()

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

    context = build_context(items, args.days)
    stories = load_stories()

    prompt = PROMPT
    if stories:
        prompt += "\n### Cross-source stories (clusters)\n\n" + stories + "\n\n"
    prompt += "### Items by category\n\n" + context

    print(f"Building prompt from {len(items)} items (model={model})...")
    markdown = call_llm(prompt, model, api_key)

    if args.print_only:
        print(markdown)
    else:
        full = write_outputs(markdown)
        print(f"Wrote {IDEAS_FILE} and {IDEAS_DIR}/{datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d')}.md")


if __name__ == "__main__":
    main()
