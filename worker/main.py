import asyncio
import json
import os
import aiohttp
from pathlib import Path
from dotenv import load_dotenv
from bullmq import Worker

from core.logger import get_logger
from worker.graph import build_graph, AgentState

load_dotenv(Path(__file__).parent.parent / ".env")
logger = get_logger("worker.main")

QUEUE_NAME = os.getenv("QUEUE_NAME", "auraflow-jobs")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
GATEWAY_CALLBACK_URL = os.getenv("GATEWAY_CALLBACK_URL", "http://localhost:3000/jobs/callback")

graph = build_graph()


async def send_callback(job_id: str, result: dict):
    payload = {
        "jobId": job_id,
        "status": "completed" if result["is_valid"] else "failed",
        "cleanedData": result["cleaned_data"],
        "isValid": result["is_valid"],
        "attempts": result["attempt"],
        "validationReason": result["validation_reason"],
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GATEWAY_CALLBACK_URL, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                logger.info("callback_sent job_id=%s status_code=%d", job_id, resp.status)
    except Exception as e:
        logger.error("callback_failed job_id=%s error=%s", job_id, e)


async def process_job(job, job_token):
    # jobId sekarang dikirim dari gateway dalam job.data
    job_id = job.data.get("jobId") or job.id
    logger.info("job_received job_id=%s", job_id)

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
    logger.info(
        "job_finished job_id=%s is_valid=%s attempts=%d",
        job_id, result["is_valid"], result["attempt"]
    )

    await send_callback(job_id, result)
    return result


async def main():
    logger.info("worker_starting queue=%s redis=%s", QUEUE_NAME, REDIS_URL)
    worker = Worker(QUEUE_NAME, process_job, {"connection": REDIS_URL})
    logger.info("worker_ready waiting_for_jobs")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("worker_shutdown signal_received")
        await worker.close()


if __name__ == "__main__":
    asyncio.run(main())