"""Assistant implementation and related helpers."""
from __future__ import annotations

import logging
from typing import Optional, Dict, Any

from livekit.agents import Agent

from .instructions import get_assistant_instructions, get_entrypoint_instructions
from .onboarding_instructions import get_onboarding_assistant_instructions
from .routing_tools import (
    create_intent_classifier_tool,
    create_save_onboarding_answer_tool,
    create_turn_guidance_tool,
)
from .onboarding_routing_tools import (
    create_get_next_onboarding_question_tool,
    create_onboarding_save_answer_tool,
)

logger = logging.getLogger(__name__)


class Assistant(Agent):
    def __init__(
        self,
        language: str = "english",
        user_context: Optional[Dict[str, Any]] = None,
        custom_instructions: Optional[str] = None,
        is_onboarding: bool = False
    ) -> None:
        self.language = (language or "english").lower()
        self.shared_state = {}
        
        if is_onboarding:
            # Onboarding mode: Use onboarding specific instructions and tools
            instructions = get_onboarding_assistant_instructions(self.language)
            routing_tools = [
                create_get_next_onboarding_question_tool(self.shared_state, user_context),
                create_onboarding_save_answer_tool(self.shared_state, user_context),
            ]
        else:
            # Business mode: Use standard instructions and tools
            base_instructions = get_assistant_instructions(self.language)
            if custom_instructions:
                instructions = f"{base_instructions}\n\n[BUSINESS SYSTEM PROMPT / PERSONA]\n{custom_instructions}"
            else:
                instructions = base_instructions
            
            routing_tools = [
                create_intent_classifier_tool(self.shared_state),
                create_save_onboarding_answer_tool(
                    self.shared_state,
                    user_context,
                ),
                create_turn_guidance_tool(
                    self.shared_state, 
                    self.language, 
                    user_context
                )
            ]
        
        super().__init__(instructions=instructions, tools=routing_tools)
