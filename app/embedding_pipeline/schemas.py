from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field



class BudgetComponent(BaseModel):
    """A single component of a budget."""
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1024)
    estimated_hours: int = Field(ge=0, le=2000)
    complexity: Literal["low", "medium", "high"] = Field(default="medium")
    dependencies: list[str] = Field(default_factory=list)

class ClientMetadata(BaseModel):
    """Metadata about a client."""
    name: str = Field(min_length=1, max_length=128)
    sector: Literal["finance", "ecommerce", "healthcare", "industrial", "other"] = Field(default="other")
    country: str = Field(min_length=1, max_length=128)

class Budget(BaseModel):
    """A budget for a project."""
    budget_id: str = Field(min_length=1, max_length=128)
    client_metadata: ClientMetadata = Field(default_factory=ClientMetadata)
    project_summary: str = Field(min_length=1, max_length=1024)
    main_technology: str = Field(min_length=1, max_length=128)
    year: int = Field(ge=1980, le=2100)

class Chunk(BaseModel):
    """A chunk from a budget."""
    chunk_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=1024)
    metadata: dict[str, any] = Field(default_factory=dict)
    token_count: int = Field(ge=0)

class EmbeddedChunk(Chunk):
    """An embedded chunk from a budget."""
    embedding: list[float] = Field(min_length=1, max_length=1536)

class IngestRequest(BaseModel):
    """A request to ingest a budget."""
    budgets: list[Budget] = Field(min_length=1)

class IngestStats(BaseModel):
    """Statistics about the ingestion process."""
    total_budgets: int = Field(ge=0)
    total_chunks: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0)

class IngestResponse(BaseModel):
    """A response from ingesting a budget."""
    chunks: list[EmbeddedChunk] = Field(min_length=1)
    stats: IngestStats = Field(default_factory=IngestStats)