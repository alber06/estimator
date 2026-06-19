"""Session-scoped state for multi-turn estimation conversations.

Conversation history and project metadata are held in memory for the lifetime
of the process. That volatility is deliberate at this stage as it keeps it simple
for us to prototype without adding extra complexity, which will be added at later stages.
"""

import uuid

from app.schemas.session import Message, ProjectMetadata
from pydantic import Field

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

class Session:
    """One conversational estimation context, keyed by ``session_id``."""

    def __init__(
        self,
        id: uuid.UUID = Field(default_factory=uuid.uuid4),
        *,
        project_metadata: ProjectMetadata | None = None,
        conversation_history: ConversationHistory | None = None,
    ) -> None:
        self.id = id
        self.project_metadata = project_metadata or ProjectMetadata()
        self.conversation_history = conversation_history or ConversationHistory()


class SessionStore:
    """``session_id -> Session`` map living in process memory."""

    def __init__(self) -> None:
        self._sessions: dict[uuid.UUID, Session] = {}
    
    def get(self, session_id: uuid.UUID) -> Session:
        return self._sessions.get(session_id)

    def add(self, session: Session) -> None:
        self._sessions[session.id] = session

    def delete(self, session_id: uuid.UUID) -> bool:
        return self._sessions.pop(session_id, None) is not None