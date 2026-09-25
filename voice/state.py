"""Explicit Thread-Safe Conversation State Machine for JARVIS.

States:
- IDLE: Waiting for wake-word ("Hey Jarvis") or sleeping in standby.
- LISTENING: Microphone active, streaming frames into Silero VAD.
- THINKING: Audio captured; Whisper transcribing and Gemini generating action/reply.
- SPEAKING: Edge TTS generating/playing audio with concurrent microphone VAD monitoring.
- INTERRUPTED: User speech detected while speaking; TTS and playback instantly aborted,
  transitioning immediately back to LISTENING with zero lost speech.
"""

from __future__ import annotations

from enum import Enum
import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger("jarvis.state")


class ConversationState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"


class StateManager:
    """Thread-safe conversation state and generation manager for JARVIS."""

    def __init__(self, on_change: Optional[Callable[[ConversationState], None]] = None) -> None:
        self._lock = threading.RLock()
        self._state: ConversationState = ConversationState.IDLE
        self._generation_id: int = 0
        self._on_change = on_change
        self._cancellation_events: dict[int, threading.Event] = {}

    @property
    def current(self) -> ConversationState:
        with self._lock:
            return self._state

    @property
    def generation_id(self) -> int:
        with self._lock:
            return self._generation_id

    def new_generation(self) -> tuple[int, threading.Event]:
        """Increments and returns a new generation ID and its cancellation event."""
        with self._lock:
            self._generation_id += 1
            gen_id = self._generation_id
            cancel_event = threading.Event()
            self._cancellation_events[gen_id] = cancel_event
            return gen_id, cancel_event

    def cancel_generation(self, generation_id: Optional[int] = None) -> None:
        """Signals cancellation for the specified generation or the active one."""
        with self._lock:
            gen_id = generation_id if generation_id is not None else self._generation_id
            event = self._cancellation_events.get(gen_id)
            if event:
                event.set()

    def is_generation_cancelled(self, generation_id: int) -> bool:
        with self._lock:
            if generation_id != self._generation_id:
                return True
            event = self._cancellation_events.get(generation_id)
            return bool(event and event.is_set())

    def transition_to(self, new_state: ConversationState) -> bool:
        """Transitions to a new state and invokes registered listeners."""
        with self._lock:
            old_state = self._state
            if old_state == new_state:
                return False
            self._state = new_state
            logger.info("State transition: %s -> %s (generation: %d)", old_state.value, new_state.value, self._generation_id)

        if self._on_change:
            try:
                self._on_change(new_state)
            except Exception as exc:
                logger.debug("State change callback error: %s", exc)

        return True
