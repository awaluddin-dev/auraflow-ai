import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=False)

import uvicorn
from bullmq import Worker
from core.logger import get_logger
from worker.processor import AuraFlowProcessor
from worker.api import app, set_processor

logger = get_logger("worker.main")

QUEUE_NAME = os.getenv("QUEUE_NAME", "auraflow-jobs")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
WORKER_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "3"))
API_PORT = int(os.getenv("WORKER_API_PORT", "8001"))


async def main():
    # Init processor
    processor = AuraFlowProcessor()
    set_processor(processor)

    logger.info(
        "worker_starting queue=%s redis=%s concurrency=%d api_port=%d",
        QUEUE_NAME, REDIS_URL, WORKER_CONCURRENCY, API_PORT,
    )

    # BullMQ worker
    bullmq_worker = Worker(
        QUEUE_NAME,
        processor.process,
        {
            "connection": REDIS_URL,
            "concurrency": WORKER_CONCURRENCY,
        }
    )

    logger.info("worker_ready waiting_for_jobs concurrency=%d", WORKER_CONCURRENCY)

    # FastAPI via uvicorn — non-blocking
    uvicorn_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=API_PORT,
        log_level="warning",  # suppress uvicorn access logs, pakai logger kita
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)

    async def keep_alive():
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("worker_shutdown signal_received")
            await bullmq_worker.close()

    # Jalankan keduanya bersamaan
    await asyncio.gather(
        uvicorn_server.serve(),
        keep_alive(),
    )


if __name__ == "__main__":
    asyncio.run(main())