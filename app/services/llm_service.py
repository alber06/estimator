import time
from dataclasses import dataclass
from typing import Literal

import structlog
from litellm import Router

from app.config import get_settings
from app.context.examples import format_examples_for_prompt, select_examples
from app.schemas.estimation import ExampleFormat, PreprocessingMode

log = structlog.get_logger()

DEFAULT_MAX_TOKENS = 4000
EXTRACTION_MAX_TOKENS = 1500


class LLMServiceError(Exception):
    """Raised when the LLM provider call fails."""


# ---------------------------------------------------------------------------
# Prompt building blocks
#
# The two ACTIVE_OUTPUT_PROMPT variants live side by side so the instructor
# can switch between them in the live session (Block 3.4) by editing the
# ACTIVE_OUTPUT_PROMPT assignment below. Uvicorn `--reload` picks up the
# change automatically.
# ---------------------------------------------------------------------------

PROMPT_OUTPUT_BASIC = "Generate an estimation for the project described above."

PROMPT_OUTPUT_STRUCTURED = """\
Generate the estimation with this exact structure:

## Project summary
[2-3 sentences describing the project scope and goals]

## Task breakdown
| Task | Hours | Cost (EUR) |
[one row per task; cost = hours * 62.50 EUR for developer tasks]

## Totals
- Total hours: [number]
- Total cost: [number] EUR
- Recommended team: [composition]
- Estimated duration: [weeks]

## Risks and assumptions
- [3-5 bullet points covering technical risks, scope assumptions, and external dependencies]
"""

# >>> Block 3.4 live switch: change the right-hand side to PROMPT_OUTPUT_STRUCTURED
ACTIVE_OUTPUT_PROMPT = PROMPT_OUTPUT_BASIC


INLINE_CLEANING_BLOCK = """\
The transcription you receive is from a real meeting and may contain:
- Informal small talk you must ignore
- Implicit requirements you must surface explicitly
- Contradictions where you must trust the most recent statement
- Non-technical jargon you must interpret

Extract ONLY the functional and technical requirements relevant to the estimation."""


EXTRACTION_SYSTEM_PROMPT = (
    "You are an analyst. Read the meeting transcription and produce a clean, "
    "deduplicated bullet list of functional requirements, non-functional "
    "requirements, integrations, constraints and explicit deadlines. Ignore "
    "fillers, divagations and off-topic remarks. Output Markdown only."
)


@dataclass
class GenerationOptions:
    """Per-request knobs that drive prompt construction and the LLM call."""

    preprocessing: PreprocessingMode = "none"
    example_format: ExampleFormat = "markdown"
    num_examples: int = 3
    use_examples: bool = True
    model: str | None = None
    max_tokens: int = DEFAULT_MAX_TOKENS
    thinking_budget: int | None = None


@dataclass
class SystemPromptParts:
    """Decomposed system prompt sections for debug UIs and assembly."""

    role: str
    cleaning_block: str
    rates: str
    output_spec: str
    examples_block: str

    @property
    def system_prompt_without_examples(self) -> str:
        sections = [self.role, self.cleaning_block, self.rates, self.output_spec]
        return "\n\n".join(s for s in sections if s)

    @property
    def full_system_prompt(self) -> str:
        sections = [
            self.role,
            self.cleaning_block,
            self.rates,
            self.output_spec,
            self.examples_block,
        ]
        return "\n\n".join(s for s in sections if s)


@dataclass
class StreamPromptInfo:
    """Prompt context surfaced before the LLM response streams."""

    system_prompt_without_examples: str
    examples_block: str


@dataclass
class StreamMetrics:
    """Base metrics for the estimation LLM call."""

    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int


@dataclass
class StreamEvent:
    """Tagged event emitted by ``generate_estimation_stream``."""

    kind: Literal["metadata", "delta", "done"]
    text: str | None = None
    prompt_info: StreamPromptInfo | None = None
    metrics: StreamMetrics | None = None


# ---------------------------------------------------------------------------
# System prompt construction
# ---------------------------------------------------------------------------


def build_system_prompt_parts(
    example_format: ExampleFormat = "markdown",
    num_examples: int = 3,
    use_examples: bool = True,
    inline_cleaning: bool = False,
) -> SystemPromptParts:
    """Build decomposed system prompt sections."""
    role = (
        "You are a senior software consultant with 15+ years of experience in project "
        "estimation. Your task is to produce a detailed software project estimation based "
        "on a meeting transcription provided by the user."
    )
    rates = (
        "Use a developer rate of approximately 62.50 EUR/hour (500 EUR/day) and a designer "
        "rate of approximately 50 EUR/hour (400 EUR/day). Provide realistic, well-justified "
        "numbers."
    )

    examples_block = ""
    if use_examples and num_examples > 0:
        rendered = format_examples_for_prompt(select_examples(num_examples), example_format)
        if rendered:
            examples_block = (
                "Below are reference estimations from previous projects. Use them as a guide "
                "for structure, level of detail, and realistic pricing. Adapt the content to "
                "match the specific project described in the transcription.\n\n"
                + rendered
            )

    cleaning_block = INLINE_CLEANING_BLOCK if inline_cleaning else ""

    return SystemPromptParts(
        role=role,
        cleaning_block=cleaning_block,
        rates=rates,
        output_spec=ACTIVE_OUTPUT_PROMPT,
        examples_block=examples_block,
    )


