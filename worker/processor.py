from anthropic.types.beta import beta_managed_agents_agent_tool_config_params
from anthropic.types.beta import beta_managed_agents_agent_tool_config_params
import asyncio
import aiohttp
import os
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=False)

from core.logger import get_logger
from worker.graph import build_graph, AgentState

logger = get_logger("worker.processor")

GATEWAY_CALLBACK_URL = os.getenv("GATEWAY_CALLBACK_URL", "http://localhost:3000/jobs/callback")
CALLBACK_MAX_RETRIES = int(os.getenv("CALLBACK_MAX_RETRIES", "5"))
CALLBACK_BASE_DELAY = float(os.getenv("CALLBACK_BASE_DELAY_SECONDS", "1.0"))
CALLBACK_MAX_DELAY = float(os.getenv("CALLBACK_MAX_DELAY_SECONDS", "30.0"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE_SCORE", "0.8"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Checkpoint TTL — hapus otomatis setelah 24 jam
# Tidak perlu simpan checkpoint selamanya, hanya untuk fault tolerance
CHECKPOINT_TTL_MINUTES = int(os.getenv("CHECKPOINT_TTL_MINUTES", "1440"))

_THREAD_POOL = ThreadPoolExecutor(
    max_workers=int(os.getenv("WORKER_CONCURRENCY", "3")),
    thread_name_prefix="langgraph",
)


class AuraFlowProcessor:
    def __init__(self):
        self._checkpointer = None
        self._graph = None
        self._jobs_processed = 0
        self._jobs_failed = 0
        self._active_jobs: set[str] = set()
        self._background_tasks = set()

    async def setup(self):
        """Init checkpointer async — dipanggil dari main() sebelum worker start."""
        try:
            from langgraph.checkpoint.redis.aio import AsyncRedisSaver

            self._checkpointer = AsyncRedisSaver(
                redis_url=REDIS_URL,
                ttl={
                    "default_ttl": CHECKPOINT_TTL_MINUTES,
                    "refresh_on_read": False,  # tidak perlu refresh, checkpoint bersifat sementara
                },
            )
            await self._checkpointer.asetup()
            self._graph = build_graph(checkpointer=self._checkpointer)
            logger.info(
                "processor_setup checkpointer=redis ttl_minutes=%d",
                CHECKPOINT_TTL_MINUTES,
            )
        except Exception as e:
            logger.error(
                "processor_setup checkpointer_failed error=%s — fallback to no checkpoint", e
            )
            self._graph = build_graph(checkpointer=None)

    async def teardown(self):
        if self._checkpointer:
            try:
                await self._checkpointer.aclose()
                logger.info("processor_teardown checkpointer_closed")
            except Exception as e:
                logger.warning("processor_teardown error=%s", e)

    @property
    def jobs_processed(self) -> int:
        return self._jobs_processed

    @property
    def jobs_failed(self) -> int:
        return self._jobs_failed

    @property
    def active_jobs(self) -> list[str]:
        return list(self._active_jobs)

    async def process(self, job, job_token) -> dict:
        job_id = job.data.get("jobId") or job.id
        self._active_jobs.add(job_id)

        logger.info(
            "job_received job_id=%-30s active_count=%d active_jobs=[%s]",
            job_id, len(self._active_jobs),
            ", ".join(list(self._active_jobs)[:3]),
        )

        try:
            raw_data = job.data.get("rawData", "")
            if not raw_data:
                raise ValueError(f"Missing rawData in job {job_id}")

            initial_state: AgentState = {
                "job_id": job_id,
                "raw_data": raw_data,
                "sanitized_data": "",
                "sanitize_log": [],
                "cleaned_data": "",
                "is_valid": False,
                "confidence": 0.0,
                "attempt": 0,
                "validation_reason": "",
                "issues": [],
                "hitl_reasons": [],
                "review_decision": "",
                "review_edited_data": "",
                "review_note": "",
            }

            invoke_config = {"configurable": {"thread_id": job_id}}

            logger.info("job_processing job_id=%-30s preview=%s checkpoint=%s",
                job_id, raw_data[:40],
                "enabled" if self._checkpointer else "disabled")

            loop = asyncio.get_event_loop()

            # graph.invoke() dengan interrupt_before akan RETURN (bukan raise)
            # saat graph pause — return value berisi __interrupt__ key
            result = await loop.run_in_executor(
                _THREAD_POOL,
                lambda: self._graph.invoke(initial_state, invoke_config),
            )

            # Log untuk debug
            logger.debug("invoke_result keys=%s",
                list(result.keys()) if isinstance(result, dict) else type(result))

            # interrupt() di dalam node → result["__interrupt__"] berisi tuple Interrupt objects
            interrupts = result.get("__interrupt__") if isinstance(result, dict) else None

            logger.debug("invoke_result __interrupt__=%s type=%s",
                interrupts, type(interrupts).__name__ if interrupts is not None else "None")

            if interrupts:
                # Ada interrupt — graph pause, tunggu review
                logger.info(
                    "job_interrupted job_id=%-30s hitl_reasons=%s waiting_for_review",
                    job_id, result.get("hitl_reasons", []),
                )
                await self._send_review_callback(job_id, result)
                task = asyncio.create_task(self._listen_for_resume(job_id))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
                self._jobs_processed += 1
                return {"status": "pending_review", "jobId": job_id}

            # Normal completion
            logger.info(
                "job_finished  job_id=%-30s is_valid=%s confidence=%.2f attempts=%d sanitize_log=%s",
                job_id, result["is_valid"], result["confidence"],
                result["attempt"], result.get("sanitize_log", []),
            )

            failed_reason = None
            if not result["is_valid"] or result["confidence"] < MIN_CONFIDENCE:
                failed_reason = (
                    f"Max parse attempts reached. "
                    f"confidence={result['confidence']:.2f} "
                    f"reason={result['validation_reason']} "
                    f"issues={result['issues']}"
                )
                logger.warning("job_invalid job_id=%-30s reason=%s", job_id, failed_reason)

            success = await self._send_callback(job_id, result, failed_reason)
            if not success:
                raise RuntimeError(f"Callback failed after {CALLBACK_MAX_RETRIES} retries")

            self._jobs_processed += 1
            return result

        except Exception as e:
            self._jobs_failed += 1
            failed_reason = str(e)
            logger.error("job_error job_id=%-30s error=%s", job_id, failed_reason)

            try:
                await self._send_callback(job_id, {
                    "job_id": job_id,
                    "sanitized_data": "",
                    "sanitize_log": [],
                    "cleaned_data": "",
                    "is_valid": False,
                    "confidence": 0.0,
                    "attempt": 0,
                    "validation_reason": "",
                    "issues": [],
                    "hitl_reasons": [],
                    "review_decision": "",
                    "review_edited_data": "",
                    "review_note": "",
                }, failed_reason)
            except Exception as cb_err:
                logger.error("callback_on_error_failed job_id=%-30s error=%s", job_id, cb_err)

            raise

        finally:
            self._active_jobs.discard(job_id)
            logger.info("job_done      job_id=%-30s remaining_active=%d",
                job_id, len(self._active_jobs))

    async def _send_review_callback(self, job_id: str, state: dict) -> None:
        payload = {
            "jobId": job_id,
            "status": "pending_review",
            "cleanedData": state.get("cleaned_data", ""),
            "isValid": state.get("is_valid", False),
            "confidence": state.get("confidence", 0.0),
            "attempts": state.get("attempt", 0),
            "validationReason": state.get("validation_reason", ""),
            "issues": state.get("issues", []),
            "sanitizeLog": state.get("sanitize_log", []),
            "hitlReasons": state.get("hitl_reasons", []),
            "failedReason": None,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    GATEWAY_CALLBACK_URL,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    logger.info(
                        "review_callback_sent job_id=%-30s status=%d",
                        job_id, resp.status,
                    )
        except Exception as e:
            logger.error("review_callback_failed job_id=%-30s error=%s", job_id, e)

    async def _listen_for_resume(self, job_id: str) -> None:
        """
        Subscribe ke Redis channel job-resume:{jobId}.
        Tunggu sinyal dari gateway setelah reviewer membuat keputusan.
        Resume graph dengan Command(resume=...).
        """
        import redis.asyncio as aioredis
        from langgraph.types import Command

        sub = aioredis.Redis.from_url(REDIS_URL, decode_responses=True)
        pubsub = sub.pubsub()
        channel = f"job-resume:{job_id}"

        await pubsub.subscribe(channel)
        logger.info("resume_listener_started job_id=%-30s channel=%s", job_id, channel)

        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                payload = json.loads(message["data"])
                decision = payload.get("decision")
                edited_data = payload.get("editedData", "")
                note = payload.get("note", "")

                logger.info(
                    "resume_received job_id=%-30s decision=%s",
                    job_id, decision,
                )

                invoke_config = {"configurable": {"thread_id": job_id}}

                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    _THREAD_POOL,
                    lambda: self._graph.invoke(
                        Command(resume={
                            "decision": decision,
                            "editedData": edited_data,
                            "note": note,
                        }),
                        invoke_config,
                    ),
                )

                logger.info(
                    "resume_finished job_id=%-30s is_valid=%s confidence=%.2f",
                    job_id,
                    result.get("is_valid"),
                    result.get("confidence", 0.0),
                )

                failed_reason = None
                if not result.get("is_valid") or result.get("confidence", 0) < MIN_CONFIDENCE:
                    failed_reason = (
                        f"Review decision={decision}. "
                        f"confidence={result.get('confidence', 0):.2f}"
                    )

                await self._send_callback(job_id, result, failed_reason)
                break

        except Exception as e:
            logger.error("resume_listener_error job_id=%-30s error=%s", job_id, e)
        finally:
            await pubsub.unsubscribe(channel)
            await sub.aclose()
            logger.info("resume_listener_stopped job_id=%-30s", job_id)

    async def _send_callback(self, job_id: str, result: dict, failed_reason: str = None) -> bool:
        is_valid = result.get("is_valid", False)
        confidence = result.get("confidence", 0.0)

        payload = {
            "jobId": job_id,
            "status": "completed" if (is_valid and confidence >= MIN_CONFIDENCE) else "failed",
            "cleanedData": result.get("cleaned_data", ""),
            "isValid": is_valid,
            "confidence": confidence,
            "attempts": result.get("attempt", 0),
            "validationReason": result.get("validation_reason", ""),
            "issues": result.get("issues", []),
            "sanitizeLog": result.get("sanitize_log", []),
            "failedReason": failed_reason,
        }

        for attempt in range(1, CALLBACK_MAX_RETRIES + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        GATEWAY_CALLBACK_URL,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status in (200, 201, 409):
                            logger.info(
                                "callback_sent   job_id=%-30s status=%d attempt=%d",
                                job_id, resp.status, attempt,
                            )
                            return True
                        logger.warning(
                            "callback_bad_status job_id=%-30s status=%d attempt=%d/%d",
                            job_id, resp.status, attempt, CALLBACK_MAX_RETRIES,
                        )
            except aiohttp.ClientConnectorError as e:
                logger.warning("callback_conn_err job_id=%-30s error=%s attempt=%d/%d",
                    job_id, e, attempt, CALLBACK_MAX_RETRIES)
            except asyncio.TimeoutError:
                logger.warning("callback_timeout  job_id=%-30s attempt=%d/%d",
                    job_id, attempt, CALLBACK_MAX_RETRIES)
            except Exception as e:
                logger.error("callback_error    job_id=%-30s error=%s attempt=%d/%d",
                    job_id, e, attempt, CALLBACK_MAX_RETRIES)

            if attempt < CALLBACK_MAX_RETRIES:
                delay = min(CALLBACK_BASE_DELAY * (2 ** (attempt - 1)), CALLBACK_MAX_DELAY)
                logger.info("callback_retry    job_id=%-30s delay=%.1fs next=%d",
                    job_id, delay, attempt + 1)
                await asyncio.sleep(delay)

        logger.error("callback_exhausted job_id=%-30s", job_id)
        return False