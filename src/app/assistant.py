"""Assistant implementation and related helpers."""
from __future__ import annotations

import logging
from typing import Optional, Dict, Any

from livekit.agents import Agent

from .instructions import get_assistant_instructions
from .routing_tools import (
    create_intent_classifier_tool,
    create_turn_guidance_tool,
)

logger = logging.getLogger(__name__)


class Assistant(Agent):
    def __init__(
        self,
        language: str = "english",
        user_context: Optional[Dict[str, Any]] = None,
        custom_instructions: Optional[str] = None
    ) -> None:
        normalized_language = (language or "english").lower()
        instructions = custom_instructions or get_assistant_instructions(normalized_language)
        
        self.language = normalized_language
        self.shared_state = {}
        
        # Create routing tools with shared state
        routing_tools = [
            create_intent_classifier_tool(self.shared_state),
            create_turn_guidance_tool(
                self.shared_state, 
                normalized_language, 
                user_context
            )
        ]
        
        super().__init__(instructions=instructions, tools=routing_tools)
