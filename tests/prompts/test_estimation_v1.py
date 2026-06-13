import re

from app.prompts.loader import render_estimation_prompt
from app.schemas.estimation import EstimationRequest, ProjectType, DetailLevel, OutputFormat
from streamlit_app import OUTPUT_FORMAT_LABELS, detail_level, output_format


def _get_request(**args) -> EstimationRequest:
    request = {
        "description": "We need a small game with auth, contacts and roles. MVP seven weeks.",
        "project_type": ProjectType.MOBILE_APP,
        "detail_level": DetailLevel.MEDIUM,
        "output_format": OutputFormat.PHASES_TABLE
    }

    request.update(**args)
    return EstimationRequest(**request)

def test_render_includes_parts():
    request = _get_request()

    user_prompt, system_prompt = render_estimation_prompt(request)

    start_description = user_prompt.find("<project_description>")
    end_description = user_prompt.find("</project_description>")
    assert start_description != -1 and end_description != -1
    assert request.description in user_prompt[start_description:end_description]

    start_project_type = system_prompt.find("<project_type>")
    end_project_type = system_prompt.find("</project_type>")
    assert start_project_type != -1 and end_project_type != -1
    assert request.project_type.value in system_prompt[start_project_type:end_project_type]

    start_detail_level = system_prompt.find("<detail_level>")
    end_detail_level = system_prompt.find("</detail_level>")
    assert start_detail_level != -1 and end_detail_level != -1
    assert request.detail_level.value in system_prompt[start_detail_level:end_detail_level]

    start_output_format = system_prompt.find("<output_format>")
    end_output_format = system_prompt.find("</output_format>")
    assert start_output_format != -1 and end_output_format != -1
    assert request.output_format.value in system_prompt[start_output_format:end_output_format]

def test_render_produces_valid_prompt():
    request = _get_request()

    _, system_prompt = render_estimation_prompt(request)

    start_output_format = system_prompt.find("<output_format>")
    end_output_format = system_prompt.find("</output_format>")
    assert start_output_format != -1 and end_output_format != -1
    assert OutputFormat.PHASES_TABLE.value in system_prompt[start_output_format:end_output_format]
    assert OutputFormat.NARRATIVE.value not in system_prompt[start_output_format:end_output_format]

def test_detailed_prompt_content():
    request = _get_request(detail_level=DetailLevel.DETAILED)
    _, system_prompt = render_estimation_prompt(request)
    assert "list assumptions per phase" in system_prompt

    request = _get_request(detail_level=DetailLevel.SUMMARY)
    _, system_prompt = render_estimation_prompt(request)
    assert "list assumptions per phase" not in system_prompt
