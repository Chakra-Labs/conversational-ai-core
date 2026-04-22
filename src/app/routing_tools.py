"""Tool-based routing logic for the Chakra Labs conversational assistant."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from livekit.agents import function_tool
from .database import db
from .instructions import get_turn_guidance_config

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {
    "general_inquiry",
    "product_or_service_details",
    "pricing_and_sales",
    "support_and_troubleshooting",
    "contact_information",
    "other",
}


def _normalize_text(value: str) -> str:
    return (value or "").strip().lower()


def _extract_user_id(user_context: Optional[Dict[str, Any]]) -> Optional[str]:
    if not user_context:
        return None
    user_id = user_context.get("user_id") or user_context.get("userId")
    return str(user_id) if user_id else None


def _is_onboarding_enabled(user_context: Optional[Dict[str, Any]]) -> bool:
    if not user_context:
        return False
    value = user_context.get("is_onboarding")
    if value is None:
        value = user_context.get("isOnboarding")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _build_business_context(profile: Dict[str, Any]) -> str:
    items = []
    
    agent_name = profile.get("agent_name") or profile.get("ai_agent_name")
    if agent_name:
        items.append(f"- Agent Name: {agent_name}")

    sys_prompt = profile.get("system_prompt")
    if sys_prompt:
        items.append(f"- System Prompt: {sys_prompt}")
        
    persona = profile.get("persona_description")
    if persona:
        items.append(f"- Agent Persona: {persona}")

    for key, label in (
        ("business_name", "Business name"),
        ("industry", "Industry"),
        ("business_size", "Business size"),
        ("use_case", "Use case"),
        ("primary_use_case", "Primary use case"),
        ("industry_vertical", "Industry vertical"),
        ("description", "Description"),
        ("website", "Website"),
    ):
        value = profile.get(key)
        if value:
            items.append(f"- {label}: {value}")

    target_audience = profile.get("target_audience")
    if isinstance(target_audience, list) and target_audience:
        items.append(f"- Target audience: {', '.join(str(v) for v in target_audience)}")

    if not items:
        return ""

    return "Business profile context:\n" + "\n".join(items)


def _match_option_values(question: Dict[str, Any], raw_values: List[str]) -> List[str]:
    options = question.get("options", [])
    if not options:
        return []

    matched: List[str] = []
    normalized_tokens = [_normalize_text(token) for token in raw_values if token and token.strip()]

    for token in normalized_tokens:
        for option in options:
            option_value = str(option.get("option_value", ""))
            option_label = str(option.get("option_label", ""))
            if token in {_normalize_text(option_value), _normalize_text(option_label)}:
                if option_value not in matched:
                    matched.append(option_value)
                break

    return matched

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
            category: Choose the best matching category using one of these English enum values: {general_inquiry, product_or_service_details, pricing_and_sales, support_and_troubleshooting, contact_information, other}.
            confidence: Confidence in [0,1]. Use lower if ambiguous.
        """
        normalized_category = category.lower().strip()
        if normalized_category not in VALID_CATEGORIES:
            # Fallback for invalid categories
            logger.warning(f"Invalid category '{category}', defaulting to general_inquiry")
            normalized_category = "general_inquiry"

        # First-turn forced policy
        classification_count = shared_state.get("classification_count", 0)
        if classification_count == 0 and normalized_category != "general_inquiry":
            logger.info("First turn: forcing category to 'general_inquiry' (was %s)", normalized_category)
            normalized_category = "general_inquiry"
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


