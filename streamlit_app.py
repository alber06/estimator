"""Streamlit chat UI for the estimator.

Streamlit acts as an HTTP client of the FastAPI service: it POSTs to
``/api/v1/estimate/stream`` and renders the SSE chunks live with
``st.write_stream``. The endpoint URL is read from ``ESTIMATOR_API_BASE_URL``
(loaded from the same ``.env`` as the API), so the same UI works against a
local uvicorn or against docker-compose.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import httpx
import streamlit as st
from dotenv import load_dotenv
from app.schemas.estimation import (
    DetailLevel,
    EstimationRequest,
    EstimationResponse,
    OutputFormat,
    ProjectType,
)
load_dotenv()

API_BASE_URL = os.getenv("ESTIMATOR_API_BASE_URL", "http://localhost:8000")
ESTIMATE_ENDPOINT = f"{API_BASE_URL.rstrip('/')}/api/v1/estimate"
STREAM_ENDPOINT = f"{API_BASE_URL.rstrip('/')}/api/v1/estimate/stream"

PROJECT_TYPE_LABELS: dict[ProjectType, str] = {
    ProjectType.MOBILE_APP: "Mobile app",
    ProjectType.WEB_SAAS: "Web SaaS",
    ProjectType.INTERNAL_TOOL: "Internal tool",
    ProjectType.DATA_PIPELINE: "Data pipeline",
}

DETAIL_LEVEL_LABELS: dict[DetailLevel, str] = {
    DetailLevel.SUMMARY: "Summary",
    DetailLevel.MEDIUM: "Medium",
    DetailLevel.DETAILED: "Detailed",
}

OUTPUT_FORMAT_LABELS: dict[OutputFormat, str] = {
    OutputFormat.PHASES_TABLE: "Phases table",
    OutputFormat.LINE_ITEMS: "Line items",
    OutputFormat.NARRATIVE: "Narrative",
}

st.set_page_config(page_title="Software Estimator", page_icon="📊")
st.title("Software Estimator")
st.caption(
    "Enter project information. The answer streams token by token from the "
    "FastAPI service over Server-Sent Events."
)

if "estimating" not in st.session_state:
    st.session_state.estimating = False
if "estimation" not in st.session_state:
    st.session_state.estimation = None
if "estimation_error" not in st.session_state:
    st.session_state.estimation_error = None


def fetch_estimation(payload: EstimationRequest) -> EstimationResponse:
    """POST to the estimate endpoint and return the full JSON response."""
    response = httpx.post(
        ESTIMATE_ENDPOINT,
        json=payload.model_dump(mode="json"),
        timeout=httpx.Timeout(120.0, connect=10.0),
    )
    response.raise_for_status()
    return EstimationResponse.model_validate(response.json())


def stream_estimation(payload: EstimationRequest) -> Iterator[str]:
    """POST to the SSE endpoint and yield text chunks as they arrive.

    Per the SSE spec, a single message with internal newlines is serialised as
    multiple ``data:`` lines, and the client must join them with ``\\n`` to
    reconstruct the original payload. A blank line terminates the message.
    """
    with httpx.stream(
        "POST",
        STREAM_ENDPOINT,
        json=payload.model_dump(mode="json"),
        timeout=httpx.Timeout(120.0, connect=10.0),
        headers={"Accept": "text/event-stream"},
    ) as response:
        response.raise_for_status()
        current_event = "token"
        data_lines: list[str] = []
        for raw_line in response.iter_lines():
            if raw_line == "":
                if data_lines:
                    payload_text = "\n".join(data_lines)
                    data_lines = []
                    if current_event == "token":
                        yield payload_text
                    elif current_event == "error":
                        yield f"\n\n[error] {payload_text}"
                    elif current_event == "done":
                        return
                current_event = "token"
                continue
            if raw_line.startswith("event:"):
                current_event = raw_line[6:].strip()
            elif raw_line.startswith("data:"):
                # The SSE spec defines exactly one space after `data:` as
                # framing, not payload — preserve any further whitespace.
                data_lines.append(
                    raw_line[6:] if raw_line.startswith("data: ") else raw_line[5:]
                )

with st.form("estimation_form"):
    st.write("Enter estimation data")
    transcription = st.text_area("Transcription")
    project_type = st.selectbox(
        "Project type", 
        options=list[str](PROJECT_TYPE_LABELS.keys()),
        format_func=lambda pt: PROJECT_TYPE_LABELS[pt],
    )
    detail_level = st.selectbox(
        "Detail level", 
        options=list(DETAIL_LEVEL_LABELS.keys()),
        format_func=lambda dl: DETAIL_LEVEL_LABELS[dl],
    )
    output_format = st.selectbox(
        "Output format", 
        options=list(OUTPUT_FORMAT_LABELS.keys()),
        format_func=lambda of: OUTPUT_FORMAT_LABELS[of],
    )

    if st.session_state.estimating:
        st.form_submit_button("Generating...", icon="spinner", disabled=True)
        submitted = False
    else:
        submitted = st.form_submit_button("Submit")

if submitted:
    st.session_state.estimating = True
    st.session_state.estimation = None
    st.session_state.estimation_error = None
    st.session_state.pending_request = EstimationRequest(
        transcription=transcription,
        project_type=project_type,
        detail_level=detail_level,
        output_format=output_format,
    )
    st.rerun()

if st.session_state.estimating:
    try:
        response = fetch_estimation(st.session_state.pending_request)
        st.session_state.estimation = response.estimation
    except httpx.HTTPError as exc:
        st.session_state.estimation_error = (
            f"Could not reach the estimator at `{ESTIMATE_ENDPOINT}`: {exc}"
        )
    finally:
        st.session_state.estimating = False
        st.session_state.pop("pending_request", None)
    st.rerun()

if st.session_state.estimation:
    st.markdown(st.session_state.estimation)
if st.session_state.estimation_error:
    st.error(st.session_state.estimation_error)

with st.sidebar:
    st.header("Service")
    st.code(ESTIMATE_ENDPOINT, language="text")
    primary = os.getenv("PRIMARY_MODEL", "gpt-4o-mini")
    fallback = os.getenv("FALLBACK_MODEL", "claude-haiku-4-5-20251001")
    st.markdown(f"**Primary model:** `{primary}`")
    st.markdown(f"**Fallback model:** `{fallback}`")
    st.markdown(f"**Cache TTL:** `{os.getenv('CACHE_TTL', '86400')}s`")
