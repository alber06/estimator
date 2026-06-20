import structlog
import uuid

from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile
from app.dependencies import get_estimation_service, get_session_store
from app.services.session import SessionStore, Session
from app.schemas.estimation import EstimationResponse
from app.services.estimation import EstimationService
from app.guardrails.input import InputGuardrailViolation


from app.schemas.session import SessionResponse
from app.schemas.estimation import ProjectType, DetailLevel, OutputFormat
from app.services.content_extractor import UnsupportedFileTypeError, extract_content

log = structlog.get_logger()

router = APIRouter(prefix="/sessions", tags=["sessions"])

@router.post("")
def create_session(store: SessionStore = Depends(get_session_store)) -> SessionResponse:
    session = Session()
    store.add(session)
    
    return SessionResponse(session_id=session.id)

@router.post("/{session_id}/estimate", response_model=EstimationResponse)
def create_estimation_in_session(
    session_id: uuid.UUID,
    transcript: str = Form(..., min_length=20, max_length=80_000),
    project_type: ProjectType = Form(...),
    detail_level: DetailLevel = Form(...),
    output_format: OutputFormat = Form(...),
    attachments: list[UploadFile] = File(default_factory=list),
    store: SessionStore = Depends(get_session_store),
    service: EstimationService = Depends(get_estimation_service),
) -> EstimationResponse:
    """Run the full estimation pipeline and return the structured response."""

    log.info(
        "estimation_request_received",
        project_type=project_type.value,
        detail_level=detail_level.value,
        output_format=output_format.value,
        description_chars=len(transcript),
        attachments=len(attachments),
    )

    description_with_attachments = transcript
    for attachment in attachments if attachments else []:
        filename = attachment.filename
        if not filename:
            raise HTTPException(status_code=400, detail="Attachment filename is required")
        try:
            extracted = extract_content(filename, attachment.file.read())
        except UnsupportedFileTypeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        description_with_attachments += f"\n--- attachment: {filename} ---\n{extracted}\n--- end attachment ---"

    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        return service.estimate_conversation(
            transcript=description_with_attachments,
            project_type=project_type,
            detail_level=detail_level,
            output_format=output_format,
            session=session,
        )
    except InputGuardrailViolation as exc:
        log.info(
            "estimation_blocked_by_input_guardrail",
            reason=exc.reason,
            message=exc.message,
        )
        raise HTTPException(
            status_code=400, detail={"reason": exc.reason, "message": exc.message}
        ) from exc
    except Exception as exc:
        log.error(
            "estimation_endpoint_error",
            error=str(exc)[:400],
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail="Upstream LLM call failed") from exc