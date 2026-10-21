import json
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from unittest import mock

import fetch

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Test</title>
  <item>
    <title>Hello World Model</title>
    <link>https://example.com/hello-world-model</link>
    <guid>https://example.com/hello-world-model</guid>
    <pubDate>Mon, 20 Oct 2025 08:00:00 GMT</pubDate>
    <description><![CDATA[<p>A new world model for agents.</p>]]></description>
  </item>
</channel></rss>"""

ATOM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Test</title>
  <entry>
    <title>Atom Entry</title>
    <link href="https://example.com/atom-entry"/>
    <id>tag:example.com,2025:1</id>
    <updated>2025-10-20T08:00:00Z</updated>
    <summary>Short summary text.</summary>
  </entry>
</feed>"""

HN_JSON = {
    "hits": [
        {"objectID": "12345", "title": "GPT-5 local agents", "url": "https://example.com/gpt5",
         "created_at": "2025-10-20T08:00:00.000Z", "points": 120, "num_comments": 45},
        {"objectID": "67890", "title": "No link story",
         "created_at": "2025-10-20T09:00:00.000Z", "points": 3, "num_comments": 0},
    ]
}

REDDIT_JSON = {"data": {"children": [
    {"data": {"name": "t3_abc123", "id": "abc123", "title": "Reddit post about LLM",
              "permalink": "/r/LocalLLaMA/comments/abc123/x/", "created_utc": 1760918400,
              "score": 200, "subreddit": "LocalLLaMA"}}
]}}

HF_JSON = [{"id": "1234", "title": "HF Paper Title", "publishedAt": "2025-10-20T08:00:00Z",
            "summary": "A paper about X.", "paper": {"id": "1234", "title": "HF Paper Title"}}]


class ParseFeedTest(unittest.TestCase):
    def test_rss(self):
        items = fetch.parse_feed(RSS_XML)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["title"], "Hello World Model")
        self.assertEqual(it["link"], "https://example.com/hello-world-model")
        self.assertEqual(it["guid"], "https://example.com/hello-world-model")
        self.assertIsNotNone(it["published"])
        self.assertEqual(it["summary"], "A new world model for agents.")

    def test_atom(self):
        items = fetch.parse_feed(ATOM_XML)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["title"], "Atom Entry")
        self.assertEqual(it["link"], "https://example.com/atom-entry")
        self.assertEqual(it["guid"], "tag:example.com,2025:1")
        self.assertIsNotNone(it["published"])

    def test_malformed(self):
        self.assertEqual(fetch.parse_feed("<not xml"), [])


class ParseJsonTest(unittest.TestCase):
    def test_hn(self):
        items = fetch.parse_hn(HN_JSON)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["guid"], "12345")
        self.assertEqual(items[0]["link"], "https://example.com/gpt5")
        self.assertEqual(items[0]["summary"], "120 points, 45 comments")
        self.assertIsNotNone(items[0]["published"])
        self.assertTrue(items[1]["link"].startswith("https://news.ycombinator.com/"))

    def test_reddit(self):
        items = fetch.parse_reddit(REDDIT_JSON)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["guid"], "t3_abc123")
        self.assertEqual(it["link"], "https://www.reddit.com/r/LocalLLaMA/comments/abc123/x/")
        self.assertIn("score 200", it["summary"])
        self.assertIsNotNone(it["published"])

    def test_hf(self):
        items = fetch.parse_hf(HF_JSON)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["guid"], "hf:1234")
        self.assertEqual(it["link"], "https://huggingface.co/papers/1234")
        self.assertEqual(it["title"], "HF Paper Title")


class UrlAndTokenTest(unittest.TestCase):
    def test_canonical_url(self):
        self.assertEqual(fetch.canonical_url("https://www.example.com/path?utm_source=x#frag"),
                         "example.com/path")
        self.assertEqual(fetch.canonical_url("HTTP://Example.com/a/b/"), "example.com/a/b")
        self.assertEqual(fetch.canonical_url(""), "")

    def test_extract_arxiv_id(self):
        self.assertEqual(fetch.extract_arxiv_id("https://arxiv.org/abs/2501.00001v2"), "2501.00001")
        self.assertEqual(fetch.extract_arxiv_id("https://example.com/no-id"), None)
        self.assertEqual(fetch.extract_arxiv_ids("see 2501.00001 and 2501.00002"),
                         {"2501.00001", "2501.00002"})

    def test_tokenize(self):
        toks = fetch.tokenize("Fine-tuning Mamba-2 models!")
        self.assertEqual(toks, {"fine", "tuning", "mamba", "models"})

    def test_jaccard(self):
        self.assertEqual(fetch.jaccard({"a", "b"}, {"b", "c"}), 1 / 3)
        self.assertEqual(fetch.jaccard(set(), {"a"}), 0.0)


