import uuid

from typing import Literal
from pydantic import BaseModel, Field

MessageRole = Literal["user", "assistant"]


class Message(BaseModel):
    role: MessageRole
    content: str


class ProjectMetadata(BaseModel):
    """Facts extracted or agreed during the conversation."""

    project_name: str = ""
    assumed_team_size: int | None = None
    mentioned_technologies: list[str] = Field(default_factory=list)
    agreed_scope: str = ""

    def has_content(self) -> bool:
        return bool(
            self.project_name
            or self.assumed_team_size is not None
            or self.mentioned_technologies
            or self.agreed_scope
        )

class SessionResponse(BaseModel):
    session_id: uuid.UUID = Field(description="The ID of the session.")