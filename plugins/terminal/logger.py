"""
Audit Logger for JARVIS Terminal Plugin.
Stores terminal history separately from normal JARVIS chat logs with secret redaction.
"""

from __future__ import annotations

import datetime
import threading
from pathlib import Path
from typing import Optional

from plugins.terminal.safety import SafetyLayer


class AuditLogger:
    """Thread-safe persistent audit logger for terminal commands."""

    def __init__(self, log_path: Optional[Path] = None):
        if log_path is None:
            # Place in project logs/ directory
            base_dir = Path(__file__).resolve().parent.parent.parent
            log_dir = base_dir / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            self.log_file = log_dir / "terminal_audit.log"
        else:
            self.log_file = Path(log_path)
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._safety = SafetyLayer()

    def log_command(
        self,
        command: str,
        exit_code: int = 0,
        duration: float = 0.0,
        cwd: str = "",
        elevated: bool = False,
        status: str = "COMPLETED",
    ) -> None:
        """Append an audited command entry to the persistent log file."""
        now = datetime.datetime.now()
        time_str = now.strftime("%H:%M:%S")
        date_str = now.strftime("%Y-%m-%d")

        # Redact secrets from command string before writing to disk
        safe_cmd = self._safety.sanitize_output(command).strip()

        # Detailed record
        tag = "[SUDO]" if elevated else "[USER]"
        line = f"{date_str} {time_str} {tag} (exit={exit_code}, {duration:.2f}s, cwd={cwd}) {safe_cmd}\n"

        with self._lock:
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception as e:
                print(f"[TerminalLogger] Failed to write audit log: {e}")

    def get_history_lines(self, limit: int = 20) -> list[str]:
        """Return the most recent command history formatted as: HH:MM:SS <command>."""
        if not self.log_file.exists():
            return []

        lines = []
        with self._lock:
            try:
                with open(self.log_file, "r", encoding="utf-8") as f:
                    raw_lines = f.readlines()
                for line in reversed(raw_lines[-limit:]):
                    parts = line.strip().split(" ", 3)
                    if len(parts) >= 4:
                        # Extract timestamp and command
                        time_part = parts[1]
                        cmd_part = parts[3]
                        # Remove prefix info if present
                        if ")" in cmd_part:
                            cmd_part = cmd_part.split(")", 1)[1].strip()
                        lines.append(f"{time_part}  {cmd_part}")
                    else:
                        lines.append(line.strip())
                lines.reverse()
            except Exception:
                return []
        return lines
