from enum import Enum

from pydantic import BaseModel, Field

class ProjectType(str, Enum):
    MOBILE_APP = "mobile_app"
    WEB_SAAS = "web_saas"
    INTERNAL_TOOL = "internal_tool"
    DATA_PIPELINE = "data_pipeline"

class DetailLevel(str, Enum):
    SUMMARY = "summary"
    MEDIUM = "medium"
    DETAILED = "detailed"

class OutputFormat(str, Enum):
    PHASES_TABLE = "phases_table"
    LINE_ITEMS = "line_items"
    NARRATIVE = "narrative"

class PromptVersion(str, Enum):
    V1 = "v1"
    V2 = "v2"

class EstimationRequest(BaseModel):
    """Incoming request containing a project description to estimate."""

    description: str = Field(..., min_length=50, max_length=2000, description="Project description text")

    project_type: ProjectType = Field(..., description="Project type")
    detail_level: DetailLevel = Field(..., description="Detail level")
    output_format: OutputFormat = Field(..., description="Output format")


class EstimationResponse(BaseModel):
    """Response containing the generated estimation and metadata."""

    estimation: str = Field(..., description="Generated software estimation in markdown")
    prompt_version: str = Field(..., description="Prompt version used")

