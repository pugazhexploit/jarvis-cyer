"""
tests/test_search_lifecycle.py
Tests the complete trace flow:
Web Search -> Search Response -> State/Store -> Dashboard UI Rendering
"""

import unittest
from core.search_store import search_store, parse_search_response


class TestSearchLifecycle(unittest.TestCase):

    def test_parse_numbered_results(self):
        mock_raw = (
            "1. OpenAI Announces Frontier Reasoning Model\n"
            "   OpenAI has unveiled its latest model with high reasoning fidelity and speed.\n"
            "   Source: https://openai.com/news/frontier/\n\n"
            "2. Quantum Computing Breakthrough\n"
            "   Researchers demonstrate logical qubits with low error rates.\n"
            "   Source: https://nature.com/articles/qc-2026"
        )

        status, items, msg = parse_search_response(mock_raw, "quantum ai")
        self.assertEqual(status, "success")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "OpenAI Announces Frontier Reasoning Model")
        self.assertEqual(items[0]["url"], "https://openai.com/news/frontier/")
        self.assertIn("reasoning fidelity", items[0]["snippet"])
        self.assertEqual(items[0]["source"], "openai.com")

        self.assertEqual(items[1]["title"], "Quantum Computing Breakthrough")
        self.assertEqual(items[1]["url"], "https://nature.com/articles/qc-2026")
        self.assertEqual(items[1]["source"], "nature.com")

    def test_parse_empty_and_error(self):
        status, items, msg = parse_search_response("No results found for xyz.", "xyz")
        self.assertEqual(status, "empty")
        self.assertEqual(len(items), 0)

        status, items, msg = parse_search_response("Search failed: Network timeout", "query")
        self.assertEqual(status, "error")
        self.assertEqual(len(items), 0)
        self.assertIn("Network timeout", msg)

    def test_html_rendering(self):
        state = {
            "status": "success",
            "query": "artificial intelligence",
            "mode": "search",
            "results": [
                {
                    "title": "AI Breakthrough",
                    "url": "https://example.com/ai",
                    "snippet": "Exciting advancements in artificial intelligence.",
                    "source": "example.com",
                }
            ],
        }
        html = search_store.to_html(state)
        self.assertIn('href="https://example.com/ai"', html)
        self.assertIn("AI Breakthrough", html)
        self.assertIn("example.com", html)
        self.assertIn("Exciting advancements", html)

    def test_loading_and_error_html(self):
        loading_state = {
            "status": "loading",
            "query": "supercomputing",
            "mode": "research",
            "results": [],
        }
        loading_html = search_store.to_html(loading_state)
        self.assertIn("SEARCHING REAL-TIME WEB INTELLIGENCE", loading_html)
        self.assertIn("supercomputing", loading_html)

        err_state = {
            "status": "error",
            "query": "offline site",
            "mode": "search",
            "results": [],
            "error": "Connection timed out",
        }
        err_html = search_store.to_html(err_state)
        self.assertIn("SEARCH ERROR", err_html)
        self.assertIn("Connection timed out", err_html)

    def test_store_subscriber_lifecycle(self):
        transitions = []
        def listener(st):
            transitions.append(st["status"])

        search_store.subscribe(listener)
        try:
            search_store.start_search("test query", "search")
            self.assertEqual(transitions[-1], "loading")

            search_store.set_response("test query", "search", "1. Title\n   Snippet\n   Source: https://foo.bar")
            self.assertEqual(transitions[-1], "success")

            search_store.set_empty("empty query", "search", "No items")
            self.assertEqual(transitions[-1], "empty")

            search_store.set_error("err query", "search", "Fatal crash")
            self.assertEqual(transitions[-1], "error")
        finally:
            search_store.unsubscribe(listener)


if __name__ == "__main__":
    unittest.main()
