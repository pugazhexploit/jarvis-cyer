"""
Mode Manager for JARVIS.
Provides a modular architecture for switching between different operational modes.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Any

@dataclass
class JarvisMode:
    id: str
    name: str
    icon: str
    description: str
    badge: str = ""
    is_active: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class ModeManager:
    """Singleton mode manager coordinating active JARVIS operational mode."""
    _instance: ModeManager | None = None

    def __new__(cls) -> ModeManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_modes()
        return cls._instance

    def _init_modes(self):
        self._current_mode_id = "assistant"
        self._listeners: list[Callable[[str, dict], None]] = []
        self._modes: dict[str, JarvisMode] = {
            "assistant": JarvisMode(
                id="assistant",
                name="Standard Assistant",
                icon="🤖",
                description="General-purpose AI assistant for computer control, system tasks, news, reminders, and queries.",
                badge="DEFAULT",
                is_active=True,
            ),
            "interview": JarvisMode(
                id="interview",
                name="Practice Real Interviews with an AI Interviewer",
                icon="🎯",
                description="Conduct realistic, adaptive mock job interviews with real-time feedback or post-interview evaluation.",
                badge="INTERVIEW",
                is_active=False,
            ),
        }

    def get_modes(self) -> list[JarvisMode]:
        return list(self._modes.values())

    def get_mode(self, mode_id: str) -> JarvisMode | None:
        return self._modes.get(mode_id)

    def get_current_mode(self) -> str:
        return self._current_mode_id

    def is_interview_active(self) -> bool:
        return self._current_mode_id == "interview"

    def set_mode(self, mode_id: str, **config) -> bool:
        if mode_id not in self._modes:
            return False
        
        old_mode = self._current_mode_id
        self._current_mode_id = mode_id
        
        for m in self._modes.values():
            m.is_active = (m.id == mode_id)

        print(f"[ModeManager] Switched mode: {old_mode} -> {mode_id}")
        
        # Notify all registered listeners
        for listener in self._listeners:
            try:
                listener(mode_id, config)
            except Exception as e:
                print(f"[ModeManager] Listener error: {e}")
                
        return True

    def register_listener(self, callback: Callable[[str, dict], None]):
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unregister_listener(self, callback: Callable[[str, dict], None]):
        if callback in self._listeners:
            self._listeners.remove(callback)


# Global singleton instance
mode_manager = ModeManager()
