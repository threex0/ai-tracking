"""Export the AI Tracking window + stories + ideas as one machine-readable JSON
artifact (output/latest.json) for downstream consumers (e.g. vramdb).

Stdlib-only. Run after fetch.py and ideas.py.
"""

import json
import re
import sys
from datetime import datetime, timezone

import fetch
from paths import IDEAS_FILE, ITEMS_FILE, OUTPUT_DIR

LATEST_FILE = OUTPUT_DIR / "latest.json"
WINDOW_DAYS = 14
SUMMARY_CHARS = 300

TITLE_RE = re.compile(r"^\*\*(.+?)\*\*(.*)$")
SIGNAL_RE = re.compile(r"^\*Signal:\s*(.+?)\s*\*?$")
SECTION_RE = re.compile(r"^\d+\.\s+(.*)$")


def export_items(items):
    out = []
    for it in items:
        e = {
            "title": it.get("title") or "",
            "url": it.get("link") or "",
            "source_id": it.get("source_id") or "",
            "source_name": it.get("source_name") or it.get("source_id") or "",
            "date": (it.get("published") or "")[:10],
            "tier": it.get("tier"),
            "tags": it.get("tags") or [],
            "summary": (it.get("summary") or "")[:SUMMARY_CHARS],
            "score": it.get("score") or 0.0,
        }
        if it.get("points") is not None:
            e["points"] = it["points"]
        if it.get("comments") is not None:
            e["comments"] = it["comments"]
        out.append(e)
    return out


def export_stories(stories):
    out = []
    for st in stories:
        links, seen = [], set()
        for m in st["members"]:
            url = m.get("link")
            if url and url not in seen:
                seen.add(url)
                links.append({
                    "url": url,
                    "source_name": m.get("source_name") or m.get("source_id") or "",
                })
        out.append({
            "title": st["title"],
            "discovery": st["tag"],
            "trigger": st.get("trigger"),
            "tags": st.get("tags") or [],
            "sources": len(st["sources"]),
            "items": len(st["members"]),
            "links": links,
        })
    return out


def parse_ideas(text):
    ideas = []
    for block in re.split(r"\n##\s+", text):
        lines = [ln.strip() for ln in block.splitlines()]
        if not lines:
            continue
        first = lines[0]
        section = ""
        start = 0
        if SECTION_RE.match(first):
            section = SECTION_RE.match(first).group(1)
            start = 1
        current = None
        for ln in lines[start:]:
            if not ln:
                continue
            m = TITLE_RE.match(ln)
            if m and m.group(1):
                current = {"title": m.group(1).strip(), "section": section,
                           "body": [], "signal": ""}
                ideas.append(current)
                rest = m.group(2).strip().lstrip("-—").strip()
                if rest:
                    current["body"].append(rest)
                continue
            sm = SIGNAL_RE.match(ln)
            if sm and current is not None:
                current["signal"] = sm.group(1).strip()
                continue
            if current is not None:
                current["body"].append(ln)
    return [
        {"title": i["title"], "section": i["section"],
         "body": " ".join(i["body"]).strip(), "signal": i["signal"]}
        for i in ideas
    ]


def export_ideas():
    if not IDEAS_FILE.exists():
        return []
    return parse_ideas(IDEAS_FILE.read_text(encoding="utf-8"))


def main():
    items = fetch.load_items()
    if not items:
        print("No items in the rolling window. Run fetch.py first.", file=sys.stderr)
        sys.exit(1)

    stories = fetch.build_stories(items)
    artifact = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": WINDOW_DAYS,
        "items": export_items(items),
        "stories": export_stories(stories),
        "ideas": export_ideas(),
        "watch": fetch.watch_items(stories, items),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_FILE.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {LATEST_FILE} "
          f"({len(artifact['items'])} items, {len(artifact['stories'])} stories, "
          f"{len(artifact['ideas'])} ideas, {len(artifact['watch'])} watch)")


if __name__ == "__main__":
    main()
