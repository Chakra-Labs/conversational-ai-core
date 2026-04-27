"""Primary agent entrypoint wiring for LiveKit jobs."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress
from typing import Any

from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, RoomInputOptions, TurnHandlingOptions, cli
from livekit.agents.llm.chat_context import ChatMessage
from livekit.plugins import google, noise_cancellation, silero
from livekit.plugins.google.realtime import realtime_api as google_realtime_api
from google.genai import types as genai_types

from app.assistant import Assistant
from app.database import db
from app.instructions import get_entrypoint_instructions
from app.session_manager import SessionManager, TranscriptLogger
from app.user_context import get_user_details_from_metadata
from monitoring.metrics import setup_metrics_callbacks

agent_name = "conversational-ai"

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

def prewarm(proc: agents.JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

server.setup_fnc = prewarm

async def handle_greet(data: rtc.RpcInvocationData) -> str:
    logger.info("Received greeting from %s: %s", data.caller_identity, data.payload)
    return f"Hello, {data.caller_identity}!"


def _select_model(language: str) -> str:
    # Use Gemini Live native audio model for voice sessions
    return "gemini-3.1-flash-live-preview"

@server.rtc_session(agent_name=agent_name)
async def govimithuru_agent(ctx: agents.JobContext):
    # Logging setup
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    user_details = get_user_details_from_metadata(ctx)
    language = (user_details.get("language") if user_details else "english").lower()
    user_phone = user_details.get("phone") if user_details else "unknown"
    mode = (user_details.get("mode") if user_details else "voice").lower()

    session_manager = SessionManager()
    transcript_logger = TranscriptLogger(user_phone=user_phone or "unknown", language=language)

    go_away_patched_session_ids: set[int] = set()

    logger.info("Initializing agent for user %s with language: %s, mode: %s", user_phone, language, mode)

    await db.ensure_initialized()
    
    custom_instructions = None
    user_id = user_details.get("user_id") if user_details else None
    is_onboarding = user_details.get("is_onboarding") if user_details else False
    profile = None

    if user_id and not is_onboarding:
        profile = await db.get_business_profile(user_id)
        if profile:
            parts = []
            if profile.get("system_prompt"):
                parts.append(f"System Prompt: {profile['system_prompt']}")
            if profile.get("persona_description"):
                parts.append(f"Persona: {profile['persona_description']}")
            if parts:
                custom_instructions = "\n".join(parts)

    # Instantiate Assistant with user context
    assistant = Assistant(
        language=language, 
        user_context=user_details, 
        custom_instructions=custom_instructions,
        is_onboarding=is_onboarding
    )

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.error("GOOGLE_API_KEY is missing in environment variables!")
    else:
        logger.info("GOOGLE_API_KEY found (length: %d)", len(api_key))

    # Configure model based on mode
    if mode == "chat":
        # For chat mode, use Gemini 2.0 Flash with text-only modality
        realtime_model = google.beta.realtime.RealtimeModel(
            model="gemini-3-flash-preview",
            api_key=api_key,
            temperature=0.7,
            modalities=[genai_types.Modality.TEXT],
        )
    else:
        # For voice mode, use the native audio model
        realtime_model = google.beta.realtime.RealtimeModel(
            model=_select_model(language),
            api_key=api_key,
            voice="Leda",
            temperature=0.4,  # Low temperature for fastest response
            modalities=[genai_types.Modality.AUDIO],
            # thinking_config=genai_types.ThinkingConfig(
            #     thinking_budget=0,
            #     include_thoughts=False,
            # ),
            # realtime_input_config=genai_types.RealtimeInputConfig(
            #     automatic_activity_detection=genai_types.AutomaticActivityDetection(
            #         disabled=False,
            #         start_of_speech_sensitivity=genai_types.StartSensitivity.START_SENSITIVITY_HIGH,
            #         end_of_speech_sensitivity=genai_types.EndSensitivity.END_SENSITIVITY_HIGH,
            #         prefix_padding_ms=20,
            #         silence_duration_ms=120,
            #     )
            # ),
            # context_window_compression=genai_types.ContextWindowCompressionConfig(
            #     trigger_tokens=2000,
            #     sliding_window=genai_types.SlidingWindow(target_tokens=1000),
            # ),
            # session_resumption=genai_types.SessionResumptionConfig(
            #     handle=session_manager.get_resumption_handle(),
            #     transparent=True,
            # ),
        )

    session = AgentSession(
        turn_handling=TurnHandlingOptions(turn_detection="realtime_llm"),
        vad=ctx.proc.userdata["vad"],
        llm=realtime_model,
    )

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

    try:
        # Configure room options based on mode
        if mode == "chat":
            room_input_options = RoomInputOptions(
                audio_enabled=False,
                video_enabled=False,
            )
        else:
            room_input_options = RoomInputOptions(
                video_enabled=True,  # Enable video for plant image analysis (may add latency)
                noise_cancellation=noise_cancellation.BVC(),
            )

        await session.start(
            room=ctx.room,
            agent=assistant,
            room_input_options=room_input_options,
        )

        background_tasks.append(asyncio.create_task(_monitor_realtime_session()))

        if is_onboarding:
            from app.onboarding_instructions import get_onboarding_greeting_instructions
            greeting_instructions = get_onboarding_greeting_instructions(language)
            
            # Fetch the first question directly to prevent audio overlapping/interruption 
            # caused by a mid-greeting tool call.
            if user_id:
                db_session = await db.get_onboarding_session(user_id)
                if db_session:
                    questions = await db.get_onboarding_questions()
                    answers = await db.get_onboarding_answers(str(db_session["id"]))
                    next_q = next((q for q in questions if q["id"] not in answers), None)
                    if next_q:
                        greeting_instructions += (
                            f"\n\nFIRST QUESTION TO ASK: {next_q['question_text']}\n"
                            f"QUESTION_ID: {next_q['id']}\n"
                            f"QUESTION_TYPE: {next_q['question_type']}\n"
                            "INSTRUCTION: Greet the user warmly, explain the profile setup, and then ask the FIRST QUESTION TO ASK immediately. "
                            "Do NOT call `get_next_onboarding_question` now. Just ask the question. "
                            "When the user answers, call `save_onboarding_answer` with the QUESTION_ID provided above."
                        )
        else:
            greeting_instructions = get_entrypoint_instructions(language)
            if profile:
                biz_name = profile.get('business_name', 'the business')
                greeting_instructions += f"\nNote: You are representing {biz_name}. End of instructions."
        
        await session.generate_reply(instructions=greeting_instructions)
        await ctx.connect()
    finally:
        for task in background_tasks:
            task.cancel()
        for task in background_tasks:
            with suppress(asyncio.CancelledError):
                await task


if __name__ == "__main__":
    cli.run_app(server)
