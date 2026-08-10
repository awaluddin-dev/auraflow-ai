import os
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(
    title="AuraFlow Worker",
    description="Health and metrics for AuraFlow AI worker",
    version="1.0.0",
)

# Reference ke processor di-inject dari main.py
_processor = None

def set_processor(processor):
    global _processor
    _processor = processor


class HealthResponse(BaseModel):
    status: str
    queue: str
    concurrency: int
    redis_url: str


class MetricsResponse(BaseModel):
    jobs_processed: int
    jobs_failed: int
    active_jobs: list[str]
    active_count: int


@app.get("/health", response_model=HealthResponse)
def health():
    return {
        "status": "ok",
        "queue": os.getenv("QUEUE_NAME", "auraflow-jobs"),
        "concurrency": int(os.getenv("WORKER_CONCURRENCY", "3")),
        "redis_url": os.getenv("REDIS_URL", "redis://localhost:6379"),
    }


@app.get("/metrics", response_model=MetricsResponse)
def metrics():
    if _processor is None:
        return {
            "jobs_processed": 0,
            "jobs_failed": 0,
            "active_jobs": [],
            "active_count": 0,
        }
    return {
        "jobs_processed": _processor.jobs_processed,
        "jobs_failed": _processor.jobs_failed,
        "active_jobs": _processor.active_jobs,
        "active_count": len(_processor.active_jobs),
    }


@app.get("/ready")
def ready():
    """Kubernetes readiness probe."""
    if _processor is None:
        return {"ready": False}
    return {"ready": True}