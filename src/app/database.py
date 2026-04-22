"""Async PostgreSQL helpers for onboarding and business-profile context."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)


def _preview_record(data: Dict[str, Any], max_len: int = 700) -> str:
    try:
        safe_data = dict(data)
        if "answer" in safe_data and isinstance(safe_data["answer"], str):
            safe_data["answer"] = safe_data["answer"][:120]
        text = str(safe_data)
    except Exception:
        text = str(data)
    if len(text) > max_len:
        return f"{text[:max_len]}...<truncated>"
    return text


class Database:
    def __init__(self) -> None:
        self.dsn = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")
        if not self.dsn:
            user = os.getenv("DB_USER")
            password = os.getenv("DB_PASSWORD")
            host = os.getenv("DB_HOST")
            port = os.getenv("DB_PORT") or "5432"
            db_name = os.getenv("DB_NAME")

            if user and password and host and db_name:
                self.dsn = f"postgresql://{user}:{password}@{host}:{port}/{db_name}"

        self._pools: Dict[asyncio.AbstractEventLoop, asyncpg.Pool] = {}

    async def ensure_initialized(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.error("No running event loop available for DB pool initialization")
            return

        if loop in self._pools and not getattr(self._pools[loop], "_closed", False):
            return

        if not self.dsn:
            logger.error("Missing DB DSN. Set POSTGRES_URL/DATABASE_URL or DB_* env variables.")
            return

        try:
            self._pools[loop] = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=1,
                max_size=10,
                command_timeout=60,
            )
            logger.info("Initialized DB pool for loop %s", id(loop))
        except Exception as exc:
            logger.error("Failed to initialize DB pool: %s", exc)

    @property
    def pool(self) -> Optional[asyncpg.Pool]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None
        return self._pools.get(loop)

    async def _get_pool(self) -> Optional[asyncpg.Pool]:
        pool = self.pool
        if not pool:
            logger.info("DB pool missing in current loop; attempting initialization")
            await self.ensure_initialized()
            pool = self.pool
        if not pool:
            logger.error("DB pool unavailable after initialization attempt")
        return pool

    async def get_business_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        logger.info("Fetching business profile for user_id=%s", user_id)
        pool = await self._get_pool()
        if not pool or not user_id:
            logger.warning("Skipping business profile fetch: pool_available=%s user_id_present=%s", bool(pool), bool(user_id))
            return None

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT bp.id, bp.user_id, bp.business_name, bp.industry, bp.business_size, bp.use_case,
                       bp.description, bp.website, bp.industry_vertical, bp.primary_use_case,
                       bp.target_audience, bp.brand_voice,
                       ai.system_prompt, ai.persona_description, ai.agent_name
                FROM business_profiles bp
                LEFT JOIN agent_identity ai ON bp.id = ai.business_profile_id
                WHERE bp.user_id::text = $1 AND bp.is_active = TRUE
                ORDER BY bp.updated_at DESC
                LIMIT 1
                """,
                user_id,
            )
            profile = dict(row) if row else None
            if profile:
                logger.info("Fetched business profile: %s", _preview_record(profile))
            else:
                logger.info("No active business profile found for user_id=%s", user_id)
            return profile

    async def get_onboarding_session(self, user_id: str) -> Optional[Dict[str, Any]]:
        logger.info("Fetching onboarding session for user_id=%s", user_id)
        pool = await self._get_pool()
        if not pool or not user_id:
            logger.warning("Skipping onboarding session fetch: pool_available=%s user_id_present=%s", bool(pool), bool(user_id))
            return None

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, user_id, onboarding_id, current_step, total_steps, status
                FROM onboarding_sessions
                WHERE user_id::text = $1
                  AND status IN ('started', 'in_progress')
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                user_id,
            )
            session = dict(row) if row else None
            if session:
                logger.info("Fetched onboarding session: %s", _preview_record(session))
            else:
                logger.info("No active onboarding session found for user_id=%s", user_id)
            return session

    async def get_onboarding_questions(self) -> List[Dict[str, Any]]:
        logger.info("Fetching onboarding questions and options")
        pool = await self._get_pool()
        if not pool:
            logger.warning("Skipping onboarding questions fetch: pool unavailable")
            return []

        async with pool.acquire() as conn:
            question_rows = await conn.fetch(
                """
                SELECT id, question_text, question_type, order_index, is_required
                FROM onboarding_questions
                ORDER BY order_index ASC
                """
            )
            option_rows = await conn.fetch(
                """
                SELECT question_id, option_value, option_label, order_index
                FROM onboarding_options
                ORDER BY question_id ASC, order_index ASC
                """
            )

        options_by_question: Dict[str, List[Dict[str, Any]]] = {}
        for row in option_rows:
            question_id = row["question_id"]
            options_by_question.setdefault(question_id, []).append(
                {
                    "option_value": row["option_value"],
                    "option_label": row["option_label"],
                    "order_index": row["order_index"],
                }
            )

        questions: List[Dict[str, Any]] = []
        for row in question_rows:
            question_id = row["id"]
            questions.append(
                {
                    "id": question_id,
                    "question_text": row["question_text"],
                    "question_type": row["question_type"],
                    "order_index": row["order_index"],
                    "is_required": row["is_required"],
                    "options": options_by_question.get(question_id, []),
                }
            )
        logger.info(
            "Fetched onboarding question set: questions=%d options=%d",
            len(questions),
            len(option_rows),
        )
        return questions

    async def get_onboarding_answers(self, onboarding_session_id: str) -> Dict[str, Dict[str, Any]]:
        logger.info("Fetching onboarding answers for session_id=%s", onboarding_session_id)
        pool = await self._get_pool()
        if not pool or not onboarding_session_id:
            logger.warning(
                "Skipping onboarding answers fetch: pool_available=%s session_id_present=%s",
                bool(pool),
                bool(onboarding_session_id),
            )
            return {}

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT question_id, answer, answer_type
                FROM onboarding_answers
                WHERE onboarding_session_id = $1
                """,
                onboarding_session_id,
            )

        answer_map = {
            row["question_id"]: {
                "answer": row["answer"],
                "answer_type": row["answer_type"],
            }
            for row in rows
        }
        logger.info(
            "Fetched onboarding answers: session_id=%s answers=%d question_ids=%s",
            onboarding_session_id,
            len(answer_map),
            list(answer_map.keys()),
        )
        return answer_map

    async def upsert_onboarding_answer(
        self,
        onboarding_session_id: str,
        question_id: str,
        answer: str,
        answer_type: str,
    ) -> bool:
        logger.info(
            "Upserting onboarding answer: session_id=%s question_id=%s answer_type=%s answer_preview=%s",
            onboarding_session_id,
            question_id,
            answer_type,
            (answer or "")[:120],
        )
        pool = await self._get_pool()
        if not pool:
            logger.error("Failed to upsert onboarding answer: pool unavailable")
            return False

        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO onboarding_answers (
                        onboarding_session_id, question_id, answer, answer_type
                    )
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (onboarding_session_id, question_id)
                    DO UPDATE
                    SET answer = EXCLUDED.answer,
                        answer_type = EXCLUDED.answer_type,
                        updated_at = now()
                    """,
                    onboarding_session_id,
                    question_id,
                    answer,
                    answer_type,
                )

                counts = await conn.fetchrow(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM onboarding_answers WHERE onboarding_session_id = $1) AS answered_count,
                        (SELECT total_steps FROM onboarding_sessions WHERE id = $1) AS total_steps
                    """,
                    onboarding_session_id,
                )

                if counts:
                    answered_count = int(counts["answered_count"] or 0)
                    total_steps = int(counts["total_steps"] or 0)
                    is_completed = total_steps > 0 and answered_count >= total_steps

                    logger.info(
                        "Onboarding progress after save: session_id=%s answered=%d total=%d completed=%s",
                        onboarding_session_id,
                        answered_count,
                        total_steps,
                        is_completed,
                    )

                    await conn.execute(
                        """
                        UPDATE onboarding_sessions
                        SET current_step = $2,
                            status = CASE WHEN $3 THEN 'completed' ELSE 'in_progress' END,
                            completed_at = CASE WHEN $3 THEN now() ELSE completed_at END,
                            updated_at = now()
                        WHERE id = $1
                        """,
                        onboarding_session_id,
                        answered_count,
                        is_completed,
                    )

        logger.info(
            "Onboarding answer upsert succeeded: session_id=%s question_id=%s",
            onboarding_session_id,
            question_id,
        )
        return True


db = Database()
