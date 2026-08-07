import asyncio
import json
import os
import aiohttp
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=False)

from bullmq import Worker
from core.logger import get_logger
from worker.graph import build_graph, AgentState

logger = get_logger("worker.main")

QUEUE_NAME = os.getenv("QUEUE_NAME", "auraflow-jobs")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
GATEWAY_CALLBACK_URL = os.getenv("GATEWAY_CALLBACK_URL", "http://localhost:3000/jobs/callback")
CALLBACK_MAX_RETRIES = int(os.getenv("CALLBACK_MAX_RETRIES", "5"))
CALLBACK_BASE_DELAY = float(os.getenv("CALLBACK_BASE_DELAY_SECONDS", "1.0"))
CALLBACK_MAX_DELAY = float(os.getenv("CALLBACK_MAX_DELAY_SECONDS", "30.0"))

# Concurrency: berapa job diproses parallel dalam satu worker instance
# Hati-hati: setiap concurrent job = 2 LLM calls bersamaan
# Custom endpoint limit 60 req/min → max concurrency aman = 5
WORKER_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "3"))

graph = build_graph()


async def send_callback(job_id: str, result: dict) -> bool:
    payload = {
        "jobId": job_id,
        "status": "completed" if result["is_valid"] else "failed",
        "cleanedData": result["cleaned_data"],
        "isValid": result["is_valid"],
        "attempts": result["attempt"],
        "validationReason": result["validation_reason"],
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
                            "callback_sent job_id=%s status_code=%d attempt=%d",
                            job_id, resp.status, attempt,
                        )
                        return True
                    logger.warning(
                        "callback_unexpected_status job_id=%s status_code=%d attempt=%d/%d",
                        job_id, resp.status, attempt, CALLBACK_MAX_RETRIES,
                    )
        except aiohttp.ClientConnectorError as e:
            logger.warning("callback_connection_error job_id=%s error=%s attempt=%d/%d",
                job_id, e, attempt, CALLBACK_MAX_RETRIES)
        except asyncio.TimeoutError:
            logger.warning("callback_timeout job_id=%s attempt=%d/%d",
                job_id, attempt, CALLBACK_MAX_RETRIES)
        except Exception as e:
            logger.error("callback_unexpected_error job_id=%s error=%s attempt=%d/%d",
                job_id, e, attempt, CALLBACK_MAX_RETRIES)

        if attempt < CALLBACK_MAX_RETRIES:
            delay = min(CALLBACK_BASE_DELAY * (2 ** (attempt - 1)), CALLBACK_MAX_DELAY)
            logger.info("callback_retry_scheduled job_id=%s delay=%.1fs next_attempt=%d",
                job_id, delay, attempt + 1)
            await asyncio.sleep(delay)

    logger.error("callback_all_retries_exhausted job_id=%s max_retries=%d",
        job_id, CALLBACK_MAX_RETRIES)
    return False


async def process_job(job, job_token):
    job_id = job.data.get("jobId") or job.id
    logger.info("job_received job_id=%s worker_concurrency=%d", job_id, WORKER_CONCURRENCY)

    raw_data = job.data.get("rawData", "")
    if not raw_data:
        logger.error("job_invalid job_id=%s reason=missing_rawData", job_id)
        raise ValueError("Missing rawData in job payload")

    initial_state: AgentState = {
        "raw_data": raw_data,
        "cleaned_data": "",
        "is_valid": False,
        "attempt": 0,
        "validation_reason": "",
    }

    logger.info("job_processing job_id=%s", job_id)
    result = graph.invoke(initial_state)
    logger.info("job_finished job_id=%s is_valid=%s attempts=%d",
        job_id, result["is_valid"], result["attempt"])

    success = await send_callback(job_id, result)
    if not success:
        raise RuntimeError(f"Callback failed after {CALLBACK_MAX_RETRIES} retries for job {job_id}")

    return result


async def main():
    logger.info(
        "worker_starting queue=%s redis=%s concurrency=%d",
        QUEUE_NAME, REDIS_URL, WORKER_CONCURRENCY
    )

    worker = Worker(
        QUEUE_NAME,
        process_job,
        {
            "connection": REDIS_URL,
            "concurrency": WORKER_CONCURRENCY,  # ini yang berubah
        }
    )

    logger.info("worker_ready waiting_for_jobs concurrency=%d", WORKER_CONCURRENCY)

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("worker_shutdown signal_received")
        await worker.close()


if __name__ == "__main__":
    asyncio.run(main())