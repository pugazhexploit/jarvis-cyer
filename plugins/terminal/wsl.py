"""
WSL2 Controller for Kali Linux.
Handles dynamic WSL and Kali Linux detection, process execution, and output capture.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Optional

# Output buffer limits (prevents runaway memory consumption)
MAX_OUTPUT_BYTES = 65536
CWD_MARKER = "__JARVIS_CWD_MARKER__"


class WSLController:
    """Manages WSL2 interaction and command dispatching into Kali Linux."""

    def __init__(self, kali_distribution: Optional[str] = None):
        self._kali_distro = kali_distribution
        self._wsl_path = shutil.which("wsl.exe") or "wsl.exe"

    def is_wsl_installed(self) -> bool:
        """Detect whether WSL is installed on the Windows host."""
        try:
            res = subprocess.run(
                [self._wsl_path, "--status"],
                capture_output=True,
                timeout=10,
            )
            # Check return code or output for WSL status
            output = self._decode_output(res.stdout + res.stderr)
            return res.returncode == 0 or "Distribution" in output or "Version" in output
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            return False

    def list_distributions(self) -> list[str]:
        """List all installed WSL distributions dynamically."""
        try:
            res = subprocess.run(
                [self._wsl_path, "--list", "--quiet"],
                capture_output=True,
                timeout=10,
            )
            raw = self._decode_output(res.stdout)
            distros = []
            for line in raw.splitlines():
                line = line.strip()
                if line and not line.startswith("Windows Subsystem"):
                    distros.append(line)
            return distros
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            return []

    def detect_kali_distribution(self, force_refresh: bool = False) -> Optional[str]:
        """Detect whether a Kali Linux distribution exists dynamically."""
        if self._kali_distro and not force_refresh:
            return self._kali_distro

        distros = self.list_distributions()
        for d in distros:
            if "kali" in d.lower():
                self._kali_distro = d
                return d

        # If quiet list didn't find it, check default or status
        self._kali_distro = None
        return None

    def get_distribution_name(self) -> Optional[str]:
        """Get the cached or detected Kali distribution name."""
        return self.detect_kali_distribution()

    def get_initial_home_dir(self, distro: Optional[str] = None) -> str:
        """Find the initial home working directory of the Kali user."""
        target_distro = distro or self.detect_kali_distribution()
        if not target_distro:
            return "/home/kali"
        try:
            res = subprocess.run(
                [self._wsl_path, "-d", target_distro, "--", "bash", "-c", "echo $HOME"],
                capture_output=True,
                timeout=10,
            )
            home = self._decode_output(res.stdout).strip()
            return home if home.startswith("/") else "/home/kali"
        except Exception:
            return "/home/kali"

    def execute_in_kali(
        self,
        command: str,
        cwd: str = "",
        timeout: int = 30,
    ) -> dict:
        """
        Execute a command inside the Kali Linux environment.
        Maintains working directory and captures stdout, stderr, exit code, and duration.
        """
        distro = self.detect_kali_distribution()
        if not distro:
            return {
                "success": False,
                "stdout": "",
                "stderr": (
                    "JARVIS Terminal unavailable.\n"
                    "Reason: Kali Linux distribution was not detected in WSL.\n"
                    "Please install/import a Kali WSL distribution first."
                ),
                "exit_code": 1,
                "duration": 0.0,
                "working_directory": cwd or "/home/kali",
                "error": "Kali distribution not found",
            }

        start_time = time.monotonic()
        target_cwd = cwd.strip() if cwd else "~"

        # Build bash wrapper script:
        # 1. cd to working directory (fall back to ~ if not found)
        # 2. execute command with eval
        # 3. capture command exit code
        # 4. print CWD_MARKER and new pwd
        # 5. exit with preserved exit code
        script = (
            f"cd {target_cwd} 2>/dev/null || cd ~; "
            f"eval {self._escape_bash_command(command)}; "
            f"__jarvis_ec=$?; "
            f"printf '\\n{CWD_MARKER}\\n'; "
            f"pwd; "
            f"exit $__jarvis_ec"
        )

        try:
            for attempt in range(2):
                res = subprocess.run(
                    [self._wsl_path, "-d", distro, "--", "bash", "-c", script],
                    capture_output=True,
                    timeout=timeout,
                )
                raw_stdout = self._decode_output(res.stdout)
                raw_stderr = self._decode_output(res.stderr)

                # Retry once if WSL service threw a transient wake-up error
                if res.returncode != 0 and "Wsl/Service" in (raw_stdout + raw_stderr) and attempt == 0:
                    time.sleep(0.5)
                    continue

                duration = round(time.monotonic() - start_time, 2)

                # Separate command output from the final working directory marker
                clean_stdout, new_cwd = self._parse_cwd_output(raw_stdout, current_cwd=cwd)

                # Apply buffer limits
                clean_stdout = self._truncate_output(clean_stdout)
                clean_stderr = self._truncate_output(raw_stderr)

                return {
                    "success": res.returncode == 0,
                    "stdout": clean_stdout,
                    "stderr": clean_stderr,
                    "exit_code": res.returncode,
                    "duration": duration,
                    "working_directory": new_cwd,
                    "error": None,
                }

        except subprocess.TimeoutExpired:
            duration = round(time.monotonic() - start_time, 2)
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Command timed out after {timeout} seconds.",
                "exit_code": 124,
                "duration": duration,
                "working_directory": cwd,
                "error": "TimeoutExpired",
            }
        except FileNotFoundError:
            return {
                "success": False,
                "stdout": "",
                "stderr": "wsl.exe was not found on the host system. Ensure WSL is installed and in PATH.",
                "exit_code": 127,
                "duration": 0.0,
                "working_directory": cwd,
                "error": "wsl_not_found",
            }
        except Exception as e:
            duration = round(time.monotonic() - start_time, 2)
            return {
                "success": False,
                "stdout": "",
                "stderr": f"WSL execution error: {e}",
                "exit_code": 1,
                "duration": duration,
                "working_directory": cwd,
                "error": str(e),
            }

    @staticmethod
    def _escape_bash_command(cmd: str) -> str:
        """Wrap command in single quotes with escaped internal quotes for bash eval."""
        escaped = cmd.replace("'", "'\"'\"'")
        return f"'{escaped}'"

    @staticmethod
    def _decode_output(raw_bytes: bytes) -> str:
        """Decode subprocess bytes safely handling UTF-16LE, UTF-8, and null bytes."""
        if not raw_bytes:
            return ""
        # Check if output is UTF-16LE (common in wsl.exe commands on Windows)
        if b"\x00" in raw_bytes:
            try:
                decoded = raw_bytes.decode("utf-16le")
                return decoded.replace("\x00", "").replace("\r\n", "\n")
            except UnicodeDecodeError:
                pass
        try:
            return raw_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n")
        except Exception:
            return raw_bytes.decode("latin-1", errors="replace").replace("\r\n", "\n")

    @staticmethod
    def _parse_cwd_output(raw_stdout: str, current_cwd: str = "") -> tuple[str, str]:
        """Extract the updated working directory from the marker in stdout."""
        if CWD_MARKER in raw_stdout:
            parts = raw_stdout.split(CWD_MARKER)
            clean_stdout = parts[0].rstrip("\r\n")
            remainder = parts[1].strip()
            # The next line after marker should be the pwd
            new_cwd = remainder.splitlines()[0].strip() if remainder else current_cwd
            return clean_stdout, new_cwd if new_cwd.startswith("/") else current_cwd
        return raw_stdout, current_cwd

    @staticmethod
    def _truncate_output(text: str, max_bytes: int = MAX_OUTPUT_BYTES) -> str:
        """Limit output size to prevent memory or display freeze."""
        encoded = text.encode("utf-8", errors="replace")
        if len(encoded) > max_bytes:
            truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
            return f"{truncated}\n\n[... Output truncated: exceeded {max_bytes // 1024} KB limit ...]"
        return text
