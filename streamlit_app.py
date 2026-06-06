import streamlit as st

from app.services.llm_service import (
    LLMServiceError,
    StreamMetrics,
    StreamPromptInfo,
    generate_estimation_stream,
)

if "messages" not in st.session_state:
    st.session_state.messages = []

if "prompt_info" not in st.session_state:
    st.session_state.prompt_info = None

if "last_metrics" not in st.session_state:
    st.session_state.last_metrics = None


def _render_sidebar_content(
    prompt_area: st.delta_generator.DeltaGenerator,
    metrics_area: st.delta_generator.DeltaGenerator,
    *,
    prompt_info: StreamPromptInfo | None = None,
    metrics: StreamMetrics | None = None,
) -> None:
    prompt_info = prompt_info if prompt_info is not None else st.session_state.prompt_info
    metrics = metrics if metrics is not None else st.session_state.last_metrics

    if prompt_info:
        with prompt_area.container():
            st.markdown("**System prompt**")
            st.code(prompt_info.system_prompt, language="markdown")
    else:
        prompt_area.caption("System prompt will appear after the first request.")

    if metrics:
        input_tokens = metrics.input_tokens if metrics.input_tokens is not None else "—"
        output_tokens = metrics.output_tokens if metrics.output_tokens is not None else "—"
        with metrics_area.container():
            st.markdown("**Metrics**")
            st.markdown(f"- **Model:** `{metrics.model}`")
            st.markdown(f"- **Input tokens:** {input_tokens}")
            st.markdown(f"- **Output tokens:** {output_tokens}")
            st.markdown(f"- **Latency:** {metrics.latency_ms} ms")
    else:
        metrics_area.caption("Metrics will appear after the response completes.")


def _on_prompt_info(prompt_info: StreamPromptInfo) -> None:
    st.session_state.prompt_info = prompt_info
    _render_sidebar_content(prompt_area, metrics_area, prompt_info=prompt_info)


def _on_metrics(metrics: StreamMetrics) -> None:
    st.session_state.last_metrics = metrics
    _render_sidebar_content(prompt_area, metrics_area, metrics=metrics)


def _text_only_stream(events):
    """Filter StreamEvents: update sidebar hooks, yield only text for write_stream."""
    for event in events:
        if event.kind == "metadata" and event.prompt_info:
            _on_prompt_info(event.prompt_info)
        elif event.kind == "delta" and event.text:
            yield event.text
        elif event.kind == "done" and event.metrics:
            _on_metrics(event.metrics)


with st.sidebar:
    st.header("Prompt & metrics")
    prompt_area = st.empty()
    metrics_area = st.empty()
    _render_sidebar_content(prompt_area, metrics_area)

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Escribe tu mensaje..."):
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        try:
            events = generate_estimation_stream(messages=list(st.session_state.messages))
            stream = _text_only_stream(events)
            response = st.write_stream(stream)
            st.session_state.messages.append({"role": "assistant", "content": response})
        except LLMServiceError as exc:
            st.error(f"Error: {exc}")