def build_system_prompt(
    example_format: ExampleFormat = "markdown",
    num_examples: int = 3,
    use_examples: bool = True,
    inline_cleaning: bool = False,
) -> str:
    """Assemble the system prompt with role, rates, output spec and (optionally) examples."""
    return build_system_prompt_parts(
        example_format=example_format,
        num_examples=num_examples,
        use_examples=use_examples,
        inline_cleaning=inline_cleaning,
    ).full_system_prompt


# ---------------------------------------------------------------------------
# Two-phase preprocessing (phase 1: requirement extraction)
# ---------------------------------------------------------------------------


def extract_requirements(
    transcription: str,
    opts: GenerationOptions,
) -> tuple[str, dict]:
    """Run the cheap phase-1 LLM call that turns a raw transcription into clean requirements.

    Returns (requirements_text, usage_dict) where usage_dict has keys
    'input' and 'output' (token counts) for downstream accounting.
    """
    settings = get_settings()
    model = opts.model or settings.LLM_MODEL

    log.info("extracting_requirements", provider=settings.LLM_PROVIDER, model=model)

    if settings.LLM_PROVIDER == "openai":
        result = _call_openai(
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": transcription},
            ],
            model=model,
            max_tokens=EXTRACTION_MAX_TOKENS,
        )
    else:
        result = _call_anthropic(
            system=EXTRACTION_SYSTEM_PROMPT,
            user_message=transcription,
            model=model,
            max_tokens=EXTRACTION_MAX_TOKENS,
            thinking_budget=None,
        )

    return result["estimation"], {
        "input": result["usage"]["input_tokens"],
        "output": result["usage"]["output_tokens"],
    }


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def generate_estimation(
    transcription: str,
    opts: GenerationOptions | None = None,
) -> dict:
    """Generate a software estimation from a meeting transcription using the configured LLM."""
    opts = opts or GenerationOptions()
    settings = get_settings()

    t0 = time.perf_counter()

    prep_usage = {"input": 0, "output": 0}
    extracted_requirements: str | None = None
    user_input = transcription

    if opts.preprocessing == "two_phase":
        extracted_requirements, prep_usage = extract_requirements(transcription, opts)
        user_input = extracted_requirements

    system_prompt = build_system_prompt(
        example_format=opts.example_format,
        num_examples=opts.num_examples,
        use_examples=opts.use_examples,
        inline_cleaning=(opts.preprocessing == "inline_cleaning"),
    )

    model = opts.model or settings.LLM_MODEL

    log.info(
        "generating_estimation",
        provider=settings.LLM_PROVIDER,
        model=model,
        preprocessing=opts.preprocessing,
        example_format=opts.example_format,
        num_examples=opts.num_examples,
        use_examples=opts.use_examples,
        max_tokens=opts.max_tokens,
        thinking_budget=opts.thinking_budget,
    )

    try:
        if settings.LLM_PROVIDER == "openai":
            if opts.thinking_budget is not None:
                log.warning("thinking_budget_ignored_for_provider", provider="openai")
            result = _call_openai(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input},
                ],
                model=model,
                max_tokens=opts.max_tokens,
            )
        else:
            result = _call_anthropic(
                system=system_prompt,
                user_message=user_input,
                model=model,
                max_tokens=opts.max_tokens,
                thinking_budget=opts.thinking_budget,
            )
    except LLMServiceError:
        raise
    except Exception as exc:
        log.error("llm_call_failed", error=str(exc), provider=settings.LLM_PROVIDER)
        raise LLMServiceError(f"LLM call failed: {exc}") from exc

    result["usage"]["preprocessing_input_tokens"] = prep_usage["input"]
    result["usage"]["preprocessing_output_tokens"] = prep_usage["output"]
    result["preprocessing"] = opts.preprocessing
    result["extracted_requirements"] = extracted_requirements
    result["latency_ms"] = int((time.perf_counter() - t0) * 1000)

    return result

