"""
Test suite for JARVIS Personality Message Formatter.
Verifies tone, structure, factual preservation, WhatsApp formatting, and author identity.
Author: pugazhenthi
"""

from __future__ import annotations

import unittest
from core.message_formatter import (
    format_as_jarvis_message,
    AUTHOR_NAME,
    _clean_robotic_intros,
    _detect_context,
)


class TestMessageFormatter(unittest.TestCase):
    def test_author_identity(self):
        self.assertEqual(AUTHOR_NAME, "pugazhenthi")

    def test_weather_personality_and_factual_preservation(self):
        raw = "The weather today is 31°C. There is a 60% chance of rain."
        formatted = format_as_jarvis_message(raw)
        self.assertIn("31°C", formatted)
        self.assertIn("60% chance of rain", formatted)
        self.assertTrue(formatted.startswith("Sir,"))
        self.assertIn("umbrella", formatted.lower())

    def test_task_completed_personality(self):
        raw = "Your task has been completed successfully."
        formatted = format_as_jarvis_message(raw, context="task_completion")
        self.assertTrue(formatted.startswith("Done, sir. ✅"))
        self.assertIn("completed successfully", formatted)

    def test_system_alert_personality(self):
        raw = "CPU usage has reached 91%."
        formatted = format_as_jarvis_message(raw, context="system_alert")
        self.assertIn("⚠️", formatted)
        self.assertIn("91%", formatted)
        self.assertIn("Sir", formatted)

        # Memory usage status
        raw_mem = "The system is currently using 82% memory."
        formatted_mem = format_as_jarvis_message(raw_mem, context="status_update")
        self.assertIn("82%", formatted_mem)
        self.assertIn("Sir", formatted_mem)

    def test_technical_results_formatting(self):
        raw = (
            "Host: 192.168.1.10\n"
            "Status: Online\n"
            "Port: 443\n"
            "Service: HTTPS"
        )
        formatted = format_as_jarvis_message(raw, context="technical_result")
        self.assertIn("192.168.1.10", formatted)
        self.assertIn("443", formatted)
        self.assertIn("HTTPS", formatted)
        self.assertIn("• *Host*: 192.168.1.10", formatted)
        self.assertIn("• *Port*: 443", formatted)

    def test_strip_robotic_cliches(self):
        cases = [
            ("Here is the information you requested: Disk space is 120GB.", "Disk space is 120GB."),
            ("Sure, I can help you with that. The file is ready.", "The file is ready."),
            ("According to my analysis, network latency is 24ms.", "Network latency is 24ms."),
            ("Please find below the details: Port 22 is open.", "Port 22 is open."),
        ]
        for input_text, expected_core in cases:
            cleaned = _clean_robotic_intros(input_text)
            self.assertIn(expected_core.lower(), cleaned.lower())
            self.assertNotIn("here is the information", cleaned.lower())
            self.assertNotIn("sure, i can help", cleaned.lower())
            self.assertNotIn("according to my analysis", cleaned.lower())

    def test_context_detection(self):
        self.assertEqual(_detect_context("⚠️ Warning: High temperature detected"), "system_alert")
        self.assertEqual(_detect_context("Done with the data download"), "task_completion")
        self.assertEqual(_detect_context("Weather forecast is 28°C"), "status_update")
        self.assertEqual(_detect_context("Host: 10.0.0.1 Port: 80"), "technical_result")
        self.assertEqual(_detect_context("Reminder: Meeting at 3pm"), "reminder")

    def test_never_modifies_critical_facts(self):
        raw = "Server 10.14.88.2 failed on 2026-09-14 with error code 500 at https://api.service.internal"
        formatted = format_as_jarvis_message(raw)
        self.assertIn("10.14.88.2", formatted)
        self.assertIn("2026-09-14", formatted)
        self.assertIn("500", formatted)
        self.assertIn("https://api.service.internal", formatted)


if __name__ == "__main__":
    unittest.main()
