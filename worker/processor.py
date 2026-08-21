import asyncio
import aiohttp
import os
from concurrent.futures import ThreadPoolExecutor
from core.logger import get_logger
from worker.graph import build_graph, AgentState

logger = get_logger("worker.processor")

GATEWAY_CALLBACK_URL = os.getenv("GATEWAY_CALLBACK_URL", "http://localhost:3000/jobs/callback")
CALLBACK_MAX_RETRIES = int(os.getenv("CALLBACK_MAX_RETRIES", "5"))
CALLBACK_BASE_DELAY = float(os.getenv("CALLBACK_BASE_DELAY_SECONDS", "1.0"))
CALLBACK_MAX_DELAY = float(os.getenv("CALLBACK_MAX_DELAY_SECONDS", "30.0"))

_THREAD_POOL = ThreadPoolExecutor(
    max_workers=int(os.getenv("WORKER_CONCURRENCY", "3")),
    thread_name_prefix="langgraph",
)


class AuraFlowProcessor:
    def __init__(self):
        self.graph = build_graph()
        self._jobs_processed = 0
        self._jobs_failed = 0
        self._active_jobs: set[str] = set()

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
                "raw_data": raw_data,
                "sanitized_data": "",
                "sanitize_log": [],
                "cleaned_data": "",
                "is_valid": False,
                "confidence": 0.0,
                "attempt": 0,
                "validation_reason": "",
                "issues": [],
            }

            logger.info("job_processing job_id=%-30s preview=%s",
                job_id, raw_data[:40])

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                _THREAD_POOL,
                self.graph.invoke,
                initial_state,
            )

            logger.info(
                "job_finished  job_id=%-30s is_valid=%s confidence=%.2f attempts=%d sanitize_log=%s",
                job_id, result["is_valid"], result["confidence"],
                result["attempt"], result["sanitize_log"],
            )

            failed_reason = None
            if not result["is_valid"] or result["confidence"] < float(os.getenv("MIN_CONFIDENCE_SCORE", "0.8")):
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
                    "sanitized_data": "",
                    "sanitize_log": [],
                    "cleaned_data": "",
                    "is_valid": False,
                    "confidence": 0.0,
                    "attempt": 0,
                    "validation_reason": "",
                    "issues": [],
                }, failed_reason)
            except Exception as cb_err:
                logger.error("callback_on_error_failed job_id=%-30s error=%s", job_id, cb_err)

            raise

        finally:
            self._active_jobs.discard(job_id)
            logger.info(
                "job_done      job_id=%-30s remaining_active=%d",
                job_id, len(self._active_jobs),
            )

    async def _send_callback(self, job_id: str, result: dict, failed_reason: str = None) -> bool:
        payload = {
            "jobId": job_id,
            "status": "completed" if (result["is_valid"] and result.get("confidence", 0) >= float(os.getenv("MIN_CONFIDENCE_SCORE", "0.8"))) else "failed",
            "cleanedData": result["cleaned_data"],
            "isValid": result["is_valid"],
            "confidence": result.get("confidence", 0.0),
            "attempts": result["attempt"],
            "validationReason": result["validation_reason"],
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
                            logger.info("callback_sent   job_id=%-30s status=%d attempt=%d",
                                job_id, resp.status, attempt)
                            return True
                        logger.warning("callback_bad_status job_id=%-30s status=%d attempt=%d/%d",
                            job_id, resp.status, attempt, CALLBACK_MAX_RETRIES)
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