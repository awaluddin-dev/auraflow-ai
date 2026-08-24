import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from worker.processor import AuraFlowProcessor

@pytest.fixture
def processor():
    return AuraFlowProcessor()

@pytest.mark.asyncio
async def test_send_callback_success(processor, mocker):
    mock_post = mocker.patch("aiohttp.ClientSession.post")
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_post.return_value.__aenter__.return_value = mock_response

    result = await processor._send_callback("job1", {"is_valid": True, "confidence": 0.95})
    assert result is True

@pytest.mark.asyncio
async def test_send_callback_idempotent_conflict(processor, mocker):
    mock_post = mocker.patch("aiohttp.ClientSession.post")
    mock_response = AsyncMock()
    mock_response.status = 409
    mock_post.return_value.__aenter__.return_value = mock_response

    result = await processor._send_callback("job1", {"is_valid": True})
    assert result is True # 409 means already processed, considered success

@pytest.mark.asyncio
async def test_send_callback_failure_retry(processor, mocker):
    # Reduce delay for fast testing
    mocker.patch("worker.processor.CALLBACK_BASE_DELAY", 0.01)
    
    mock_post = mocker.patch("aiohttp.ClientSession.post")
    mock_response = AsyncMock()
    mock_response.status = 500
    mock_post.return_value.__aenter__.return_value = mock_response

    result = await processor._send_callback("job1", {"is_valid": True})
    assert result is False
    assert mock_post.call_count == 5 # CALLBACK_MAX_RETRIES is 5

@pytest.mark.asyncio
async def test_process_job_completed(processor, mocker):
    mocker.patch.object(processor, '_send_callback', return_value=True)
    mocker.patch('worker.processor.get_logger')
    
    # Mocking the graph to return a specific state
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "is_valid": True,
        "confidence": 0.95,
        "attempt": 1,
        "cleaned_data": "{}"
    }
    processor._graph = mock_graph
    
    # Mock job
    mock_job = AsyncMock()
    mock_job.data = {"jobId": "job1", "rawData": "raw data"}
    mock_job.id = "job1"
    
    result = await processor.process(mock_job, "token")
    
    assert result["is_valid"] is True
    assert result["confidence"] == 0.95

@pytest.mark.asyncio
async def test_process_job_pending_review(processor, mocker):
    mocker.patch.object(processor, '_send_callback', return_value=True)
    mocker.patch.object(processor, '_send_review_callback', return_value=None)
    mocker.patch.object(processor, '_listen_for_resume', return_value=None)
    
    # Mocking the graph to return a specific state
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "__interrupt__": (True,), # Set interrupt to simulate pause
        "is_valid": True,
        "confidence": 0.85, # Below MIN_CONFIDENCE
        "attempt": 1,
        "hitl_reasons": ["name is unusually short"],
        "cleaned_data": "{}"
    }
    processor._graph = mock_graph
    
    # Mock job
    mock_job = AsyncMock()
    mock_job.data = {"jobId": "job1", "rawData": "raw data"}
    mock_job.id = "job1"
    
    # Mock asyncio.create_task to avoid hanging
    mocker.patch("asyncio.create_task")
    
    result = await processor.process(mock_job, "token")
    
    assert result["status"] == "pending_review"
    assert result["jobId"] == "job1"
