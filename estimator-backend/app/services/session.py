"""Session-scoped state for multi-turn estimation conversations.

Conversation history and project metadata are held in memory for the lifetime
of the process. That volatility is deliberate at this stage as it keeps it simple
for us to prototype without adding extra complexity, which will be added at later stages.
"""

from __future__ import annotations

from functools import lru_cache
import uuid

import structlog

from app.prompts import render_extract_metadata_prompt
from app.schemas.estimation import EstimationResult
from app.schemas.session import Message, ProjectMetadata
from app.services.llm_wrapper import LLMWrapper

log = structlog.get_logger()

DEFAULT_MAX_TURNS = 20


class ConversationHistory:
    """Sliding window of user/assistant messages."""

    def __init__(
        self,
        *,
        system_prompt: str = "",
        max_turns: int = DEFAULT_MAX_TURNS,
    ) -> None:
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self._messages: list[Message] = []

    @property
    def messages(self) -> list[Message]:
        """Non-system messages only, oldest first."""
        return list(self._messages)

    def set_system_prompt(self, content: str) -> None:
        self.system_prompt = content

    def append(self, message: Message) -> None:
        self._messages.append(message)
        while len(self._messages) > self.max_turns:
            self._messages.pop(0)

    def as_llm_messages(self) -> list[dict[str, str]]:
        """Chat-completions shape: pinned system message plus the window."""

        out: list[dict[str, str]] = []

        if (self.system_prompt):
            out.append({"role": "system", "content": self.system_prompt})

        out.extend(m.model_dump() for m in self._messages)
        return out


def merge_project_metadata(
    existing: ProjectMetadata,
    extracted: ProjectMetadata,
) -> ProjectMetadata:
    """Merge extracted metadata into the session snapshot."""
    merged = existing.model_copy(deep=True)

    if extracted.project_name:
        merged.project_name = extracted.project_name
    if extracted.assumed_team_size is not None:
        merged.assumed_team_size = extracted.assumed_team_size
    if extracted.agreed_scope:
        merged.agreed_scope = extracted.agreed_scope

    seen = {tech.casefold() for tech in merged.mentioned_technologies}
    for tech in extracted.mentioned_technologies:
        if tech.casefold() not in seen:
            merged.mentioned_technologies.append(tech)
            seen.add(tech.casefold())

    return merged


def update_project_metadata_from_estimation(
    session: Session,
    *,
    transcript: str,
    estimation_result: EstimationResult,
    llm_wrapper: LLMWrapper,
) -> None:
    """Extract project metadata from the estimation and merge it into the session."""
    existing_metadata = (
        session.project_metadata if session.project_metadata.has_content() else None
    )
    system_prompt, user_message = render_extract_metadata_prompt(
        transcript=transcript,
        estimation=estimation_result,
        existing_metadata=existing_metadata,
    )

    try:
        extracted, meta = llm_wrapper.complete_structured(
            system_prompt=system_prompt,
            user_message=user_message,
            response_model=ProjectMetadata,
        )
    except Exception as exc:
        log.warning(
            "project_metadata_extraction_failed",
            session_id=str(session.id),
            error_type=type(exc).__name__,
            error=str(exc)[:400],
        )
        return

    before = session.project_metadata.model_dump(mode="json")
    session.project_metadata = merge_project_metadata(session.project_metadata, extracted)
    after = session.project_metadata.model_dump(mode="json")
    changed_fields = [field for field in before if before[field] != after[field]]

    log.info(
        "project_metadata_updated",
        session_id=str(session.id),
        changed_fields=changed_fields,
        **meta,
    )


class Session:
    """One conversational estimation context, keyed by ``session_id``."""

    def __init__(
        self,
        id: uuid.UUID | None = None,
        *,
        project_metadata: ProjectMetadata | None = None,
        conversation_history: ConversationHistory | None = None,
    ) -> None:
        self.id = id or uuid.uuid4()
        self.project_metadata = project_metadata or ProjectMetadata()
        self.conversation_history = conversation_history or ConversationHistory()


class SessionStore:
    """``session_id -> Session`` map living in process memory."""

    def __init__(self) -> None:
        self._sessions: dict[uuid.UUID, Session] = {}
    
    def get(self, session_id: uuid.UUID) -> Session | None:
        return self._sessions.get(session_id)

    def add(self, session: Session) -> None:
        self._sessions[session.id] = session

    def delete(self, session_id: uuid.UUID) -> bool:
        return self._sessions.pop(session_id, None) is not None

@lru_cache
def get_session_store() -> SessionStore:
    return SessionStore()