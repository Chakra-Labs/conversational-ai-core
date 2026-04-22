import logging
from typing import Iterable

from livekit.agents import JobContext
from livekit.agents.metrics import (
    AgentSessionUsage,
    InterruptionModelUsage,
    LLMModelUsage,
    STTModelUsage,
    TTSModelUsage,
)
from livekit.agents.voice import SessionUsageUpdatedEvent

logger = logging.getLogger(__name__)


class UsageCollector:
    def __init__(self):
        self._latest_usage: AgentSessionUsage | None = None

    def on_session_usage_updated(self, ev: SessionUsageUpdatedEvent) -> None:
        """Handle session usage updates for logging and analysis."""
        self._latest_usage = ev.usage
        totals = _summarize_llm_usage(ev.usage.model_usage)
        if totals is None:
            return

        # logger.info(
        #     "LLM usage update - input: %d (text: %d, audio: %d, image: %d, cached: %d), "
        #     "output: %d (text: %d, audio: %d)",
        #     totals["input_tokens"],
        #     totals["input_text_tokens"],
        #     totals["input_audio_tokens"],
        #     totals["input_image_tokens"],
        #     totals["input_cached_tokens"],
        #     totals["output_tokens"],
        #     totals["output_text_tokens"],
        #     totals["output_audio_tokens"],
        # )

    async def log_usage(self) -> None:
        """Log usage summary at session end."""
        if self._latest_usage is None:
            logger.info("No session usage data recorded.")
            return

        logger.info("\n====== Session Usage Summary ======")
        totals = _summarize_llm_usage(self._latest_usage.model_usage)
        if totals:
            logger.info(
                "Total LLM tokens: input=%d (text=%d, audio=%d, image=%d, cached=%d) output=%d",
                totals["input_tokens"],
                totals["input_text_tokens"],
                totals["input_audio_tokens"],
                totals["input_image_tokens"],
                totals["input_cached_tokens"],
                totals["output_tokens"],
            )

        for usage in self._latest_usage.model_usage:
            if isinstance(usage, (LLMModelUsage, TTSModelUsage, STTModelUsage, InterruptionModelUsage)):
                logger.info("%s", usage)


def setup_metrics_callbacks(session, ctx: JobContext):
    usage_collector = UsageCollector()
    session.on("session_usage_updated")(usage_collector.on_session_usage_updated)
    ctx.add_shutdown_callback(usage_collector.log_usage)


def _summarize_llm_usage(model_usage: Iterable[object]) -> dict[str, int] | None:
    totals = {
        "input_tokens": 0,
        "input_cached_tokens": 0,
        "input_text_tokens": 0,
        "input_audio_tokens": 0,
        "input_image_tokens": 0,
        "output_tokens": 0,
        "output_text_tokens": 0,
        "output_audio_tokens": 0,
    }

    has_llm = False
    for usage in model_usage:
        if not isinstance(usage, LLMModelUsage):
            continue
        has_llm = True
        totals["input_tokens"] += usage.input_tokens
        totals["input_cached_tokens"] += usage.input_cached_tokens
        totals["input_text_tokens"] += usage.input_text_tokens
        totals["input_audio_tokens"] += usage.input_audio_tokens
        totals["input_image_tokens"] += usage.input_image_tokens
        totals["output_tokens"] += usage.output_tokens
        totals["output_text_tokens"] += usage.output_text_tokens
        totals["output_audio_tokens"] += usage.output_audio_tokens

    return totals if has_llm else None
