"""
Core JarvisTerminal implementation.
Provides modular terminal capabilities interacting with Kali Linux in WSL2.
"""

from __future__ import annotations

import time
from typing import Optional

from plugins.terminal.wsl import WSLController
from plugins.terminal.safety import SafetyLayer, ValidationResult
from plugins.terminal.session import TerminalSession
from plugins.terminal.logger import AuditLogger


class JarvisTerminal:
    """
    Main interface for the JARVIS Terminal.
    Controls execution, environment detection, and session state inside Kali Linux on WSL2.
    """

    _instance: Optional[JarvisTerminal] = None

    @classmethod
    def get_instance(cls) -> JarvisTerminal:
        """Singleton accessor for persistent session state across tool calls."""
        if cls._instance is None:
            cls._instance = JarvisTerminal()
        return cls._instance

    def __init__(self, kali_distribution: Optional[str] = None):
        self.wsl = WSLController(kali_distribution=kali_distribution)
        self.safety = SafetyLayer()
        self.logger = AuditLogger()
        self.session = TerminalSession()
        self._initialize_session()

    def _initialize_session(self) -> None:
        """Discover distribution and initial working directory."""
        distro = self.wsl.detect_kali_distribution()
        if distro:
            self.session.distribution = distro
            initial_home = self.wsl.get_initial_home_dir(distro)
            self.session.working_directory = initial_home
            self.session.status = "CONNECTED"
        else:
            self.session.status = "UNAVAILABLE"

    def is_available(self) -> bool:
        """Check whether WSL and Kali Linux are ready for execution."""
        return self.wsl.is_wsl_installed() and bool(self.wsl.detect_kali_distribution())

    def get_status(self) -> dict:
        """Return structured status of the WSL Kali terminal session."""
        distro = self.wsl.detect_kali_distribution()
        available = bool(distro)
        self.session.status = "CONNECTED" if available else "UNAVAILABLE"
        if distro:
            self.session.distribution = distro

        summary_text = (
            f"Session:\n{self.session.session_id}\n\n"
            f"Distribution:\n{self.session.distribution}\n\n"
            f"Working Directory:\n{self.session.working_directory}\n\n"
            f"Status:\n{self.session.status}"
        )

        return {
            "success": available,
            "available": available,
            "session_id": self.session.session_id,
            "distribution": self.session.distribution,
            "working_directory": self.session.working_directory,
            "status": self.session.status,
            "created_at": self.session.created_at,
            "command_count": len(self.session.command_history),
            "summary": summary_text,
            "environment": f"{self.session.distribution} / WSL2",
        }

    def get_environment(self) -> dict:
        """
        Inspect Kali Linux environment details:
        OS, Distribution, Kernel, Architecture, WSL version, User, Working Directory.
        """
        if not self.is_available():
            return {
                "success": False,
                "error": "Kali Linux distribution not detected in WSL.",
                "summary": "JARVIS Terminal unavailable. Reason: Kali Linux distribution was not detected in WSL.",
            }

        # Query Kali for environment details in a single quick bash execution
        probe_cmd = (
            "echo 'OS:' $(uname -s);"
            "echo 'DISTRO:' $(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '\"' || echo 'Kali GNU/Linux');"
            "echo 'KERNEL:' $(uname -r);"
            "echo 'ARCH:' $(uname -m);"
            "echo 'USER:' $(whoami);"
            "echo 'HOME:' $HOME"
        )
        res = self.wsl.execute_in_kali(probe_cmd, cwd=self.session.working_directory, timeout=10)

        env_data = {
            "os": "Linux",
            "distribution": "Kali GNU/Linux",
            "kernel": "unknown",
            "architecture": "x86_64",
            "wsl": "WSL2",
            "user": "kali",
            "working_directory": self.session.working_directory,
        }

        if res["success"]:
            for line in res["stdout"].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip().lower()
                    v = v.strip()
                    if k == "os":
                        env_data["os"] = v
                    elif k == "distro":
                        env_data["distribution"] = v
                    elif k == "kernel":
                        env_data["kernel"] = v
                    elif k == "arch":
                        env_data["architecture"] = v
                    elif k == "user":
                        env_data["user"] = v
                    elif k == "home" and self.session.working_directory in ("~", ""):
                        self.session.working_directory = v

        env_data["working_directory"] = self.session.working_directory
        self.session.environment = env_data

        formatted_summary = (
            f"OS: {env_data['os']}\n"
            f"Distribution: {env_data['distribution']}\n"
            f"Kernel: {env_data['kernel']}\n"
            f"Architecture: {env_data['architecture']}\n"
            f"WSL: {env_data['wsl']}\n"
            f"User: {env_data['user']}\n"
            f"Working Directory: {env_data['working_directory']}"
        )

        return {
            "success": True,
            "environment_data": env_data,
            "summary": formatted_summary,
            "environment": f"{env_data['distribution']} / {env_data['wsl']}",
            "stdout": formatted_summary,
            "stderr": "",
            "exit_code": 0,
        }

    def execute(
        self,
        command: str,
        timeout: int = 30,
        confirmed: bool = False,
        target: str = "",
    ) -> dict:
        """
        Execute a Linux command inside Kali Linux through the safety layer.
        Returns structured results:
        {
            "success": bool,
            "stdout": str,
            "stderr": str,
            "exit_code": int,
            "command": str,
            "environment": str,
            "duration": float,
            "working_directory": str
        }
        """
        if not self.is_available():
            distro = self.wsl.detect_kali_distribution(force_refresh=True)
            if not distro:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": (
                        "JARVIS Terminal unavailable.\n\n"
                        "Reason:\n"
                        "Kali Linux distribution was not detected in WSL.\n"
                        "Please install/import a Kali WSL distribution first."
                    ),
                    "exit_code": 1,
                    "command": command,
                    "environment": "WSL2 (Kali not found)",
                    "duration": 0.0,
                    "working_directory": self.session.working_directory,
                    "requires_confirmation": False,
                }

        # 1. Safety & validation check
        validation: ValidationResult = self.safety.validate_command(
            command=command,
            confirmed=confirmed,
            authorized_target=target,
        )

        if not validation.is_allowed:
            if validation.requires_confirmation:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": validation.confirmation_prompt,
                    "exit_code": -1,
                    "command": command,
                    "environment": f"{self.session.distribution} / WSL2",
                    "duration": 0.0,
                    "working_directory": self.session.working_directory,
                    "requires_confirmation": True,
                    "confirmation_prompt": validation.confirmation_prompt,
                    "category": validation.category,
                }
            else:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"Execution blocked: {validation.reason}",
                    "exit_code": 126,
                    "command": command,
                    "environment": f"{self.session.distribution} / WSL2",
                    "duration": 0.0,
                    "working_directory": self.session.working_directory,
                    "requires_confirmation": False,
                }

        # 2. Execution in WSL Kali
        safe_timeout = self.safety.normalize_timeout(timeout)
        exec_res = self.wsl.execute_in_kali(
            command=command,
            cwd=self.session.working_directory,
            timeout=safe_timeout,
        )

        # 3. Update session CWD and record command history
        new_cwd = exec_res.get("working_directory", self.session.working_directory)
        self.session.record_command(
            command=command,
            exit_code=exec_res["exit_code"],
            duration=exec_res["duration"],
            working_directory=new_cwd,
            success=exec_res["success"],
            requires_sudo="sudo" in command.lower(),
        )

        # 4. Audit logging
        self.logger.log_command(
            command=command,
            exit_code=exec_res["exit_code"],
            duration=exec_res["duration"],
            cwd=new_cwd,
            elevated="sudo" in command.lower(),
            status="SUCCESS" if exec_res["success"] else "FAILED",
        )

        # 5. Sanitize outputs (redact secrets / credentials)
        clean_stdout = self.safety.sanitize_output(exec_res["stdout"])
        clean_stderr = self.safety.sanitize_output(exec_res["stderr"])

        return {
            "success": exec_res["success"],
            "stdout": clean_stdout,
            "stderr": clean_stderr,
            "exit_code": exec_res["exit_code"],
            "command": command,
            "environment": f"{self.session.distribution} / WSL2",
            "duration": exec_res["duration"],
            "working_directory": new_cwd,
            "requires_confirmation": False,
        }
