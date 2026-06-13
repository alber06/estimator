import hashlib
import json
import structlog

from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.schemas.estimation import EstimationRequest
from app.schemas.estimation import PromptVersion

PROMPTS_DIR = Path(__file__).parent

log = structlog.get_logger()

_env = Environment(
    loader=FileSystemLoader(PROMPTS_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=False,
    undefined=StrictUndefined,
)

def render_estimation_prompt(
    request: EstimationRequest,
    version: PromptVersion = PromptVersion.V1,
) -> tuple[str, str]:
    system = _env.get_template(f"estimation/{version}/system.j2")
    user = _env.get_template(f"estimation/{version}/user.j2")

    digest = hashlib.sha256(json.dumps(request.model_dump(mode="json"), sort_keys=True).encode("utf-8")).hexdigest()
    log.info(
        "Rendering estimation prompt",
        content_digest=digest,
        prompt_version=version,
    )

    context = {
        "project_type": request.project_type.value,
        "detail_level": request.detail_level.value,
        "output_format": request.output_format.value,
        "description": request.description,
        "reference_projects": request.reference_projects,
    }

    return user.render(**context), system.render(**context)