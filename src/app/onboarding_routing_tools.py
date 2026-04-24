"""Onboarding-specific tool implementations for the Chakra Labs onboarding agent."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from livekit.agents import function_tool
from .database import db

logger = logging.getLogger(__name__)


def _normalize_text(value: str) -> str:
    return (value or "").strip().lower()


def _extract_user_id(user_context: Optional[Dict[str, Any]]) -> Optional[str]:
    if not user_context:
        return None
    user_id = user_context.get("user_id") or user_context.get("userId")
    return str(user_id) if user_id else None


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


def create_get_next_onboarding_question_tool(
    shared_state: Dict[str, Any],
    user_context: Optional[Dict[str, Any]] = None,
):
    @function_tool(
        name="get_next_onboarding_question",
        description=(
            "Fetch the next unanswered onboarding question for the current user. "
            "Call this at the start of the session and immediately after every successful `save_onboarding_answer` call. "
            "Returns the question text, type, allowed options (for select/multiselect), and progress info."
        ),
    )
    async def get_next_onboarding_question() -> str:
        user_id = _extract_user_id(user_context)
        logger.info("get_next_onboarding_question called: user_id=%s", user_id)

        if not user_id:
            logger.warning("get_next_onboarding_question aborted: missing user_id")
            return "Cannot retrieve onboarding questions: user_id is missing from session metadata."

        session = await db.get_onboarding_session(user_id)
        if not session:
            logger.warning(
                "get_next_onboarding_question: no active onboarding session for user_id=%s", user_id
            )
            return (
                "No active onboarding session found for your account. "
                "Please contact Chakra Labs support to start a new onboarding session."
            )

        questions = await db.get_onboarding_questions()
        answers = await db.get_onboarding_answers(str(session["id"]))

        logger.info(
            "Onboarding state: session_id=%s questions=%d answered=%d",
            session["id"],
            len(questions),
            len(answers),
        )

        next_question = next((q for q in questions if q["id"] not in answers), None)

        if not next_question:
            logger.info("All onboarding questions answered for session_id=%s", session["id"])
            return (
                "ONBOARDING_COMPLETE: All questions have been answered. "
                "Thank the user warmly and let them know their business profile setup is complete. "
                "They can now start using their personalised Chakra Labs AI."
            )

        progress_done = len(answers)
        progress_total = len(questions)

        lines = [
            f"NEXT_QUESTION",
            f"session_id: {session['id']}",
            f"question_id: {next_question['id']}",
            f"progress: {progress_done}/{progress_total}",
            f"question_type: {next_question['question_type']}",
            f"question_text: {next_question['question_text']}",
        ]

        options = next_question.get("options") or []
        if options:
            option_lines = " | ".join(
                f"{opt['option_label']} (value={opt['option_value']})" for opt in options
            )
            lines.append(f"allowed_options: {option_lines}")
        else:
            lines.append("allowed_options: free-text (no predefined options)")

        lines.append(
            "INSTRUCTION: Ask the user exactly this question now. "
            "After the user answers, call `save_onboarding_answer` with the question_id above and the parsed answer."
        )

        logger.info(
            "Returning next question: question_id=%s type=%s progress=%d/%d",
            next_question["id"],
            next_question["question_type"],
            progress_done,
            progress_total,
        )
        return "\n".join(lines)

    return get_next_onboarding_question


def create_onboarding_save_answer_tool(
    shared_state: Dict[str, Any],
    user_context: Optional[Dict[str, Any]] = None,
):
    @function_tool(
        name="save_onboarding_answer",
        description=(
            "Save the user's answer to an onboarding question. "
            "Always call this after the user answers a question, using the exact question_id returned "
            "by `get_next_onboarding_question`. For select/multiselect questions pass the option_value(s), "
            "not the label(s)."
        ),
    )
    async def save_onboarding_answer(
        question_id: str,
        answer: str,
        selected_option_values: Optional[List[str]] = None,
    ) -> str:
        """
        Args:
            question_id: Exact question_id returned by `get_next_onboarding_question`.
            answer: The user's free-text answer or the displayed option label(s) as spoken.
            selected_option_values: For select/multiselect questions supply the option_value(s) directly here
                                    (preferred over free-text matching).
        """
        user_id = _extract_user_id(user_context)
        logger.info(
            "save_onboarding_answer called: user_id=%s question_id=%s answer_preview=%s selected_option_values=%s",
            user_id,
            question_id,
            (answer or "")[:120],
            selected_option_values,
        )

        if not user_id:
            logger.warning("save_onboarding_answer aborted: missing user_id")
            return "Cannot save answer: user_id is missing from session metadata."

        session = await db.get_onboarding_session(user_id)
        if not session:
            logger.warning(
                "save_onboarding_answer aborted: no active session for user_id=%s", user_id
            )
            return "No active onboarding session found. Cannot save answer."

        questions = await db.get_onboarding_questions()
        question_map = {q["id"]: q for q in questions}
        question = question_map.get(question_id)

        if not question:
            logger.warning("save_onboarding_answer aborted: invalid question_id=%s", question_id)
            return (
                f"Invalid question_id '{question_id}'. "
                "Please use exactly the question_id returned by `get_next_onboarding_question`."
            )

        question_type = question.get("question_type", "text")
        normalized_answer = (answer or "").strip()
        final_answer = normalized_answer

        if question_type == "select":
            candidates = selected_option_values or [normalized_answer]
            matched = _match_option_values(question, candidates)
            logger.info("Select mapping: candidates=%s matched=%s", candidates, matched)
            if not matched:
                options_hint = ", ".join(
                    opt["option_label"] for opt in question.get("options", [])
                )
                return (
                    f"The answer could not be matched to a valid option. "
                    f"Please ask the user to choose one of: {options_hint}."
                )
            final_answer = matched[0]

        elif question_type == "multiselect":
            candidates = selected_option_values
            if not candidates:
                candidates = [seg.strip() for seg in normalized_answer.split(",")]
            matched = _match_option_values(question, candidates)
            logger.info("Multiselect mapping: candidates=%s matched=%s", candidates, matched)
            if not matched:
                options_hint = ", ".join(
                    opt["option_label"] for opt in question.get("options", [])
                )
                return (
                    f"The answer could not be matched to valid options. "
                    f"Please ask the user to choose one or more of: {options_hint}."
                )
            final_answer = ",".join(matched)

        logger.info(
            "Upserting answer: session_id=%s question_id=%s question_type=%s final_answer=%s",
            session["id"],
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
            logger.error(
                "save_onboarding_answer DB upsert failed: session_id=%s question_id=%s",
                session["id"],
                question_id,
            )
            return "Failed to save the answer due to a database error. Please try again."

        shared_state["last_saved_question_id"] = question_id
        logger.info(
            "Answer saved successfully: session_id=%s question_id=%s", session["id"], question_id
        )
        return (
            f"Answer saved for question '{question_id}'. "
            "Now call `get_next_onboarding_question` to retrieve the next question."
        )

    return save_onboarding_answer
