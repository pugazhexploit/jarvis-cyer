"""
Safety and Validation Layer for JARVIS Terminal Plugin.
Enforces privilege escalation checks, destructive command guardrails,
security tool authorization, and secret redaction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ValidationResult:
    is_allowed: bool
    requires_confirmation: bool
    category: str  # "safe" | "sudo" | "destructive" | "security_tool" | "blocked"
    reason: str = ""
    confirmation_prompt: str = ""


class SafetyLayer:
    """Validates commands before WSL execution and redacts sensitive data."""

    # Commands that destroy or significantly alter system state
    DESTRUCTIVE_PATTERNS = [
        r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*\s+)?(\/|\*|~\/|[a-zA-Z0-9_\-\.\/]+)",
        r"\brmdir\b",
        r"\bdd\s+if=",
        r"\bmkfs(\.[a-zA-Z0-9]+)?\b",
        r"\bfdisk\b",
        r"\bparted\b",
        r"\bsfdisk\b",
        r"\bmkswap\b",
        r"\bshred\b",
        r"\bwipefs\b",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bpoweroff\b",
        r"\bhalt\b",
        r"\binit\s+[06]\b",
        r"\bsystemctl\s+(stop|restart|disable|mask|isolate)\b",
        r"\bchmod\b(\s+-R)?",
        r"\bchown\b(\s+-R)?",
        r"\biptables\s+-[FDX]",
        r"\bufw\s+(disable|reset)\b",
    ]

    # Security assessment tools requiring explicit confirmation & target acknowledgment
    SECURITY_TOOLS = [
        "nmap",
        "nikto",
        "gobuster",
        "sqlmap",
        "whatweb",
        "dig",
        "whois",
        "hydra",
        "metasploit",
        "msfconsole",
        "aircrack-ng",
        "wireshark",
        "tcpdump",
        "masscan",
        "wpscan",
        "dirb",
        "dirbuster",
        "ettercap",
        "bettercap",
        "john",
        "hashcat",
        "sublist3r",
        "amass",
    ]

    # Blocked commands attempting Windows host traversal or dangerous shell loops
    BLOCKED_PATTERNS = [
        r"\bpowershell(\.exe)?\b",
        r"\bcmd(\.exe)?\b",
        r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",  # Fork bomb
        r"/dev/zero\s+.*>\s+/dev/sd[a-z]",
        r"/dev/urandom\s+.*>\s+/dev/sd[a-z]",
    ]

    # Patterns for redacting sensitive secrets
    REDACTION_PATTERNS = [
        (re.compile(r"-----BEGIN [A-Z0-9\s]+PRIVATE KEY-----.*?-----END [A-Z0-9\s]+PRIVATE KEY-----", re.DOTALL), "[REDACTED_PRIVATE_KEY]"),
        (re.compile(r"AIza[0-9A-Za-z-_]{35}"), "[REDACTED_GEMINI_KEY]"),
        (re.compile(r"ghp_[A-Za-z0-9]{36}"), "[REDACTED_GITHUB_TOKEN]"),
        (re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
        (re.compile(r"(-p|--password|password=)[\s'\"]*([^\s'\"]+)", re.IGNORECASE), r"\1 [REDACTED_PASSWORD]"),
    ]

    ALLOWED_TIMEOUTS = {10, 30, 60, 300}

    def __init__(self):
        self._compiled_destructive = [re.compile(p, re.IGNORECASE) for p in self.DESTRUCTIVE_PATTERNS]
        self._compiled_blocked = [re.compile(p, re.IGNORECASE) for p in self.BLOCKED_PATTERNS]
        sec_pattern = r"\b(" + "|".join(re.escape(t) for t in self.SECURITY_TOOLS) + r")\b"
        self._compiled_security = re.compile(sec_pattern, re.IGNORECASE)
        self._sudo_pattern = re.compile(r"(^|[;&|]\s*)sudo\b", re.IGNORECASE)

    def validate_command(
        self,
        command: str,
        confirmed: bool = False,
        authorized_target: Optional[str] = None,
    ) -> ValidationResult:
        """
        Validate whether a command is safe to execute or requires user confirmation.
        """
        cleaned = command.strip()
        if not cleaned:
            return ValidationResult(
                is_allowed=False,
                requires_confirmation=False,
                category="blocked",
                reason="Empty command provided.",
            )

        # 1. Check for outright blocked patterns (fork bombs, Windows cmd/powershell triggers)
        for pattern in self._compiled_blocked:
            if pattern.search(cleaned):
                return ValidationResult(
                    is_allowed=False,
                    requires_confirmation=False,
                    category="blocked",
                    reason="Command contains a prohibited execution pattern or host escaping attempt.",
                )

        # 2. Check for sudo privilege escalation
        if self._sudo_pattern.search(cleaned):
            if not confirmed:
                prompt = (
                    "This command requires elevated privileges.\n\n"
                    f"Command:\n{cleaned}\n\n"
                    "Execute with sudo? [Confirm] [Cancel]"
                )
                return ValidationResult(
                    is_allowed=False,
                    requires_confirmation=True,
                    category="sudo",
                    reason="Command requires elevated privileges (sudo).",
                    confirmation_prompt=prompt,
                )

        # 3. Check for destructive operations
        for pattern in self._compiled_destructive:
            if pattern.search(cleaned):
                if not confirmed:
                    prompt = (
                        "Destructive command detected.\n\n"
                        f"Command:\n{cleaned}\n\n"
                        "This command can modify or destroy data or change system state.\n"
                        "Execute anyway? [Confirm] [Cancel]"
                    )
                    return ValidationResult(
                        is_allowed=False,
                        requires_confirmation=True,
                        category="destructive",
                        reason="Destructive command requiring explicit user confirmation.",
                        confirmation_prompt=prompt,
                    )

        # 4. Check for security tools
        sec_match = self._compiled_security.search(cleaned)
        if sec_match:
            tool_name = sec_match.group(1).lower()
            if not confirmed:
                target_note = (
                    f"Target acknowledged: '{authorized_target}'.\n"
                    if authorized_target
                    else "Target: Ensure target is an authorized local lab or personal testing environment.\n"
                )
                prompt = (
                    f"Security tool execution detected: '{tool_name}'.\n\n"
                    f"Command:\n{cleaned}\n\n"
                    f"{target_note}"
                    "JARVIS is configured for authorized local labs, CTFs, and personal systems only.\n"
                    "Confirm execution? [Confirm] [Cancel]"
                )
                return ValidationResult(
                    is_allowed=False,
                    requires_confirmation=True,
                    category="security_tool",
                    reason=f"Execution of security tool '{tool_name}' requires user confirmation.",
                    confirmation_prompt=prompt,
                )

        # Safe command or confirmed elevated/destructive command
        return ValidationResult(
            is_allowed=True,
            requires_confirmation=False,
            category="safe" if not confirmed else "confirmed",
            reason="Command authorized for execution.",
        )

    def normalize_timeout(self, requested_timeout: Optional[int]) -> int:
        """Clamp or validate timeout to allowed limits (default: 30s)."""
        if requested_timeout is None:
            return 30
        try:
            val = int(requested_timeout)
            if val in self.ALLOWED_TIMEOUTS:
                return val
            # Pick nearest allowed limit
            if val <= 15:
                return 10
            if val <= 45:
                return 30
            if val <= 180:
                return 60
            return 300
        except (ValueError, TypeError):
            return 30

    def sanitize_output(self, text: str) -> str:
        """Redact sensitive keys, passwords, and tokens from command output or logs."""
        if not text:
            return ""
        sanitized = text
        for pattern, replacement in self.REDACTION_PATTERNS:
            sanitized = pattern.sub(replacement, sanitized)
        return sanitized

    def sanitize_environment_output(self, text: str) -> str:
        """Ensure no Windows host environment paths or credentials leak into outputs."""
        sanitized = self.sanitize_output(text)
        # Redact Windows username path if present (e.g. C:\Users\<name>)
        sanitized = re.sub(
            r"([a-zA-Z]:[\\/](?:Users|Documents and Settings)[\\/])([a-zA-Z0-9_\-\.]+)",
            r"\1[REDACTED_USER]",
            sanitized,
        )
        return sanitized
