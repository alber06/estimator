"""Manual S08 trace: embed transcript 02_ambiguous + POST /search top-5.

Embeds via the same module the service uses
(``app.generation.rag.embedding.embedder.OpenAIEmbedder``). Search goes through
the live HTTP endpoint ``POST /search`` (S08 accepts the transcript as ``query``;
it re-embeds internally — no vector in the payload).

Reproducible (API already up on :8000). Prefer Docker — host ``uv`` may fail
on some macOS/torch combos; avoid ``app.dependencies`` inside the container
(pulls LiteLLM and can OOM):

  cat examples/transcripts/02_ambiguous.txt | docker exec -i estimator \\
    python -c "from pathlib import Path; import sys; Path('/tmp/02_ambiguous.txt').write_text(sys.stdin.read())"
  docker exec -w /app -e PYTHONPATH=/app estimator \\
    python scripts/trace_s08_ambiguous.py /tmp/02_ambiguous.txt

From the host (if the venv resolves):

  set -a && source .env && set +a
  uv run python scripts/trace_s08_ambiguous.py examples/transcripts/02_ambiguous.txt
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import httpx
from openai import OpenAI

from app.generation.rag.embedding.embedder import OpenAIEmbedder

DEFAULT_TRANSCRIPT = Path("examples/transcripts/02_ambiguous.txt")
SEARCH_URL = os.environ.get("SEARCH_URL", "http://127.0.0.1:8000/search")
MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
K = 5


def main() -> None:
    transcript_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TRANSCRIPT
    transcript = transcript_path.read_text(encoding="utf-8")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY missing")

    embedder = OpenAIEmbedder(client=OpenAI(api_key=api_key), model=MODEL)
    vector = embedder.embed_one(transcript)
    dim = len(vector)
    norm = math.sqrt(sum(x * x for x in vector))
    print("=== EMBED ===")
    print(
        json.dumps(
            {
                "module": "app.generation.rag.embedding.embedder.OpenAIEmbedder",
                "model": MODEL,
                "dimensions": dim,
                "first_component": vector[0],
                "last_component": vector[-1],
                "l2_norm": norm,
                "chars": len(transcript),
            },
            indent=2,
        )
    )

    payload = {"query": transcript, "k": K}
    print("\n=== SEARCH request ===")
    print(
        json.dumps(
            {
                "url": SEARCH_URL,
                "payload": {"query": "<transcript>", "k": K, "query_chars": len(transcript)},
            },
            indent=2,
        )
    )

    with httpx.Client(timeout=60.0) as client:
        response = client.post(SEARCH_URL, json=payload)
    print(f"\n=== SEARCH status {response.status_code} ===")
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
