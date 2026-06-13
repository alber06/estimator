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

class ReferenceProject(BaseModel):
    """Reference project for estimation."""

    description: str = Field(..., description="Description of the reference project")
    estimated_cost: float = Field(..., description="Estimated cost of the reference project in euros")
    estimated_time: float = Field(..., description="Estimated time to complete the reference project in hours")
    estimated_team: list[str] = Field(..., description="Estimated team size required for the reference project")

class EstimationRequest(BaseModel):
    """Incoming request containing a project description to estimate."""

    description: str = Field(..., min_length=50, max_length=2000, description="Project description text")

    project_type: ProjectType = Field(..., description="Project type")
    detail_level: DetailLevel = Field(..., description="Detail level")
    output_format: OutputFormat = Field(..., description="Output format")
    reference_projects: list[ReferenceProject] | None = Field(
        default=None,
        description="Optional reference projects to guide the estimation",
    )


class EstimationResponse(BaseModel):
    """Response containing the generated estimation and metadata."""

    estimation: str = Field(..., description="Generated software estimation in markdown")
    prompt_version: str = Field(..., description="Prompt version used")

