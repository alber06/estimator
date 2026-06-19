from fastapi import APIRouter, Depends
from app.dependencies import get_session_store
from app.services.session import SessionStore

from app.schemas.session import Session, SessionResponse

router = APIRouter(prefix="/api/v1", tags=["sessions"])

@router.post("/sessions")
def create_session(store: SessionStore = Depends(get_session_store)) -> SessionResponse:
    session = Session()
    store.add(session)
    
    return SessionResponse(session_id=session.id)