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

class SessionResponse(BaseModel):
    session_id: uuid.UUID = Field(description="The ID of the session.")