class LinkingTest(unittest.TestCase):
    def test_same_url(self):
        a = {"url_key": "x.com/a", "source_id": "s1"}
        b = {"url_key": "x.com/a", "source_id": "s2"}
        self.assertTrue(fetch.items_linked(a, b))

    def test_same_arxiv(self):
        a = {"arxiv_ids": {"2501.00001"}, "source_id": "arxiv"}
        b = {"arxiv_ids": {"2501.00001"}, "source_id": "hn"}
        self.assertTrue(fetch.items_linked(a, b))

    def test_similar_titles(self):
        toks = {"mamba", "two", "transformer", "hybrid"}
        a = {"tokens": toks, "source_id": "arxiv"}
        b = {"tokens": toks, "source_id": "hn"}
        self.assertTrue(fetch.items_linked(a, b))

    def test_same_source_not_linked(self):
        a = {"tokens": {"aaa", "bbb", "ccc", "ddd"}, "source_id": "s1"}
        b = {"tokens": {"eee", "fff", "ggg", "hhh"}, "source_id": "s1"}
        self.assertFalse(fetch.items_linked(a, b))

    def test_unrelated(self):
        a = {"tokens": {"aaa", "bbb", "ccc", "ddd"}, "source_id": "arxiv"}
        b = {"tokens": {"eee", "fff", "ggg", "hhh"}, "source_id": "hn"}
        self.assertFalse(fetch.items_linked(a, b))


class ClusterTest(unittest.TestCase):
    def test_clusters_similar_titles(self):
        items = [
            {"title": "Mamba-2 is a Hybrid Linear Attention Transformer", "summary": "", "link": "https://a.com/1", "source_id": "arxiv"},
            {"title": "Mamba-2 is a Hybrid Linear Attention Transformer", "summary": "", "link": "https://b.com/2", "source_id": "hn"},
            {"title": "Unrelated thing about ketchup", "summary": "", "link": "https://c.com/3", "source_id": "arxiv"},
        ]
        groups = fetch.cluster_items(items)
        sizes = sorted(len(g) for g in groups)
        self.assertEqual(sizes, [1, 2])

    def test_build_stories(self):
        items = [
            {"title": "State World Models for agents", "summary": "", "link": "https://a.com/1",
             "source_id": "arxiv", "source_name": "arXiv", "category": "academic-papers", "tier": 1,
             "published": "2025-10-20T08:00:00+00:00"},
            {"title": "State World Models for agents", "summary": "", "link": "https://b.com/2",
             "source_id": "hn", "source_name": "Hacker News", "category": "communities", "tier": 2,
             "published": "2025-10-20T09:00:00+00:00"},
        ]
        stories = fetch.build_stories(items)
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["tag"], "discovery")
        self.assertEqual(len(stories[0]["sources"]), 2)


class StoryTagTest(unittest.TestCase):
    def test_discovery(self):
        self.assertEqual(fetch.story_tag({"academic-papers", "communities"}, {"arxiv", "hn"}), "discovery")

    def test_opportunity(self):
        self.assertEqual(fetch.story_tag({"industry-news", "communities"}, {"tc", "hn"}), "opportunity")

    def test_corroborated(self):
        self.assertEqual(fetch.story_tag({"academic-papers"}, {"arxiv", "hf"}), "corroborated")

    def test_single_source_story(self):
        self.assertEqual(fetch.story_tag({"communities"}, {"hn"}), "story")


class TagItemTest(unittest.TestCase):
    def test_rl_and_agents(self):
        tags = fetch.tag_item("New RLHF reward model for agents", "")
        self.assertIn("rl", tags)
        self.assertIn("agents", tags)

    def test_evals_and_multimodal(self):
        tags = fetch.tag_item("Benchmarking diffusion video generation", "")
        self.assertIn("evals", tags)
        self.assertIn("multimodal", tags)

    def test_empty(self):
        self.assertEqual(fetch.tag_item("", ""), [])

    def test_serialize_includes_tags(self):
        it = {"key": "a::1", "title": "New RLHF reward model for agents", "link": "https://x.com",
              "guid": "1", "published": datetime(2025, 10, 20, tzinfo=timezone.utc)}
        src = {"id": "a", "name": "A", "category": "academic-papers", "tier": 1}
        out = fetch.serialize_item(it, src)
        self.assertIn("rl", out["tags"])


class PruneTest(unittest.TestCase):
    def test_removes_old(self):
        old = datetime.now(timezone.utc) - timedelta(days=20)
        fresh = datetime.now(timezone.utc) - timedelta(days=1)
        items = [
            {"key": "old", "fetched_at": old.isoformat()},
            {"key": "new", "fetched_at": fresh.isoformat()},
        ]
        kept = fetch.prune_items(items)
        self.assertEqual([k["key"] for k in kept], ["new"])


class HttpTest(unittest.TestCase):
    @mock.patch("fetch.urllib.request.urlopen")
    def test_304_returns_none(self, m_urlopen):
        err = urllib.error.HTTPError("u", 304, "Not Modified", {}, None)
        m_urlopen.side_effect = [err]
        data, etag, lm = fetch.http_get_with_meta("https://x.com/feed")
        self.assertIsNone(data)

    @mock.patch("fetch.time.sleep")
    @mock.patch("fetch.urllib.request.urlopen")
    def test_retries_500_then_succeeds(self, m_urlopen, m_sleep):
        resp = mock.MagicMock()
        resp.read.return_value = b"<rss/>"
        resp.headers = {}
        resp.__enter__.return_value = resp
        err = urllib.error.HTTPError("u", 500, "Server Error", {}, None)
        m_urlopen.side_effect = [err, resp]
        data, etag, lm = fetch.http_get_with_meta("https://x.com/feed")
        self.assertEqual(data, b"<rss/>")
        m_sleep.assert_called()

    @mock.patch("fetch.urllib.request.urlopen")
    def test_404_raises(self, m_urlopen):
        err = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        m_urlopen.side_effect = [err]
        with self.assertRaises(urllib.error.HTTPError):
            fetch.http_get_with_meta("https://x.com/nope")


if __name__ == "__main__":
    unittest.main()
