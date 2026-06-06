import structlog

from collections.abc import AsyncIterable

from fastapi import APIRouter, HTTPException
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.schemas.estimation import EstimationRequest, EstimationResponse, EstimationStreamRequest
from app.services.evaluation import evaluate_estimation_structure
from app.services.llm_service import GenerationOptions, LLMServiceError, generate_estimation, generate_estimation_stream

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1", tags=["estimations"])


@router.post("/estimate", response_model=EstimationResponse)
async def create_estimation(request: EstimationRequest) -> EstimationResponse:
    """Receive a meeting transcription and return a software project estimation."""
    opts = GenerationOptions(
        preprocessing=request.preprocessing,
        example_format=request.example_format,
        num_examples=request.num_examples,
        use_examples=request.use_examples,
        model=request.model,
        max_tokens=request.max_tokens,
        thinking_budget=request.thinking_budget,
    )

    try:
        result = generate_estimation(request.transcription, opts)
    except LLMServiceError as exc:
        log.error("estimation_endpoint_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

    validation = (
        evaluate_estimation_structure(result["estimation"], result["finish_reason"])
        if request.evaluate
        else None
    )

    return EstimationResponse(**result, validation=validation)

@router.post("/estimate/stream", response_class=EventSourceResponse)
async def estimate_stream(request: EstimationStreamRequest) -> AsyncIterable[ServerSentEvent]:
    try:
        for event in generate_estimation_stream(request.transcription):
            yield ServerSentEvent(data=event)
    except LLMServiceError as exc:
        log.error("estimation_stream_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc