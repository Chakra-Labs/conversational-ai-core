"""Helpers for extracting user context from LiveKit job metadata."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from livekit import agents

logger = logging.getLogger(__name__)


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
    return context if isinstance(context, dict) else None


def get_user_details_from_metadata(ctx: agents.JobContext) -> Optional[Dict[str, Any]]:
    """Return structured user details pulled from room metadata."""

    def _format_response(user_context: Dict[str, Any]) -> Dict[str, Any]:
        location = user_context.get("location") or {}
        return {
            "phone": user_context.get("phone"),
            "language": user_context.get("selectedLanguage"),
            "district": user_context.get("district"),
            "location_method": location.get("method"),
            "location_label": location.get("label"),
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "mode": user_context.get("mode", "voice"),
        }

    metadata_sources = []

    if hasattr(ctx, "_info") and ctx._info and hasattr(ctx._info, "job"):
        job_info = ctx._info.job
        if hasattr(job_info, "room") and job_info.room:
            metadata_sources.append(("ctx._info.job.room", job_info.room.metadata))

    if hasattr(ctx, "room") and ctx.room and hasattr(ctx.room, "metadata"):
        metadata_sources.append(("ctx.room", ctx.room.metadata))

    for source, raw_metadata in metadata_sources:
        user_context = _parse_metadata(raw_metadata)
        if not user_context:
            continue

        phone = user_context.get("phone")
        logger.info(f"Found user details in metadata for phone: {phone}")
        return _format_response(user_context)

    logger.warning("No user metadata available in job context.")
    return None
