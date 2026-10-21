import json
import unittest
import urllib.error
from unittest import mock

import ideas


class FingerprintTest(unittest.TestCase):
    def test_stable_for_same_input(self):
        items = [{"fetched_at": "2026-10-21T00:00:00+00:00"}]
        a = ideas.compute_fingerprint(items, "stories text")
        b = ideas.compute_fingerprint(items, "stories text")
        self.assertEqual(a, b)

    def test_changes_when_items_change(self):
        a = ideas.compute_fingerprint([{"fetched_at": "2026-10-20T00:00:00+00:00"}], "s")
        b = ideas.compute_fingerprint([{"fetched_at": "2026-10-21T00:00:00+00:00"}], "s")
        self.assertNotEqual(a, b)

    def test_changes_when_stories_change(self):
        a = ideas.compute_fingerprint([{"fetched_at": "2026-10-21T00:00:00+00:00"}], "s1")
        b = ideas.compute_fingerprint([{"fetched_at": "2026-10-21T00:00:00+00:00"}], "s2")
        self.assertNotEqual(a, b)

    def test_changes_when_days_change(self):
        a = ideas.compute_fingerprint([{"fetched_at": "2026-10-21T00:00:00+00:00"}], "s", days=7)
        b = ideas.compute_fingerprint([{"fetched_at": "2026-10-21T00:00:00+00:00"}], "s", days=14)
        self.assertNotEqual(a, b)


class BuildPromptTest(unittest.TestCase):
    def test_includes_stories_and_context(self):
        prompt = ideas.build_prompt("CONTEXT", "STORIES")
        self.assertIn("STORIES", prompt)
        self.assertIn("CONTEXT", prompt)


def _resp(payload):
    r = mock.MagicMock()
    r.read.return_value = json.dumps(payload).encode("utf-8")
    return r


class CallLlmTest(unittest.TestCase):
    @mock.patch("ideas.urllib.request.urlopen")
    def test_success(self, m_urlopen):
        m_urlopen.return_value.__enter__.return_value = _resp({
            "choices": [{"message": {"content": "# Ideas"}, "finish_reason": "stop"}]
        })
        self.assertEqual(ideas.call_llm("p", "m", "k"), "# Ideas")

    @mock.patch("ideas.urllib.request.urlopen")
    def test_length_raises_truncated(self, m_urlopen):
        m_urlopen.return_value.__enter__.return_value = _resp({
            "choices": [{"message": {"content": None}, "finish_reason": "length"}]
        })
        with self.assertRaises(ideas.TruncatedError):
            ideas.call_llm("p", "m", "k")


class RetryTest(unittest.TestCase):
    @mock.patch("ideas.time.sleep")
    def test_retries_on_5xx(self, m_sleep):
        err = urllib.error.HTTPError("u", 500, "Server Error", {}, None)
        with mock.patch.object(ideas, "call_llm", side_effect=[err, "ok"]) as m:
            self.assertEqual(ideas.call_llm_with_retries("p", "m", "k"), "ok")
        self.assertEqual(m.call_count, 2)
        m_sleep.assert_called()

    def test_no_retry_on_4xx(self):
        err = urllib.error.HTTPError("u", 400, "Bad Request", {}, None)
        with mock.patch.object(ideas, "call_llm", side_effect=[err]) as m:
            with self.assertRaises(urllib.error.HTTPError):
                ideas.call_llm_with_retries("p", "m", "k")
        self.assertEqual(m.call_count, 1)

    def test_truncation_not_swallowed(self):
        with mock.patch.object(ideas, "call_llm", side_effect=[ideas.TruncatedError("x")]) as m:
            with self.assertRaises(ideas.TruncatedError):
                ideas.call_llm_with_retries("p", "m", "k")
        self.assertEqual(m.call_count, 1)


class GenerateTest(unittest.TestCase):
    def test_retries_with_smaller_context_on_truncation(self):
        items = [{"title": "t", "fetched_at": "2026-10-21T00:00:00+00:00"}]
        calls = []
        real = ideas.build_context

        def spy(items, days, max_items=ideas.MAX_ITEMS):
            calls.append(max_items)
            return real(items, days, max_items=max_items)

        with mock.patch.object(ideas, "build_context", side_effect=spy), \
             mock.patch.object(ideas, "call_llm_with_retries",
                               side_effect=[ideas.TruncatedError("len"), "ok"]):
            self.assertEqual(ideas.generate(items, "stories", "m", "k", None), "ok")
        self.assertEqual(calls, [ideas.MAX_ITEMS, ideas.MAX_ITEMS // 2])


if __name__ == "__main__":
    unittest.main()
