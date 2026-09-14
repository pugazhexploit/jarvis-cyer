"""
JARVIS Terminal Plugin package.
Provides modular terminal access to Kali Linux running in WSL2.
"""

from plugins.terminal.terminal import JarvisTerminal
from plugins.terminal.wsl import WSLController
from plugins.terminal.safety import SafetyLayer
from plugins.terminal.session import TerminalSession
from plugins.terminal.logger import AuditLogger

__all__ = [
    "JarvisTerminal",
    "WSLController",
    "SafetyLayer",
    "TerminalSession",
    "AuditLogger",
]
