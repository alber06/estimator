"""Jinja2 loader for versioned prompt templates.

The on-disk layout is ``app/prompts/<use_case>/<version>/<role>.j2``. Versioning
is required from day one: switching prompts becomes a string change at the
call site (``version="v2"``), not a code refactor.
"""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.schemas.estimation import (
    DetailLevel,
    EstimationRequest,
    EstimationResult,
    OutputFormat,
    ProjectType,
)
from app.schemas.session import ProjectMetadata

_BASE_DIR = Path(__file__).resolve().parent

_env = Environment(
    loader=FileSystemLoader(_BASE_DIR),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
    keep_trailing_newline=True,
)


def render_estimation_prompt(
    request: EstimationRequest,
    version: str = "v1",
) -> tuple[str, str]:
    """Render the system and user prompts for the estimation use case.

    Returns:
        A tuple ``(system_prompt, user_prompt)`` ready to be sent to the LLM
        as separate ``role: "system"`` and ``role: "user"`` messages.
    """
    context = {
        "description": request.description,
        "project_type": request.project_type.value,
        "detail_level": request.detail_level.value,
        "output_format": request.output_format.value,
    }
    system = _env.get_template(f"estimation/{version}/system.j2").render(**context)
    user = _env.get_template(f"estimation/{version}/user.j2").render(**context)
    return system, user


def render_conversation_prompt(
    *,
    transcript: str,
    project_type: ProjectType,
    detail_level: DetailLevel,
    output_format: OutputFormat,
    project_metadata: ProjectMetadata | None = None,
    version: str = "v2",
) -> tuple[str, str]:
    """Render system/user prompts for session-scoped conversation estimation.

    Returns:
        A tuple ``(system_prompt, user_prompt)`` ready to be sent to the LLM
        as separate ``role: "system"`` and ``role: "user"`` messages.
    """
    context = {
        "description": transcript,
        "project_type": project_type.value,
        "detail_level": detail_level.value,
        "output_format": output_format.value,
        "project_metadata": project_metadata,
    }
    system = _env.get_template(f"estimation/{version}/system.j2").render(**context)
    user = _env.get_template(f"estimation/{version}/user.j2").render(**context)
    return system, user


def render_extract_metadata_prompt(
    *,
    transcript: str,
    estimation: EstimationResult,
    existing_metadata: ProjectMetadata | None = None,
    version: str = "v1",
) -> tuple[str, str]:
    """Render system/user prompts for project metadata extraction.

    Returns:
        A tuple ``(system_prompt, user_prompt)`` ready to be sent to the LLM
        as separate ``role: "system"`` and ``role: "user"`` messages.
    """
    context = {
        "transcript": transcript,
        "estimation_json": json.dumps(
            estimation.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ),
        "existing_metadata": existing_metadata,
    }
    system = _env.get_template(f"extract_prompt/{version}/system.j2").render(**context)
    user = _env.get_template(f"extract_prompt/{version}/user.j2").render(**context)
    return system, user
