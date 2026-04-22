"""Session management for Gemini Live API with unlimited duration support."""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages long-lived sessions with context compression and resumption."""

    def __init__(self):
        self.session_handle: Optional[str] = None
        self.is_interrupted = False
        self.connection_time_left: Optional[float] = None

    def update_resumption_handle(self, handle: str) -> None:
        """Store the latest session resumption handle."""
        if handle != self.session_handle:
            logger.info(f"Session resumption handle updated: {handle[:20]}...")
            self.session_handle = handle

    def mark_interrupted(self) -> None:
        """Mark that the current generation was interrupted by user."""
        if not self.is_interrupted:
            logger.info("User interrupted the model - stopping playback")
            self.is_interrupted = True

    def clear_interruption(self) -> None:
        """Clear interruption flag after handling."""
        self.is_interrupted = False

    def set_connection_warning(self, time_left_seconds: float) -> None:
        """Handle GoAway message indicating connection will terminate."""
        self.connection_time_left = time_left_seconds
        logger.warning(
            f"Connection will terminate in {time_left_seconds:.1f} seconds. "
            "Prepare for session resumption."
        )

    def should_reconnect(self) -> bool:
        """Check if we should initiate reconnection."""
        return self.connection_time_left is not None and self.connection_time_left < 5.0

    def get_resumption_handle(self) -> Optional[str]:
        """Get the current session handle for resumption."""
        return self.session_handle


class TranscriptLogger:
    """Logs audio transcriptions for monitoring and debugging."""

    def __init__(self, user_phone: str, language: str):
        self.user_phone = user_phone
        self.language = language
        self.input_transcript_buffer = []
        self.output_transcript_buffer = []

    def log_input_transcript(self, text: str) -> None:
        """Log user's speech transcription."""
        if text.strip():
            logger.info(f"[{self.user_phone}] USER ({self.language}): {text}")
            self.input_transcript_buffer.append(text)

    def log_output_transcript(self, text: str) -> None:
        """Log agent's speech transcription."""
        if text.strip():
            logger.info(f"[{self.user_phone}] AGENT ({self.language}): {text}")
            self.output_transcript_buffer.append(text)

    def get_full_input_transcript(self) -> str:
        """Get complete user transcript for session."""
        return " ".join(self.input_transcript_buffer)

    def get_full_output_transcript(self) -> str:
        """Get complete agent transcript for session."""
        return " ".join(self.output_transcript_buffer)

    def clear_buffers(self) -> None:
        """Clear transcript buffers (e.g., after session save)."""
        self.input_transcript_buffer.clear()
        self.output_transcript_buffer.clear()
