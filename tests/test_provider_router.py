"""
tests/test_provider_router.py — Unit tests for the AI Provider Auto-Switching system.

Tests cover:
  • Budget tracking and threshold-based switching
  • Model round-robin rotation
  • Error fallback chain (Model A → B → C → Groq)
  • Rate limit handling
  • Usage persistence
  • Status reporting
  • Environment variable loading
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestProviderRouterBudget(unittest.TestCase):
    """Budget tracking and threshold-based switching."""

    def _make_router(self, budget=1.0, spent=0.0, or_key="sk-or-test", groq_key="gsk-test"):
        """Create a ProviderRouter with controlled state."""
        from core.provider_router import ProviderRouter

        env = {"OPENROUTER_BUDGET": str(budget)}
        if or_key:
            env["OPENROUTER_API_KEY"] = or_key
        if groq_key:
            env["GROQ_API_KEY"] = groq_key

        # Clear any real env vars that might interfere
        clear = {k: "" for k in ("OPENROUTER_API_KEY", "GROQ_API_KEY", "OPENROUTER_BUDGET")}
        clear.update(env)

        with patch.dict(os.environ, clear, clear=False), \
             patch("core.provider_router._load_dotenv", return_value={}), \
             patch("core.provider_router.USAGE_PATH") as mock_path:
            mock_path.exists.return_value = False
            mock_path.read_text.side_effect = FileNotFoundError
            router = ProviderRouter()

        # Inject pre-existing spend
        router._usage["total_spent"] = spent
        return router

    def test_budget_available_when_under_threshold(self):
        router = self._make_router(budget=1.0, spent=0.50)
        self.assertTrue(router._is_budget_available())

    def test_budget_exhausted_when_at_threshold(self):
        router = self._make_router(budget=1.0, spent=1.0)
        self.assertFalse(router._is_budget_available())

    def test_budget_exhausted_when_over_threshold(self):
        router = self._make_router(budget=1.0, spent=1.50)
        self.assertFalse(router._is_budget_available())

    def test_selects_openrouter_when_budget_available(self):
        router = self._make_router(budget=1.0, spent=0.0)
        provider, model, key, base = router._select_provider()
        self.assertEqual(provider, "openrouter")
        self.assertIn(model, router._openrouter_models)

    def test_selects_groq_when_budget_exhausted(self):
        router = self._make_router(budget=1.0, spent=1.0)
        provider, model, key, base = router._select_provider()
        self.assertEqual(provider, "groq")
        self.assertEqual(model, router._groq_model)

    def test_selects_groq_when_no_openrouter_key(self):
        router = self._make_router(or_key="", groq_key="gsk-test")
        provider, model, key, base = router._select_provider()
        self.assertEqual(provider, "groq")

    def test_raises_when_no_keys(self):
        router = self._make_router(or_key="", groq_key="")
        with self.assertRaises(RuntimeError):
            router._select_provider()


class TestProviderRouterModelRotation(unittest.TestCase):
    """Model round-robin rotation."""

    def _make_router(self):
        from core.provider_router import ProviderRouter
        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "sk-or-test",
            "GROQ_API_KEY": "gsk-test",
            "OPENROUTER_BUDGET": "10.0",
        }), patch("core.provider_router._load_dotenv", return_value={}), \
             patch("core.provider_router.USAGE_PATH") as mock_path:
            mock_path.exists.return_value = False
            mock_path.read_text.side_effect = FileNotFoundError
            router = ProviderRouter()
        return router

    def test_round_robin_cycles_through_all_models(self):
        router = self._make_router()
        models = router._openrouter_models
        n = len(models)
        self.assertGreater(n, 0)

        # Cycle through all models twice
        seen = []
        for _ in range(n * 2):
            m = router._next_openrouter_model()
            seen.append(m)

        # First cycle should match model list order
        self.assertEqual(seen[:n], models)
        # Second cycle should repeat
        self.assertEqual(seen[n:], models)

    def test_current_model_does_not_advance(self):
        router = self._make_router()
        m1 = router._current_openrouter_model()
        m2 = router._current_openrouter_model()
        self.assertEqual(m1, m2)

    def test_next_model_advances(self):
        router = self._make_router()
        if len(router._openrouter_models) < 2:
            self.skipTest("Need at least 2 models")
        m1 = router._next_openrouter_model()
        m2 = router._next_openrouter_model()
        self.assertNotEqual(m1, m2)


class TestProviderRouterUsageRecording(unittest.TestCase):
    """Usage recording and persistence."""

    def _make_router(self):
        from core.provider_router import ProviderRouter
        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "sk-or-test",
            "GROQ_API_KEY": "gsk-test",
            "OPENROUTER_BUDGET": "1.0",
        }), patch("core.provider_router._load_dotenv", return_value={}), \
             patch("core.provider_router.USAGE_PATH") as mock_path:
            mock_path.exists.return_value = False
            mock_path.read_text.side_effect = FileNotFoundError
            router = ProviderRouter()
        return router

    def test_record_openrouter_usage_increments_counters(self):
        router = self._make_router()
        initial_spent = router._usage["total_spent"]

        with patch.object(router, "_save_usage"):
            router._record_usage("openrouter", "test-model", 100, 50, 0.001, "success")

        self.assertEqual(router._usage["total_requests"], 1)
        self.assertEqual(router._usage["openrouter_requests"], 1)
        self.assertEqual(router._usage["groq_requests"], 0)
        self.assertAlmostEqual(router._usage["total_spent"], initial_spent + 0.001)

    def test_record_groq_usage_does_not_add_cost(self):
        router = self._make_router()

        with patch.object(router, "_save_usage"):
            router._record_usage("groq", "llama-3.2-3b-preview", 100, 50, 0.0, "success")

        self.assertEqual(router._usage["total_requests"], 1)
        self.assertEqual(router._usage["groq_requests"], 1)
        self.assertEqual(router._usage["openrouter_requests"], 0)
        self.assertEqual(router._usage["total_spent"], 0.0)

    def test_history_entry_structure(self):
        router = self._make_router()

        with patch.object(router, "_save_usage"):
            router._record_usage("openrouter", "test-model", 100, 50, 0.001, "success")

        entry = router._usage["history"][-1]
        self.assertIn("timestamp", entry)
        self.assertEqual(entry["provider"], "openrouter")
        self.assertEqual(entry["model"], "test-model")
        self.assertEqual(entry["prompt_tokens"], 100)
        self.assertEqual(entry["completion_tokens"], 50)
        self.assertEqual(entry["estimated_cost"], 0.001)
        self.assertEqual(entry["status"], "success")


class TestProviderRouterCostEstimation(unittest.TestCase):
    """Cost estimation using the configured cost table."""

    def _make_router(self):
        from core.provider_router import ProviderRouter
        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "sk-or-test",
            "GROQ_API_KEY": "gsk-test",
            "OPENROUTER_BUDGET": "1.0",
        }), patch("core.provider_router._load_dotenv", return_value={}), \
             patch("core.provider_router.USAGE_PATH") as mock_path:
            mock_path.exists.return_value = False
            mock_path.read_text.side_effect = FileNotFoundError
            router = ProviderRouter()
        return router

    def test_cost_for_known_model(self):
        router = self._make_router()
        # 1M prompt tokens at $0.06/M = $0.06
        cost = router._estimate_cost("meta-llama/llama-3.2-3b-instruct", 1_000_000, 0)
        self.assertAlmostEqual(cost, 0.06, places=4)

    def test_cost_for_free_model(self):
        router = self._make_router()
        cost = router._estimate_cost("google/gemma-2-9b-it:free", 1_000_000, 1_000_000)
        self.assertAlmostEqual(cost, 0.0, places=4)

    def test_cost_for_unknown_model_uses_default(self):
        router = self._make_router()
        # Unknown model should use fallback rate ($0.10/M)
        cost = router._estimate_cost("unknown/model", 1_000_000, 0)
        self.assertAlmostEqual(cost, 0.10, places=4)

    def test_cost_includes_both_prompt_and_completion(self):
        router = self._make_router()
        # 500K prompt + 500K completion at $0.06/M each = $0.06
        cost = router._estimate_cost(
            "meta-llama/llama-3.2-3b-instruct", 500_000, 500_000
        )
        self.assertAlmostEqual(cost, 0.06, places=4)


class TestProviderRouterErrorFallback(unittest.TestCase):
    """Error fallback chain: Model A → B → C → Groq."""

    def _make_router(self):
        from core.provider_router import ProviderRouter
        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "sk-or-test",
            "GROQ_API_KEY": "gsk-test",
            "OPENROUTER_BUDGET": "10.0",
        }), patch("core.provider_router._load_dotenv", return_value={}), \
             patch("core.provider_router.USAGE_PATH") as mock_path:
            mock_path.exists.return_value = False
            mock_path.read_text.side_effect = FileNotFoundError
            router = ProviderRouter()
        return router

    @patch("core.provider_router.requests.post")
    def test_falls_through_all_openrouter_models_to_groq(self, mock_post):
        """When all OpenRouter models fail, should fall through to Groq."""
        router = self._make_router()
        n_models = len(router._openrouter_models)

        # Set up mock: first N calls fail, then Groq succeeds
        fail_resp = MagicMock()
        fail_resp.raise_for_status.side_effect = Exception("rate limited")

        success_resp = MagicMock()
        success_resp.raise_for_status.return_value = None
        success_resp.json.return_value = {
            "choices": [{"message": {"content": "Hello from Groq", "tool_calls": None}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        mock_post.side_effect = [fail_resp] * n_models + [success_resp]

        result = router.call([{"role": "user", "content": "hi"}])
        self.assertEqual(result["content"], "Hello from Groq")
        # Should have tried all OpenRouter models + 1 Groq call
        self.assertEqual(mock_post.call_count, n_models + 1)

    @patch("core.provider_router.requests.post")
    def test_first_model_succeeds(self, mock_post):
        """When first model works, no fallback needed."""
        router = self._make_router()

        success_resp = MagicMock()
        success_resp.raise_for_status.return_value = None
        success_resp.json.return_value = {
            "choices": [{"message": {"content": "OK", "tool_calls": None}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_post.return_value = success_resp

        result = router.call([{"role": "user", "content": "hi"}])
        self.assertEqual(result["content"], "OK")
        self.assertEqual(mock_post.call_count, 1)

    @patch("core.provider_router.requests.post")
    def test_all_providers_fail_raises_error(self, mock_post):
        """When everything fails, should raise RuntimeError."""
        router = self._make_router()

        fail_resp = MagicMock()
        fail_resp.raise_for_status.side_effect = Exception("all broken")
        mock_post.return_value = fail_resp

        with self.assertRaises(RuntimeError) as ctx:
            router.call([{"role": "user", "content": "hi"}])
        self.assertIn("All providers failed", str(ctx.exception))


class TestProviderRouterStatus(unittest.TestCase):
    """Status reporting."""

    def _make_router(self, spent=0.0, budget=1.0):
        from core.provider_router import ProviderRouter
        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "sk-or-test",
            "GROQ_API_KEY": "gsk-test",
            "OPENROUTER_BUDGET": str(budget),
        }), patch("core.provider_router._load_dotenv", return_value={}), \
             patch("core.provider_router.USAGE_PATH") as mock_path:
            mock_path.exists.return_value = False
            mock_path.read_text.side_effect = FileNotFoundError
            router = ProviderRouter()
        router._usage["total_spent"] = spent
        return router

    def test_status_structure(self):
        router = self._make_router()
        status = router.get_status()

        required_keys = [
            "provider", "model", "fallback", "budget",
            "spent", "remaining", "budget_exhausted",
            "total_requests", "openrouter_requests", "groq_requests",
        ]
        for key in required_keys:
            self.assertIn(key, status, f"Missing key: {key}")

    def test_status_shows_openrouter_when_budget_available(self):
        router = self._make_router(spent=0.5, budget=1.0)
        status = router.get_status()
        self.assertEqual(status["provider"], "OPENROUTER")
        self.assertEqual(status["budget"], 1.0)
        self.assertAlmostEqual(status["remaining"], 0.5, places=4)
        self.assertFalse(status["budget_exhausted"])

    def test_status_shows_groq_when_budget_exhausted(self):
        router = self._make_router(spent=1.0, budget=1.0)
        status = router.get_status()
        self.assertEqual(status["provider"], "GROQ")
        self.assertTrue(status["budget_exhausted"])
        self.assertAlmostEqual(status["remaining"], 0.0, places=4)

    def test_status_never_exposes_api_keys(self):
        router = self._make_router()
        status = router.get_status()
        status_str = json.dumps(status)
        self.assertNotIn("sk-or-test", status_str)
        self.assertNotIn("gsk-test", status_str)

    def test_status_fallback_shows_groq(self):
        router = self._make_router()
        status = router.get_status()
        self.assertEqual(status["fallback"], "GROQ")


class TestProviderRouterResponseParsing(unittest.TestCase):
    """Response parsing for OpenAI-compatible format."""

    def _make_router(self):
        from core.provider_router import ProviderRouter
        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "sk-or-test",
            "GROQ_API_KEY": "gsk-test",
            "OPENROUTER_BUDGET": "1.0",
        }), patch("core.provider_router._load_dotenv", return_value={}), \
             patch("core.provider_router.USAGE_PATH") as mock_path:
            mock_path.exists.return_value = False
            mock_path.read_text.side_effect = FileNotFoundError
            router = ProviderRouter()
        return router

    def test_parse_simple_response(self):
        router = self._make_router()
        data = {
            "choices": [{"message": {"content": "Hello world", "tool_calls": None}}],
        }
        result = router._parse_response(data)
        self.assertEqual(result["content"], "Hello world")
        self.assertEqual(result["tool_calls"], [])

    def test_parse_response_with_tool_calls(self):
        router = self._make_router()
        data = {
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "id": "call_123",
                        "function": {
                            "name": "open_app",
                            "arguments": '{"app_name": "Chrome"}'
                        }
                    }]
                }
            }],
        }
        result = router._parse_response(data)
        self.assertEqual(len(result["tool_calls"]), 1)
        tc = result["tool_calls"][0]
        self.assertEqual(tc["function"]["name"], "open_app")
        self.assertEqual(tc["function"]["arguments"], {"app_name": "Chrome"})

    def test_parse_empty_response(self):
        router = self._make_router()
        data = {"choices": [{}]}
        result = router._parse_response(data)
        self.assertEqual(result["content"], "")
        self.assertEqual(result["tool_calls"], [])


class TestProviderRouterUsageReset(unittest.TestCase):
    """Usage reset functionality."""

    def _make_router(self):
        from core.provider_router import ProviderRouter
        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "sk-or-test",
            "GROQ_API_KEY": "gsk-test",
            "OPENROUTER_BUDGET": "1.0",
        }), patch("core.provider_router._load_dotenv", return_value={}), \
             patch("core.provider_router.USAGE_PATH") as mock_path:
            mock_path.exists.return_value = False
            mock_path.read_text.side_effect = FileNotFoundError
            router = ProviderRouter()
        return router

    def test_reset_clears_all_counters(self):
        router = self._make_router()
        router._usage["total_spent"] = 0.75
        router._usage["total_requests"] = 42
        router._usage["openrouter_requests"] = 38
        router._usage["groq_requests"] = 4

        with patch.object(router, "_save_usage"):
            router.reset_usage()

        self.assertEqual(router._usage["total_spent"], 0.0)
        self.assertEqual(router._usage["total_requests"], 0)
        self.assertEqual(router._usage["openrouter_requests"], 0)
        self.assertEqual(router._usage["groq_requests"], 0)
        self.assertIsNotNone(router._usage["last_reset"])

    def test_reset_restores_budget_availability(self):
        router = self._make_router()
        router._usage["total_spent"] = 1.50
        self.assertFalse(router._is_budget_available())

        with patch.object(router, "_save_usage"):
            router.reset_usage()

        self.assertTrue(router._is_budget_available())


class TestProviderRouterHeaders(unittest.TestCase):
    """HTTP header construction."""

    def _make_router(self):
        from core.provider_router import ProviderRouter
        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "sk-or-test",
            "GROQ_API_KEY": "gsk-test",
            "OPENROUTER_BUDGET": "1.0",
        }), patch("core.provider_router._load_dotenv", return_value={}), \
             patch("core.provider_router.USAGE_PATH") as mock_path:
            mock_path.exists.return_value = False
            mock_path.read_text.side_effect = FileNotFoundError
            router = ProviderRouter()
        return router

    def test_openrouter_headers_include_referer(self):
        router = self._make_router()
        headers = router._build_headers("sk-or-test", "openrouter")
        self.assertEqual(headers["Authorization"], "Bearer sk-or-test")
        self.assertIn("HTTP-Referer", headers)
        self.assertIn("X-Title", headers)

    def test_groq_headers_no_referer(self):
        router = self._make_router()
        headers = router._build_headers("gsk-test", "groq")
        self.assertEqual(headers["Authorization"], "Bearer gsk-test")
        self.assertNotIn("HTTP-Referer", headers)
        self.assertNotIn("X-Title", headers)


if __name__ == "__main__":
    unittest.main()
