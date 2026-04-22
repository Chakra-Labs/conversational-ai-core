"""Helpers for extracting user context from LiveKit job metadata."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from livekit import agents

logger = logging.getLogger(__name__)


def _preview_data(data: Dict[str, Any], max_len: int = 800) -> str:
    try:
        text = json.dumps(data, default=str)
    except Exception:
        text = str(data)
    if len(text) > max_len:
        return f"{text[:max_len]}...<truncated>"
    return text


def _parse_metadata(raw_metadata: Any) -> Optional[Dict[str, Any]]:
    if not raw_metadata:
        return None

    try:
        metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else raw_metadata
        if not isinstance(metadata, dict):
            return None
        return metadata
    except json.JSONDecodeError as exc:
        logger.error(f"Invalid room metadata JSON: {exc}")
        return None


def _extract_user_context(metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    context = metadata.get("userContext") or metadata.get("user_context")
    if isinstance(context, dict):
        return context
    return metadata


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def get_user_details_from_metadata(ctx: agents.JobContext) -> Optional[Dict[str, Any]]:
    """Return structured user details pulled from room metadata."""

    def _format_response(user_context: Dict[str, Any]) -> Dict[str, Any]:
        location = user_context.get("location") or {}
        selected_language = (
            user_context.get("selectedLanguage")
            or user_context.get("selected_language")
            or user_context.get("language")
        )

        user_id = user_context.get("userId") or user_context.get("user_id")

        return {
            "phone": user_context.get("phone"),
            "language": selected_language,
            "district": user_context.get("district"),
            "location_method": location.get("method"),
            "location_label": location.get("label"),
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "mode": user_context.get("mode", "voice"),
            "is_onboarding": _to_bool(user_context.get("isOnboarding") or user_context.get("is_onboarding")),
            "user_id": str(user_id) if user_id is not None else None,
        }

    metadata_sources = []

    if hasattr(ctx, "_info") and ctx._info and hasattr(ctx._info, "job"):
        job_info = ctx._info.job
        if hasattr(job_info, "room") and job_info.room:
            metadata_sources.append(("ctx._info.job.room", job_info.room.metadata))

    if hasattr(ctx, "room") and ctx.room and hasattr(ctx.room, "metadata"):
        metadata_sources.append(("ctx.room", ctx.room.metadata))

    for source, raw_metadata in metadata_sources:
        metadata = _parse_metadata(raw_metadata)
        if not metadata:
            continue

        logger.info("Room metadata parsed from %s: %s", source, _preview_data(metadata))

        user_context = _extract_user_context(metadata)
        if not user_context:
            continue

        formatted = _format_response(user_context)
        logger.info(
            "Extracted user context: phone=%s language=%s mode=%s is_onboarding=%s user_id=%s",
            formatted.get("phone"),
            formatted.get("language"),
            formatted.get("mode"),
            formatted.get("is_onboarding"),
            formatted.get("user_id"),
        )
        return formatted

    logger.warning("No user metadata available in job context.")
    return None
