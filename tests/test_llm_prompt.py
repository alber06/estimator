from types import SimpleNamespace

from app.services.llm_service import (
    _conversation_to_text,
    _resolve_stream_input,
    _usage_from_stream_chunk,
    build_system_prompt,
)


def test_build_system_prompt_includes_examples():
    with_examples = build_system_prompt(use_examples=True, num_examples=2)
    without_examples = build_system_prompt(use_examples=False)
    assert "reference estimations" in with_examples
    assert "reference estimations" not in without_examples
    assert len(with_examples) > len(without_examples)


def test_build_system_prompt_includes_rates():
    prompt = build_system_prompt()
    assert "62.50 EUR/hour" in prompt


def test_usage_from_stream_chunk_openai_shape():
    chunk = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))
    assert _usage_from_stream_chunk(chunk) == {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
    }


def test_usage_from_stream_chunk_anthropic_shape():
    chunk = SimpleNamespace(usage=SimpleNamespace(input_tokens=8, output_tokens=3))
    assert _usage_from_stream_chunk(chunk) == {
        "input_tokens": 8,
        "output_tokens": 3,
        "total_tokens": 11,
    }


def test_usage_from_stream_chunk_dict_shape():
    chunk = SimpleNamespace(usage={"prompt_tokens": 12, "completion_tokens": 4})
    assert _usage_from_stream_chunk(chunk) == {
        "input_tokens": 12,
        "output_tokens": 4,
        "total_tokens": 16,
    }


def test_resolve_stream_input_from_transcription():
    conversation, source_text = _resolve_stream_input("Meeting notes here", None)
    assert conversation == [{"role": "user", "content": "Meeting notes here"}]
    assert source_text == "Meeting notes here"


def test_resolve_stream_input_from_messages():
    messages = [
        {"role": "user", "content": "Necesito una app de inventario"},
        {"role": "assistant", "content": "¿Cuántos usuarios tendrá?"},
        {"role": "user", "content": "Unos 50 usuarios"},
    ]
    conversation, source_text = _resolve_stream_input(None, messages)
    assert conversation == messages
    assert "User: Necesito una app de inventario" in source_text
    assert "Assistant: ¿Cuántos usuarios tendrá?" in source_text


def test_conversation_to_text_formats_roles():
    text = _conversation_to_text(
        [
            {"role": "user", "content": "Hola"},
            {"role": "assistant", "content": "Respuesta"},
        ]
    )
    assert text == "User: Hola\n\nAssistant: Respuesta"
