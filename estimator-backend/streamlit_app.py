"""Streamlit form for the estimator.

Streamlit acts as an HTTP client of the conversational session flow: it creates
a session via ``POST /sessions``, submits multipart estimates to
``POST /sessions/{session_id}/estimate``, and renders the structured
``EstimationResult``. The API base URL is read from ``ESTIMATOR_API_BASE_URL``
(loaded from the same ``.env`` as the API), so the same UI works against a
local uvicorn or against docker-compose.
"""

from __future__ import annotations

import os

import httpx
import streamlit as st
from dotenv import load_dotenv

from app.schemas.estimation import DetailLevel, OutputFormat, ProjectType

load_dotenv()

API_BASE_URL = os.getenv("ESTIMATOR_API_BASE_URL", "http://localhost:8000")
SESSIONS_URL = f"{API_BASE_URL.rstrip('/')}/sessions"
HTTP_TIMEOUT = httpx.Timeout(120.0, connect=10.0)
CONTENT_TRUNCATE = 200


def create_session() -> str:
    response = httpx.post(SESSIONS_URL, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()["session_id"]


def ensure_session() -> str:
    if "session_id" not in st.session_state:
        st.session_state.session_id = create_session()
        st.session_state.project_metadata = {}
        st.session_state.messages = []
    return st.session_state.session_id


def render_estimation_result(body: dict) -> None:
    result = body["result"]
    prompt_version = body.get("prompt_version", "?")

    st.markdown(
        f"**Prompt version:** `{prompt_version}` · "
        f"**Confidence:** {result['confidence_pct']}%"
    )
    st.markdown(result["summary"])

    st.subheader("Phases")
    st.dataframe(result["phases"], use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    col1.metric("Total duration (weeks)", result["total_duration_weeks"])
    col2.metric("Total cost (EUR)", f"{result['total_cost_eur']:,}")


def truncate_content(content: str, limit: int = CONTENT_TRUNCATE) -> str:
    if len(content) <= limit:
        return content
    return content[: limit - 1] + "…"


st.set_page_config(page_title="Software Estimator", page_icon="📊")
st.title("Software Estimator")
st.caption(
    "Envía una transcripción (y adjuntos opcionales) para estimar un proyecto de software. "
    "Cada sesión acumula metadata del proyecto e historial de conversación."
)

session_id = ensure_session()

with st.form("estimation_form", clear_on_submit=False):
    transcript = st.text_area(
        "Transcripción",
        height=200,
        placeholder="Describe the project: goals, key features, constraints…",
        help="Between 20 and 2,000 characters.",
    )
    attachments = st.file_uploader(
        "Adjuntos",
        accept_multiple_files=True,
        type=["pdf", "docx"],
    )
    project_type = st.selectbox(
        "Project type",
        options=[t.value for t in ProjectType],
        index=1,
    )
    detail_level = st.radio(
        "Detail level",
        options=[d.value for d in DetailLevel],
        index=1,
        horizontal=True,
    )
    output_format = st.selectbox(
        "Output format",
        options=[f.value for f in OutputFormat],
        index=0,
    )
    submitted = st.form_submit_button("Generar estimación", type="primary")


if submitted:
    if len(transcript.strip()) < 20:
        st.error("The transcript must be at least 20 characters long.")
    else:
        files = [
            ("attachments", (uploaded.name, uploaded.getvalue(), uploaded.type))
            for uploaded in (attachments or [])
        ]
        data = {
            "transcript": transcript.strip(),
            "project_type": project_type,
            "detail_level": detail_level,
            "output_format": output_format,
        }
        estimate_url = f"{SESSIONS_URL}/{session_id}/estimate"
        with st.spinner("Calling the estimator service…"):
            try:
                response = httpx.post(
                    estimate_url,
                    data=data,
                    files=files,
                    timeout=HTTP_TIMEOUT,
                )
                response.raise_for_status()
                body = response.json()
            except httpx.HTTPStatusError as exc:
                st.error(f"Service returned {exc.response.status_code}: {exc.response.text}")
            except httpx.HTTPError as exc:
                st.error(f"Could not reach the estimator at `{estimate_url}`: {exc}")
            else:
                st.session_state.project_metadata = body.get("project_metadata") or {}
                st.session_state.messages = body.get("messages") or []
                st.session_state.last_result = body
                render_estimation_result(body)

if "last_result" in st.session_state and not submitted:
    st.divider()
    st.subheader("Last estimation")
    render_estimation_result(st.session_state.last_result)


with st.sidebar:
    st.header("Sesión")
    st.markdown("**Session ID**")
    st.code(st.session_state.session_id, language="text")

    st.markdown("**Memoria (project_metadata)**")
    st.json(st.session_state.get("project_metadata", {}))

    messages = st.session_state.get("messages", [])
    if not messages:
        st.caption("No messages yet.")
    else:
        for message in messages:
            label = "User" if message["role"] == "user" else "Assistant"
            st.markdown(f"**{label}:** {truncate_content(message['content'])}")

    if st.button("Nueva conversación"):
        st.session_state.session_id = create_session()
        st.session_state.project_metadata = {}
        st.session_state.messages = []
        st.session_state.pop("last_result", None)
        st.rerun()

    st.divider()
    st.header("Service")
    st.code(f"POST {SESSIONS_URL}/{{session_id}}/estimate", language="text")
    primary = os.getenv("PRIMARY_MODEL", "gpt-4o-mini")
    fallback = os.getenv("FALLBACK_MODEL", "claude-haiku-4-5-20251001")
    st.markdown(f"**Primary model:** `{primary}`")
    st.markdown(f"**Fallback model:** `{fallback}`")
    st.markdown(f"**Cache TTL:** `{os.getenv('CACHE_TTL', '86400')}s`")
