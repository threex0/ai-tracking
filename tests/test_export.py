import unittest

import export_json
import fetch


IDEAS_MD = """# AI Ideas & Opportunities

Generated 2026-10-20 07:54 from the rolling research window.

## 1. Research directions & gaps

**World models are splitting into two camps.**  
The first camp does pixels. The second does states.
*Signal: State World Models, AnyGoal

**Language pretraining may be an expensive crutch.**  
Test the scaling crossover point.
*Signal: Text-to-Image Without Language Pretraining

## 4. Watch items

**The "Cammarata claim" about interpretability** — MIT Technology Review calls it the explosive claim. Watch for replication attempts.

**CoreWeave's distressed debt** — The Verge reports the bonds slipped. Watch the compute bubble.
"""


class ParseIdeasTest(unittest.TestCase):
    def test_parses_sections_and_titles(self):
        ideas = export_json.parse_ideas(IDEAS_MD)
        self.assertEqual(len(ideas), 4)

    def test_first_idea(self):
        ideas = export_json.parse_ideas(IDEAS_MD)
        it = ideas[0]
        self.assertEqual(it["title"], "World models are splitting into two camps.")
        self.assertEqual(it["section"], "Research directions & gaps")
        self.assertIn("first camp does pixels", it["body"])
        self.assertEqual(it["signal"], "State World Models, AnyGoal")

    def test_watch_item_inline_body(self):
        ideas = export_json.parse_ideas(IDEAS_MD)
        it = ideas[2]
        self.assertEqual(it["section"], "Watch items")
        self.assertIn("explosive claim", it["body"])


class ExportStoriesTest(unittest.TestCase):
    def test_story_shape(self):
        items = [
            {"title": "State World Models for agents", "link": "https://a.com/1",
             "source_id": "arxiv", "source_name": "arXiv", "category": "academic-papers",
             "tier": 1, "published": "2026-10-19T00:00:00+00:00", "summary": "s", "tags": ["agents"]},
            {"title": "State World Models for agents", "link": "https://b.com/2",
             "source_id": "hn", "source_name": "Hacker News", "category": "communities",
             "tier": 2, "published": "2026-10-20T00:00:00+00:00", "summary": "s", "tags": ["agents"]},
        ]
        stories = export_json.export_stories(fetch.build_stories(items))
        self.assertEqual(len(stories), 1)
        st = stories[0]
        self.assertEqual(st["discovery"], "discovery")
        self.assertEqual(st["trigger"], "discovery")
        self.assertEqual(st["sources"], 2)
        self.assertEqual(st["items"], 2)
        self.assertEqual(len(st["links"]), 2)
        self.assertEqual(st["links"][0]["source_name"], "arXiv")
        self.assertIn("agents", st["tags"])


class ExportItemsTest(unittest.TestCase):
    def test_item_shape(self):
        items = [{"title": "T", "link": "https://x.com", "source_id": "arxiv",
                  "source_name": "arXiv", "published": "2026-10-19T00:00:00+00:00",
                  "tier": 1, "tags": ["agents"], "summary": "hello world",
                  "score": 2.5, "points": 5, "comments": 3}]
        out = export_json.export_items(items)[0]
        self.assertEqual(out["date"], "2026-10-19")
        self.assertEqual(out["tags"], ["agents"])
        self.assertEqual(out["url"], "https://x.com")
        self.assertEqual(out["score"], 2.5)
        self.assertEqual(out["points"], 5)
        self.assertEqual(out["comments"], 3)

    def test_score_defaults(self):
        items = [{"title": "T", "link": "https://x.com", "source_id": "a", "tier": 1,
                  "published": "2026-10-19T00:00:00+00:00", "summary": "", "tags": []}]
        out = export_json.export_items(items)[0]
        self.assertEqual(out["score"], 0.0)
        self.assertNotIn("points", out)


class WatchTest(unittest.TestCase):
    def test_watch_shape(self):
        story = {"members": [{"key": "s::1", "link": "https://a.com/1"}]}
        items = [
            {"key": "s::1", "category": "communities", "score": 9.0, "link": "https://a.com/1", "title": "in story"},
            {"key": "h::1", "category": "communities", "score": 3.0, "link": "https://h.com", "title": "hot"},
        ]
        watch = fetch.watch_items([story], items)
        self.assertEqual(len(watch), 1)
        self.assertEqual(watch[0]["title"], "hot")
        self.assertEqual(watch[0]["score"], 3.0)


if __name__ == "__main__":
    unittest.main()
