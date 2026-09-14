"""
Test suite for JARVIS Terminal Plugin using unittest.
Covers safety layer, WSL execution, session state, audit logging, and plugin discovery.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from plugins.terminal.safety import SafetyLayer
from plugins.terminal.session import TerminalSession
from plugins.terminal.logger import AuditLogger
from plugins.terminal.wsl import WSLController
from plugins.terminal.terminal import JarvisTerminal
from plugins import jarvis_terminal
from core.plugin_loader import discover_plugins


class DummyPlayer:
    """Mock JarvisUI player for testing log and content displays."""
    def __init__(self):
        self.logs = []
        self.contents = []

    def write_log(self, text: str):
        self.logs.append(text)

    def show_content(self, title: str, text: str):
        self.contents.append((title, text))


class TestSafetyLayer(unittest.TestCase):
    def setUp(self):
        self.safety = SafetyLayer()

    def test_safe_commands(self):
        for cmd in ["whoami", "pwd", "ls -la", "uname -a", "ip a", "ps aux", "cat file.txt"]:
            res = self.safety.validate_command(cmd)
            self.assertTrue(res.is_allowed, f"Command '{cmd}' should be allowed.")
            self.assertFalse(res.requires_confirmation)

    def test_sudo_requires_confirmation(self):
        cmd = "sudo apt update"
        res = self.safety.validate_command(cmd, confirmed=False)
        self.assertFalse(res.is_allowed)
        self.assertTrue(res.requires_confirmation)
        self.assertEqual(res.category, "sudo")
        self.assertIn("Execute with sudo? [Confirm] [Cancel]", res.confirmation_prompt)

        # Confirmed execution
        res_confirmed = self.safety.validate_command(cmd, confirmed=True)
        self.assertTrue(res_confirmed.is_allowed)

    def test_destructive_commands(self):
        destructive_commands = [
            "rm -rf /tmp/test",
            "rmdir mydir",
            "dd if=/dev/zero of=/dev/sda",
            "mkfs.ext4 /dev/sdb",
            "fdisk /dev/sda",
            "shutdown -h now",
            "reboot",
            "chmod -R 777 /var",
        ]
        for cmd in destructive_commands:
            res = self.safety.validate_command(cmd, confirmed=False)
            self.assertFalse(res.is_allowed, f"Command '{cmd}' should require confirmation.")
            self.assertTrue(res.requires_confirmation)
            self.assertEqual(res.category, "destructive")

            # When confirmed=True
            res_confirmed = self.safety.validate_command(cmd, confirmed=True)
            self.assertTrue(res_confirmed.is_allowed)

    def test_security_tools_require_confirmation(self):
        tools = ["nmap -sV 127.0.0.1", "nikto -h localhost", "sqlmap -u http://test", "gobuster dir -u http://test"]
        for cmd in tools:
            res = self.safety.validate_command(cmd, confirmed=False)
            self.assertFalse(res.is_allowed)
            self.assertTrue(res.requires_confirmation)
            self.assertEqual(res.category, "security_tool")

            res_confirmed = self.safety.validate_command(cmd, confirmed=True)
            self.assertTrue(res_confirmed.is_allowed)

    def test_secret_redaction(self):
        private_key = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----"
        sanitized = self.safety.sanitize_output(f"Output with {private_key}")
        self.assertIn("[REDACTED_PRIVATE_KEY]", sanitized)
        self.assertNotIn("MIIEow", sanitized)

        pw_cmd = "mysql -u root -p MySecretPassword123"
        sanitized_pw = self.safety.sanitize_output(pw_cmd)
        self.assertIn("[REDACTED_PASSWORD]", sanitized_pw)
        self.assertNotIn("MySecretPassword123", sanitized_pw)


class TestSessionAndLogger(unittest.TestCase):
    def test_terminal_session(self):
        session = TerminalSession(session_id="JARVIS-KALI-TEST", working_directory="/home/test")
        session.record_command("pwd", exit_code=0, duration=0.05, working_directory="/home/test", success=True)
        self.assertEqual(len(session.command_history), 1)
        self.assertEqual(session.last_command, "pwd")

        session.update_cwd("/var/log")
        self.assertEqual(session.working_directory, "/var/log")

    def test_audit_logger(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test_audit.log"
            logger = AuditLogger(log_path=log_file)
            logger.log_command("whoami", exit_code=0, duration=0.1, cwd="/home/kali")
            logger.log_command("cat api_key --password=supersecret", exit_code=0, duration=0.2, cwd="/home/kali")

            self.assertTrue(log_file.exists())
            content = log_file.read_text(encoding="utf-8")
            self.assertIn("whoami", content)
            self.assertNotIn("supersecret", content)
            self.assertIn("[REDACTED_PASSWORD]", content)

            lines = logger.get_history_lines()
            self.assertEqual(len(lines), 2)


class TestWSLIntegration(unittest.TestCase):
    def setUp(self):
        self.wsl = WSLController()

    def test_wsl_detection(self):
        self.assertTrue(self.wsl.is_wsl_installed(), "WSL should be detected as installed.")
        distro = self.wsl.detect_kali_distribution()
        self.assertIsNotNone(distro, "Kali Linux distribution should be detected.")
        self.assertIn("kali", distro.lower())

    def test_wsl_command_execution(self):
        distro = self.wsl.detect_kali_distribution()
        if not distro:
            self.skipTest("Kali Linux not installed in WSL.")

        res = self.wsl.execute_in_kali("whoami", timeout=15)
        self.assertTrue(res["success"], f"Failed to execute whoami: {res}")
        self.assertEqual(res["exit_code"], 0)
        self.assertGreater(len(res["stdout"].strip()), 0)
        self.assertGreater(res["duration"], 0.0)

    def test_wsl_persistent_cwd(self):
        distro = self.wsl.detect_kali_distribution()
        if not distro:
            self.skipTest("Kali Linux not installed in WSL.")

        # 1. cd to /tmp
        res1 = self.wsl.execute_in_kali("cd /tmp", timeout=15)
        self.assertTrue(res1["success"], f"Failed to cd /tmp: {res1}")
        self.assertEqual(res1["working_directory"], "/tmp")

        # 2. Next command should run from /tmp
        res2 = self.wsl.execute_in_kali("pwd", cwd="/tmp", timeout=15)
        self.assertTrue(res2["success"], f"Failed to pwd from /tmp: {res2}")
        self.assertEqual(res2["stdout"].strip(), "/tmp")


class TestJarvisTerminalClass(unittest.TestCase):
    def setUp(self):
        self.term = JarvisTerminal.get_instance()

    def test_execute_safe_command(self):
        if not self.term.is_available():
            self.skipTest("Kali Linux WSL not available.")

        res = self.term.execute("whoami")
        self.assertTrue(res["success"], f"JarvisTerminal execute failed: {res}")
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("environment", res)
        self.assertIn("kali", res["environment"].lower())

    def test_sudo_gate(self):
        res = self.term.execute("sudo whoami", confirmed=False)
        self.assertFalse(res["success"])
        self.assertTrue(res["requires_confirmation"])
        self.assertIn("Execute with sudo? [Confirm] [Cancel]", res["confirmation_prompt"])

    def test_environment_inspection(self):
        if not self.term.is_available():
            self.skipTest("Kali Linux WSL not available.")

        env = self.term.get_environment()
        self.assertTrue(env["success"])
        self.assertIn("Linux", env["stdout"])


class TestPluginDiscoveryAndRun(unittest.TestCase):
    def test_plugin_discovery(self):
        plugins_dir = BASE_DIR / "plugins"
        registry = discover_plugins(plugins_dir=plugins_dir, core_tool_names={"open_app", "web_search"})
        self.assertTrue(registry.has("jarvis_terminal"))
        decls = registry.get_tool_declarations()
        names = [d["name"] for d in decls]
        self.assertIn("jarvis_terminal", names)

    def test_plugin_run_entrypoint(self):
        player = DummyPlayer()
        # Test status
        res = jarvis_terminal.run({"action": "status"}, player=player)
        self.assertTrue("Terminal connection established" in res or "available" in res.lower())
        self.assertGreater(len(player.logs), 0)

        # Test safe execution
        res2 = jarvis_terminal.run({"command": "echo 'Hello from JARVIS Terminal'"}, player=player)
        self.assertTrue("Hello from JARVIS Terminal" in res2 or "Command completed" in res2)
        self.assertTrue(any("JARVIS TERMINAL" in c[0] for c in player.contents))


if __name__ == "__main__":
    unittest.main()
