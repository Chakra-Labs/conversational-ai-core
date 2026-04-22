"""Tool-based routing logic for the Chakra Labs conversational assistant."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from livekit.agents import function_tool
from .instructions import get_turn_guidance_config

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {
    "general_questions",
    "company_services_overview",
    "conversational_ai_platform_overview",
    "industry_solutions",
    "technical_deep_dive",
    "sales_and_contact",
}

def create_intent_classifier_tool(shared_state: Dict[str, Any]):
    @function_tool(
        name="classify_intent",
        description="Classify the user's latest message into one category (Always use English enum values). Use this before `get_turn_guidance`.",
    )
    async def classify_intent(
        user_message: str,
        category: str,
        confidence: float = 1.0
    ) -> str:
        """
        Args:
            user_message: User's latest message (transcript). Keep verbatim; Always show in english.
            category: Choose the best matching category using one of these English enum values: {general_questions, company_services_overview, conversational_ai_platform_overview, industry_solutions, technical_deep_dive, sales_and_contact}.
            confidence: Confidence in [0,1]. Use lower if ambiguous.
        """
        normalized_category = category.lower().strip()
        if normalized_category not in VALID_CATEGORIES:
            # Fallback for invalid categories
            logger.warning(f"Invalid category '{category}', defaulting to general_questions")
            normalized_category = "general_questions"

        # First-turn forced general_questions policy
        classification_count = shared_state.get("classification_count", 0)
        if classification_count == 0 and normalized_category != "general_questions":
            logger.info("First turn: forcing category to 'general_questions' (was %s)", normalized_category)
            normalized_category = "general_questions"
            confidence = min(confidence, 0.6)

        shared_state["intent_category"] = normalized_category
        shared_state["intent_confidence"] = confidence
        shared_state["last_user_message"] = user_message
        shared_state["classification_count"] = classification_count + 1

        logger.info(
            "Classified intent: category=%s confidence=%.2f count=%d",
            normalized_category,
            confidence,
            shared_state["classification_count"],
        )
        return f"Intent classified as {normalized_category}."

    return classify_intent


def create_turn_guidance_tool(
    shared_state: Dict[str, Any],
    language: str,
    user_context: Optional[Dict[str, Any]] = None
):
    @function_tool(
        name="get_turn_guidance",
        description="Return the best response instructions for this user turn, based on the classified intent.",
    )
    async def get_turn_guidance(
        user_message: str,
        confidence: float = 1.0
    ) -> str:
        """
        Args:
            user_message: User's latest message (transcript). Keep verbatim; Always show in English.
            confidence: Optional: confidence score in [0,1] from `classify_intent`.
        """
        # Enforce that classify_intent was called first
        stored_category = shared_state.get("intent_category")
        if not stored_category:
            # If for some reason classify_intent wasn't called (e.g. model hallucination), default to general_questions
             logger.warning("get_turn_guidance called without classification. Defaulting to general_questions.")
             stored_category = "general_questions"

        config = get_turn_guidance_config(language)
        
        # Build guidance parts
        parts = []
        
        # 1. Base guidance
        base = config.get("base", "Be concise.")
        parts.append(f"Guidance: {base}")

        # 2. User context (compact)
        if user_context:
            context_parts = []
            if user_context.get("name"):
                 context_parts.append(f"User: {user_context['name']}")
            
            if user_context.get("location_label") or user_context.get("district"):
                loc = user_context.get("location_label") or user_context.get("district")
                context_parts.append(f"Loc: {loc}")
                
            if context_parts:
                parts.append(" | ".join(context_parts))

        # 3. Category flow
        flows = config.get("flows", {})
        flow_text = flows.get(stored_category, "")
        if flow_text:
            parts.append(flow_text)
        else:
            # Fallback if flow missing
            parts.append(f"Category: {stored_category}. Please answer the user's question helpfully.")

        guidance_text = "\n".join(parts)
        return guidance_text

    return get_turn_guidance
