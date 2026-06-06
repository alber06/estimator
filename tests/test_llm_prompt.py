from types import SimpleNamespace

import pytest

from app.services.llm_service import (
    LLMServiceError,
    _conversation_to_text,
    _normalize_conversation,
    _resolve_stream_input,
    _usage_from_stream_chunk,
    build_system_prompt,
    build_system_prompt_parts,
)


def test_build_system_prompt_parts_matches_legacy():
    parts = build_system_prompt_parts()
    assert parts.full_system_prompt == build_system_prompt()


def test_examples_block_is_separate_from_core_prompt():
    parts = build_system_prompt_parts(use_examples=True, num_examples=2)
    assert parts.examples_block
    assert parts.examples_block not in parts.system_prompt_without_examples
    assert parts.examples_block in parts.full_system_prompt


def test_no_examples_when_disabled():
    parts = build_system_prompt_parts(use_examples=False)
    assert parts.examples_block == ""
    assert parts.full_system_prompt == parts.system_prompt_without_examples


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


def test_normalize_conversation_rejects_system_role():
    with pytest.raises(LLMServiceError, match="Unsupported conversation role"):
        _normalize_conversation([{"role": "system", "content": "secret"}])


def test_conversation_to_text_formats_roles():
    text = _conversation_to_text(
        [
            {"role": "user", "content": "Hola"},
            {"role": "assistant", "content": "Respuesta"},
        ]
    )
    assert text == "User: Hola\n\nAssistant: Respuesta"