def create_save_onboarding_answer_tool(
    shared_state: Dict[str, Any],
    user_context: Optional[Dict[str, Any]] = None,
):
    @function_tool(
        name="save_onboarding_answer",
        description="Save one onboarding answer to the database for the current user/session. Use when user provides an answer to an onboarding question.",
    )
    async def save_onboarding_answer(
        question_id: str,
        answer: str,
        selected_option_values: Optional[List[str]] = None,
    ) -> str:
        user_id = _extract_user_id(user_context)
        logger.info(
            "save_onboarding_answer called: user_id=%s question_id=%s answer_preview=%s selected_option_values=%s",
            user_id,
            question_id,
            (answer or "")[:120],
            selected_option_values,
        )
        if not user_id:
            logger.warning("save_onboarding_answer aborted: missing user_id in metadata")
            return "Cannot save onboarding answer: missing user_id in metadata."

        if not _is_onboarding_enabled(user_context):
            logger.warning("save_onboarding_answer aborted: onboarding mode disabled")
            return "Onboarding mode is disabled. Do not save onboarding answers in this session."

        session = await db.get_onboarding_session(user_id)
        if not session:
            logger.warning("save_onboarding_answer aborted: no active session for user_id=%s", user_id)
            return "No active onboarding session found for this user."

        questions = await db.get_onboarding_questions()
        question_map = {question["id"]: question for question in questions}
        question = question_map.get(question_id)
        if not question:
            logger.warning("save_onboarding_answer aborted: invalid question_id=%s", question_id)
            return f"Invalid question_id: {question_id}."

        question_type = question.get("question_type", "text")
        normalized_answer = (answer or "").strip()
        final_answer = normalized_answer

        if question_type == "select":
            candidates = selected_option_values or [normalized_answer]
            matched = _match_option_values(question, candidates)
            logger.info("Select answer mapping: candidates=%s matched=%s", candidates, matched)
            if not matched:
                return "Answer could not be mapped to a valid option. Ask user to pick one listed option."
            final_answer = matched[0]

        elif question_type == "multiselect":
            candidates = selected_option_values
            if not candidates:
                candidates = [segment.strip() for segment in normalized_answer.split(",")]
            matched = _match_option_values(question, candidates)
            logger.info("Multiselect answer mapping: candidates=%s matched=%s", candidates, matched)
            if not matched:
                return "Answer could not be mapped to valid options. Ask user to choose from listed options."
            final_answer = ",".join(matched)

        logger.info(
            "Prepared onboarding answer for upsert: question_id=%s question_type=%s final_answer=%s",
            question_id,
            question_type,
            final_answer,
        )

        success = await db.upsert_onboarding_answer(
            onboarding_session_id=str(session["id"]),
            question_id=question_id,
            answer=final_answer,
            answer_type=question_type,
        )

        if not success:
            logger.error("save_onboarding_answer failed during DB upsert for question_id=%s", question_id)
            return "Failed to save onboarding answer due to a database issue."

        shared_state["last_saved_onboarding_question_id"] = question_id
        logger.info("save_onboarding_answer succeeded for question_id=%s", question_id)
        return (
            f"Saved onboarding answer for {question_id}. "
            "Now call get_turn_guidance to retrieve the next question in sequence."
        )

    return save_onboarding_answer


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
            logger.warning("get_turn_guidance called without classification. Defaulting to general_inquiry.")
            stored_category = "general_inquiry"

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

        user_id = _extract_user_id(user_context)
        is_onboarding = _is_onboarding_enabled(user_context)
        logger.info(
            "get_turn_guidance called: category=%s user_id=%s is_onboarding=%s confidence=%.2f",
            stored_category,
            user_id,
            is_onboarding,
            confidence,
        )

        if is_onboarding and user_id:
            session = await db.get_onboarding_session(user_id)
            if not session:
                logger.warning("Onboarding mode enabled but no active session for user_id=%s", user_id)
                parts.append(
                    "Onboarding mode is enabled, but no active onboarding session was found for this user. "
                    "Ask the user to restart onboarding."
                )
                return "\n".join(parts)

            questions = await db.get_onboarding_questions()
            answers = await db.get_onboarding_answers(str(session["id"]))
            logger.info(
                "Onboarding guidance data fetched: session_id=%s questions=%d answers=%d",
                session["id"],
                len(questions),
                len(answers),
            )

            next_question = next((q for q in questions if q["id"] not in answers), None)

            if not next_question:
                logger.info("Onboarding complete for session_id=%s", session["id"])
                parts.append(
                    "Onboarding is complete: all questions are answered. "
                    "Thank the user and summarize completion status briefly."
                )
                return "\n".join(parts)

            progress_total = len(questions)
            progress_done = len(answers)

            parts.append("Onboarding mode: enabled")
            parts.append(f"Onboarding session id: {session['id']}")
            parts.append(f"Progress: {progress_done}/{progress_total}")
            parts.append("You must ask exactly the next unanswered onboarding question in order.")
            parts.append(
                f"Current question [{next_question['id']}] ({next_question['question_type']}): "
                f"{next_question['question_text']}"
            )
            logger.info(
                "Next onboarding question selected: session_id=%s question_id=%s question_type=%s progress=%d/%d",
                session["id"],
                next_question["id"],
                next_question["question_type"],
                progress_done,
                progress_total,
            )

            options = next_question.get("options") or []
            if options:
                option_lines = ", ".join(
                    f"{option['option_label']} ({option['option_value']})" for option in options
                )
                parts.append(f"Allowed options: {option_lines}")

            parts.append(
                "After the user answers, call save_onboarding_answer with the same question_id and parsed answer. "
                "For select/multiselect, store option_value(s), not free-form labels."
            )
            return "\n".join(parts)

        if not is_onboarding and user_id:
            profile = await db.get_business_profile(user_id)
            if profile:
                logger.info("Business profile found for user_id=%s; injecting into guidance", user_id)
                profile_context = _build_business_context(profile)
                if profile_context:
                    parts.append(profile_context)
            else:
                logger.info("No business profile found for user_id=%s; proceeding without profile context", user_id)

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
