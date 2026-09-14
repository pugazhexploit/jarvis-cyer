"""
JARVIS Terminal Plugin.
Enables command execution, environment inspection, and safety-gated security tools
inside Kali Linux running in WSL2.
"""

from __future__ import annotations

from plugins.terminal.terminal import JarvisTerminal

PLUGIN = {
    "name": "jarvis_terminal",
    "description": (
        "JARVIS Terminal: Executes Linux commands, inspects the environment, and runs authorized "
        "security tools inside Kali Linux on WSL2. "
        "Supported actions: 'execute' (runs bash/Linux command), 'status' (checks WSL/Kali availability and session state), "
        "'environment' (retrieves OS, kernel, distro, user, and cwd). "
        "Use this tool whenever the user asks to run Linux/bash commands (whoami, pwd, ls, ip, ps, curl, etc.), "
        "run Kali security tools (nmap, nikto, gobuster, sqlmap, etc.), check Kali status, or inspect the Linux environment. "
        "Destructive commands (rm, dd, etc.), elevated commands (sudo), and security tools require explicit user confirmation."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "The action: 'execute' (default, run command), 'status' (connection/session state), or 'environment' (OS, kernel, user, and cwd details)."
            },
            "command": {
                "type": "STRING",
                "description": "The Linux command to execute inside Kali (e.g. 'whoami', 'pwd', 'uname -a', 'ls -la', 'ip a', 'df -h'). Required for 'execute'."
            },
            "confirmed": {
                "type": "BOOLEAN",
                "description": "Must be set to true IF the user explicitly confirms executing an elevated (sudo), destructive (rm, etc.), or security tool command."
            },
            "target": {
                "type": "STRING",
                "description": "Optional authorized target IP or hostname for security tools in authorized local lab/CTF environments."
            },
            "timeout": {
                "type": "INTEGER",
                "description": "Execution timeout in seconds. Allowed: 10, 30, 60, 300. Defaults to 30."
            }
        },
        "required": []
    }
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """
    Plugin execution entrypoint invoked by JARVIS plugin registry.
    Dispatches to JarvisTerminal singleton, logs to UI, and returns spoken text.
    """
    terminal = JarvisTerminal.get_instance()
    if player and hasattr(player, "open_terminal"):
        try:
            player.open_terminal()
        except Exception:
            pass

    action = str(parameters.get("action", "")).lower().strip()
    command = str(parameters.get("command", "")).strip()
    confirmed = bool(parameters.get("confirmed", False) or parameters.get("confirm", False))
    target = str(parameters.get("target", "")).strip()
    timeout = parameters.get("timeout", 30)

    # 1. Action: Environment detection
    if action in ("environment", "env") or (not command and "environment" in action):
        if player and hasattr(player, "write_log"):
            player.write_log("JARVIS: Inspecting Kali WSL2 environment...")
        env_res = terminal.get_environment()
        if player and hasattr(player, "show_content") and env_res.get("summary"):
            player.show_content("JARVIS TERMINAL — ENVIRONMENT", env_res["summary"])

        if not env_res.get("success"):
            return (
                "Sir, the Kali Linux distribution was not detected in WSL. "
                "Please verify that Kali Linux is installed in WSL2."
            )

        data = env_res.get("environment_data", {})
        return (
            f"Terminal connection established. Environment: {data.get('distribution', 'Kali Linux')}, "
            f"Kernel {data.get('kernel', '')}, running on WSL2 as {data.get('user', 'kali')} "
            f"in {data.get('working_directory', '/home/kali')}."
        )

    # 2. Action: Session Status
    if action in ("status", "info") or (not command and action == "status"):
        status_info = terminal.get_status()
        if player and hasattr(player, "write_log"):
            player.write_log(f"JARVIS: Terminal status: {status_info['status']}.")
        if player and hasattr(player, "show_content"):
            player.show_content("JARVIS TERMINAL — STATUS", status_info["summary"])

        if not status_info.get("available"):
            return (
                "JARVIS Terminal unavailable. "
                "Reason: Kali Linux distribution was not detected in WSL. "
                "Please install or import a Kali WSL distribution first."
            )
        return (
            f"Terminal connection established. Distribution: {status_info['distribution']}, "
            f"Working Directory: {status_info['working_directory']}, Status: CONNECTED. "
            "Ready for your command, Sir."
        )

    # 3. Action: Execute command
    if not command:
        return (
            "Sir, no command was specified for the terminal. "
            "Please provide a Linux command or ask for terminal status or environment."
        )

    if player and hasattr(player, "write_log"):
        player.write_log(f"JARVIS: Executing inside Kali WSL: {command}")

    res = terminal.execute(
        command=command,
        timeout=timeout,
        confirmed=confirmed,
        target=target,
    )

    # Check if safety confirmation is required
    if res.get("requires_confirmation"):
        prompt_text = res.get("confirmation_prompt") or res.get("stderr")
        if player and hasattr(player, "show_content"):
            player.show_content("JARVIS TERMINAL — CONFIRMATION REQUIRED", prompt_text)
        if player and hasattr(player, "write_log"):
            player.write_log(f"JARVIS: Confirmation required for '{command}'.")
        return prompt_text

    # Format on-screen terminal display
    stdout_display = res.get("stdout", "")
    stderr_display = res.get("stderr", "")
    exit_code = res.get("exit_code", 0)
    duration = res.get("duration", 0.0)
    cwd = res.get("working_directory", "")

    terminal_display = (
        f"JARVIS TERMINAL\n\n"
        f"$ {command}\n\n"
        f"{stdout_display}\n"
    )
    if stderr_display:
        terminal_display += f"\nSTDERR:\n{stderr_display}\n"

    terminal_display += (
        f"\nExit Code: {exit_code}\n"
        f"Execution Time: {duration}s\n"
        f"Working Directory: {cwd}"
    )

    if player and hasattr(player, "show_content"):
        player.show_content("JARVIS TERMINAL", terminal_display)
    if player and hasattr(player, "write_log"):
        status_tag = "completed successfully" if exit_code == 0 else f"failed (exit {exit_code})"
        player.write_log(f"JARVIS: Command {status_tag} in {duration}s.")

    # Spoken summary for voice interface
    if exit_code == 0:
        lines = [line.strip() for line in stdout_display.splitlines() if line.strip()]
        if len(lines) == 1 and len(lines[0]) <= 80:
            return f"{lines[0]}"
        elif len(lines) > 0 and len(lines) <= 3 and len(stdout_display) <= 120:
            return f"Command completed successfully: {', '.join(lines)}"
        else:
            return f"Command completed successfully with exit code 0 in {duration}s. Full output displayed on screen."
    else:
        err_msg = stderr_display.strip().splitlines()[0] if stderr_display.strip() else f"exit code {exit_code}"
        return f"Command failed with exit code {exit_code}: {err_msg[:120]}"
