"""
Terminal Session model for JARVIS Terminal Plugin.
Maintains session state, working directory persistence, and execution history.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CommandRecord:
    timestamp: str
    command: str
    exit_code: int
    duration: float
    working_directory: str
    success: bool
    requires_sudo: bool = False


@dataclass
class TerminalSession:
    """Represents a stateful terminal session with Kali Linux in WSL2."""

    session_id: str = "JARVIS-KALI-001"
    distribution: str = "Kali Linux"
    working_directory: str = "/home/kali"
    environment: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    last_command: str = ""
    command_history: list[CommandRecord] = field(default_factory=list)
    status: str = "INITIALIZING"  # CONNECTED | DISCONNECTED | INITIALIZING

    def update_cwd(self, new_cwd: str) -> None:
        """Update working directory if valid."""
        if new_cwd and new_cwd.startswith("/"):
            self.working_directory = new_cwd

    def record_command(
        self,
        command: str,
        exit_code: int,
        duration: float,
        working_directory: str,
        success: bool,
        requires_sudo: bool = False,
    ) -> CommandRecord:
        """Record an executed command into session history."""
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        rec = CommandRecord(
            timestamp=ts,
            command=command,
            exit_code=exit_code,
            duration=duration,
            working_directory=working_directory,
            success=success,
            requires_sudo=requires_sudo,
        )
        self.command_history.append(rec)
        self.last_command = command
        self.update_cwd(working_directory)
        return rec

    def get_summary(self) -> str:
        """Return human-readable session summary."""
        return (
            f"Session:\n{self.session_id}\n\n"
            f"Distribution:\n{self.distribution}\n\n"
            f"Working Directory:\n{self.working_directory}\n\n"
            f"Status:\n{self.status}"
        )

    def to_dict(self) -> dict:
        """Convert session to structured dictionary."""
        return {
            "session_id": self.session_id,
            "distribution": self.distribution,
            "working_directory": self.working_directory,
            "status": self.status,
            "created_at": self.created_at,
            "last_command": self.last_command,
            "command_count": len(self.command_history),
            "environment": self.environment,
        }