def _usage_from_stream_chunk(chunk) -> dict | None:
    """Extract token usage from a LiteLLM streaming chunk when the provider sends it."""
    usage = getattr(chunk, "usage", None)
    if usage is None and hasattr(chunk, "model_dump"):
        usage = chunk.model_dump().get("usage")

    if not usage:
        return None

    if isinstance(usage, dict):
        input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
        output_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
    else:
        input_tokens = getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", None)
        output_tokens = (
            getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", None)
        )

    if input_tokens is None and output_tokens is None:
        return None

    input_tokens = input_tokens or 0
    output_tokens = output_tokens or 0
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def generate_estimation_stream(
    transcription: str,
    opts: GenerationOptions | None = None,
):
    """Stream estimation events: metadata, text deltas, then call metrics."""
    opts = opts or GenerationOptions()
    settings = get_settings()
    t0 = time.perf_counter()

    prep_usage = {"input": 0, "output": 0}
    extracted_requirements: str | None = None
    user_input = transcription

    if opts.preprocessing == "two_phase":
        extracted_requirements, prep_usage = extract_requirements(transcription, opts)
        user_input = extracted_requirements

    prompt_parts = build_system_prompt_parts(
        example_format=opts.example_format,
        num_examples=opts.num_examples,
        use_examples=opts.use_examples,
        inline_cleaning=(opts.preprocessing == "inline_cleaning"),
    )
    system_prompt = prompt_parts.full_system_prompt

    model = opts.model or settings.LLM_MODEL

    yield StreamEvent(
        kind="metadata",
        prompt_info=StreamPromptInfo(
            system_prompt_without_examples=prompt_parts.system_prompt_without_examples,
            examples_block=prompt_parts.examples_block,
        ),
    )

    log.info(
        "generating_estimation",
        provider=settings.LLM_PROVIDER,
        model=model,
        preprocessing=opts.preprocessing,
        example_format=opts.example_format,
        num_examples=opts.num_examples,
        use_examples=opts.use_examples,
        max_tokens=opts.max_tokens,
        thinking_budget=opts.thinking_budget,
    )

    router = Router(
        model_list=[
            {
                "model_name": "estimator",
                "litellm_params": {
                    "model": "gpt-4o-mini",
                    "api_key": settings.OPENAI_API_KEY,
                },
            },
            {
                "model_name": "estimator",
                "litellm_params": {
                    "model": "claude-haiku-4-5",
                    "api_key": settings.ANTHROPIC_API_KEY,
                },
            },
        ],
        fallbacks=[{"estimator": ["estimator"]}],
        num_retries=2,
    )

    resolved_model = model
    usage: dict | None = None

    try:
        response = router.completion(
            model="estimator",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            max_tokens=opts.max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )

        for chunk in response:
            if getattr(chunk, "model", None):
                resolved_model = chunk.model

            choice = chunk.choices[0]
            delta = choice.delta.content or ""
            if delta:
                yield StreamEvent(kind="delta", text=delta)

            chunk_usage = _usage_from_stream_chunk(chunk)
            if chunk_usage:
                usage = chunk_usage
    except LLMServiceError:
        raise
    except Exception as exc:
        log.error("llm_call_failed", error=str(exc), provider=settings.LLM_PROVIDER)
        raise LLMServiceError(f"LLM call failed: {exc}") from exc

    input_tokens = usage["input_tokens"] if usage else None
    output_tokens = usage["output_tokens"] if usage else None

    yield StreamEvent(
        kind="done",
        metrics=StreamMetrics(
            model=resolved_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=int((time.perf_counter() - t0) * 1000),
        ),
    )

# ---------------------------------------------------------------------------
# Provider wrappers
# ---------------------------------------------------------------------------


def _call_openai(messages: list[dict], model: str, max_tokens: int) -> dict:
    """Send a chat completion request to the OpenAI API."""
    from openai import OpenAI

    settings = get_settings()
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )

    usage = response.usage
    finish_reason = response.choices[0].finish_reason or "stop"

    log.info(
        "llm_response_received",
        provider="openai",
        model=response.model,
        finish_reason=finish_reason,
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
    )

    return {
        "estimation": response.choices[0].message.content,
        "model": response.model,
        "provider": "openai",
        "finish_reason": finish_reason,
        "usage": {
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        },
    }


def _call_anthropic(
    system: str,
    user_message: str,
    model: str,
    max_tokens: int,
    thinking_budget: int | None,
) -> dict:
    """Send a message request to the Anthropic API."""
    from anthropic import Anthropic

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_message}],
    }
    if thinking_budget is not None:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        # Anthropic requires max_tokens > thinking_budget; pad with headroom for the answer.
        kwargs["max_tokens"] = max(max_tokens, thinking_budget + 1024)

    response = client.messages.create(**kwargs)

    finish_reason = response.stop_reason or "stop"

    # When extended thinking is enabled the response contains thinking blocks
    # before the final text block. Pick the first text block.
    estimation_text = next(
        (block.text for block in response.content if getattr(block, "type", None) == "text"),
        "",
    )

    log.info(
        "llm_response_received",
        provider="anthropic",
        model=response.model,
        finish_reason=finish_reason,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )

    return {
        "estimation": estimation_text,
        "model": response.model,
        "provider": "anthropic",
        "finish_reason": finish_reason,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        },
    }
