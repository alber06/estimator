from types import SimpleNamespace

from app.services.llm_service import (
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
