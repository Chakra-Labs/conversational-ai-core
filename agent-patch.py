"""Primary agent entrypoint wiring for LiveKit jobs."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, cli
from livekit.agents.llm.chat_context import ChatMessage
from livekit.plugins import google
from livekit.plugins.google.realtime import realtime_api as google_realtime_api

from app.assistant import Assistant
from app.instructions import get_entrypoint_instructions
from app.session_manager import SessionManager, TranscriptLogger
from app.user_context import get_user_details_from_metadata
from monitoring.metrics import setup_metrics_callbacks

agent_name = "conversational-ai-platform"

load_dotenv(".env.local")

logger = logging.getLogger("agent")

server = AgentServer()


def _is_gemini_31_live_model(model_name: str | None) -> bool:
    if not model_name:
        return False
    normalized = model_name.lower()
    return normalized.startswith("gemini-3.1-") and "live" in normalized


def apply_google_runtime_monkey_patch() -> None:
    session_cls = google_realtime_api.RealtimeSession
    if getattr(session_cls, "_govimithuru_gemini31_patch", False):
        return

    original_generate_reply = session_cls.generate_reply

    def patched_generate_reply(
        self: Any,
        *,
        instructions: Any = google_realtime_api.NOT_GIVEN,
    ) -> asyncio.Future[Any]:
        model_name = getattr(getattr(self, "_opts", None), "model", None)
        if not _is_gemini_31_live_model(model_name):
            return original_generate_reply(self, instructions=instructions)

        if self._pending_generation_fut and not self._pending_generation_fut.done():
            logger.warning(
                "generate_reply called while another generation is pending, cancelling previous."
            )
            self._pending_generation_fut.cancel("Superseded by new generate_reply call")

        fut: asyncio.Future[Any] = asyncio.Future()
        self._pending_generation_fut = fut

        if self._in_user_activity:
            self._send_client_event(
                google_realtime_api.types.LiveClientRealtimeInput(
                    activity_end=google_realtime_api.types.ActivityEnd(),
                )
            )
            self._in_user_activity = False

        prompt_text = "Please respond now."
        if google_realtime_api.is_given(instructions):
            raw = str(instructions).strip()
            if raw:
                prompt_text = f"{raw}\n\nRespond in a single concise turn."

        self._send_client_event(
            google_realtime_api.types.LiveClientRealtimeInput(text=prompt_text)
        )

        def _on_timeout() -> None:
            if not fut.done():
                fut.set_exception(
                    google_realtime_api.llm.RealtimeError(
                        "generate_reply timed out waiting for generation_created event."
                    )
                )
                if self._pending_generation_fut is fut:
                    self._pending_generation_fut = None

        timeout_handle = asyncio.get_event_loop().call_later(8.0, _on_timeout)
        fut.add_done_callback(lambda _: timeout_handle.cancel())
        return fut

    session_cls.generate_reply = patched_generate_reply
    setattr(session_cls, "_govimithuru_gemini31_patch", True)
    logger.info("Applied local Gemini 3.1 realtime monkey patch")


apply_google_runtime_monkey_patch()

async def handle_greet(data: rtc.RpcInvocationData) -> str:
    logger.info("Received greeting from %s: %s", data.caller_identity, data.payload)
    return f"Hello, {data.caller_identity}!"


def build_realtime_model() -> google.realtime.RealtimeModel:
    return google.realtime.RealtimeModel(
        model="gemini-3.1-flash-live-preview",
        voice="Puck",
        temperature=0.3,
    )

@server.rtc_session(agent_name=agent_name)
async def govimithuru_agent(ctx: agents.JobContext):
    # Logging setup
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    user_details = get_user_details_from_metadata(ctx)
    language = (user_details.get("language") if user_details else "sinhala").lower()
    user_phone = user_details.get("phone") if user_details else "unknown"
    mode = (user_details.get("mode") if user_details else "voice").lower()

    session_manager = SessionManager()
    transcript_logger = TranscriptLogger(user_phone=user_phone or "unknown", language=language)

    go_away_patched_session_ids: set[int] = set()

    logger.info("Initializing agent for user %s with language: %s, mode: %s", user_phone, language, mode)

    # Instantiate Assistant with user context (used for turn guidance tools)
    assistant = Assistant(language=language, user_context=user_details)

    realtime_model = build_realtime_model()
    logger.info(
        "Gemini monkey patch active: %s",
        getattr(google_realtime_api.RealtimeSession, "_govimithuru_gemini31_patch", False),
    )

    session = AgentSession(llm=realtime_model)

    def _handle_user_transcript(event: Any) -> None:
        transcript = getattr(event, "transcript", "")
        is_final = getattr(event, "is_final", False)
        if transcript and is_final:
            transcript_logger.log_input_transcript(transcript)

    def _handle_conversation_item(event: Any) -> None:
        item = getattr(event, "item", None)
        if isinstance(item, ChatMessage) and item.role == "assistant":
            text_content = item.text_content or ""
            if text_content:
                transcript_logger.log_output_transcript(text_content)
            if item.interrupted:
                session_manager.mark_interrupted()
            else:
                session_manager.clear_interruption()

    session.on("user_input_transcribed", _handle_user_transcript)
    session.on("conversation_item_added", _handle_conversation_item)

    def _patch_go_away_hook(rt_session: Any) -> None:
        original_handler = rt_session._handle_go_away  # type: ignore[attr-defined]

        def _wrapped(go_away: Any) -> None:
            time_left = getattr(go_away, "time_left", None)
            if time_left is not None:
                # Guard against string values like "50s" coming from the SDK
                parsed_time_left = None
                if isinstance(time_left, (int, float)):
                    parsed_time_left = float(time_left)
                elif isinstance(time_left, str):
                    cleaned = time_left.strip()
                    if cleaned.endswith("s"):
                        cleaned = cleaned[:-1]
                    try:
                        parsed_time_left = float(cleaned)
                    except ValueError:
                        logger.warning("Unexpected go_away time_left value: %s", time_left)

                if parsed_time_left is not None:
                    session_manager.set_connection_warning(parsed_time_left)
            original_handler(go_away)

        rt_session._handle_go_away = _wrapped  # type: ignore[attr-defined]

    async def _monitor_realtime_session() -> None:
        previous_handle = session_manager.get_resumption_handle()
        try:
            while True:
                sessions = list(getattr(realtime_model, "_sessions", []))  # type: ignore[attr-defined]
                rt_session = sessions[0] if sessions else None
                if rt_session is not None:
                    handle = rt_session.session_resumption_handle
                    if handle and handle != previous_handle:
                        session_manager.update_resumption_handle(handle)
                        previous_handle = handle

                    session_id = id(rt_session)
                    if session_id not in go_away_patched_session_ids:
                        _patch_go_away_hook(rt_session)
                        go_away_patched_session_ids.add(session_id)

                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return

    setup_metrics_callbacks(session, ctx)

    background_tasks: list[asyncio.Task[Any]] = []

    async def _send_initial_greeting() -> None:
        greeting_prompt = get_entrypoint_instructions(language)
        if not greeting_prompt:
            logger.warning("Skipping initial greeting: empty greeting prompt for language %s", language)
            return

        for attempt in range(1, 4):
            try:
                await asyncio.sleep(0.8 if attempt == 1 else 1.2)
                logger.info("Attempting initial greeting (attempt %s)", attempt)
                await asyncio.wait_for(
                    session.generate_reply(instructions=greeting_prompt),
                    timeout=12.0,
                )
                logger.info("Initial greeting triggered (attempt %s)", attempt)
                return
            except Exception as e:
                logger.warning("Greeting attempt %s failed: %s", attempt, e)

    try:
        await session.start(
            room=ctx.room,
            agent=assistant,
        )
        logger.info("session.start completed")

        await _send_initial_greeting()

        background_tasks.append(asyncio.create_task(_monitor_realtime_session()))

        await ctx.connect()
    finally:
        for task in background_tasks:
            task.cancel()
        for task in background_tasks:
            with suppress(asyncio.CancelledError):
                await task


if __name__ == "__main__":
    cli.run_app(server)
