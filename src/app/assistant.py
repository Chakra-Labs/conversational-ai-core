"""Assistant implementation and related helpers."""
from __future__ import annotations

import logging
from typing import Optional, Dict, Any

from livekit.agents import Agent

from .instructions import get_assistant_instructions
from .routing_tools import (
    create_intent_classifier_tool,
    create_save_onboarding_answer_tool,
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
        base_instructions = get_assistant_instructions(normalized_language)
        if custom_instructions:
            instructions = f"{base_instructions}\n\n[BUSINESS SYSTEM PROMPT / PERSONA]\n{custom_instructions}"
        else:
            instructions = base_instructions
        
        self.language = normalized_language
        self.shared_state = {}
        
        # Create routing tools with shared state
        routing_tools = [
            create_intent_classifier_tool(self.shared_state),
            create_save_onboarding_answer_tool(
                self.shared_state,
                user_context,
            ),
            create_turn_guidance_tool(
                self.shared_state, 
                normalized_language, 
                user_context
            )
        ]
        
        super().__init__(instructions=instructions, tools=routing_tools)
