
import tiktoken

from app.embedding_pipeline.schemas import Budget, BudgetComponent, Chunk
from typing import Any


class JSONStructuralChunker:
    """A chunker for JSON documents."""
    def __init__(self, model_for_token_count: str = "text-embedding-3-small"):
        self._tokenizer = tiktoken.encoding_for_model(model_for_token_count)

    def chunk(self, budgets: list[Budget]) -> list[Chunk]:
        """Chunks a budget JSON document at the component level.

        Each budget component becomes one chunk. The chunk text combines
        the component's own fields with contextual headers from the parent
        budget (client sector, year, main technology, project summary).
        """

        chunks: list[Chunk] = []
        for budget in budgets:
            chunks.extend(self._chunk_budget(budget))
        return chunks

    def _chunk_budget(self, budget: Budget) -> list[Chunk]:
        """Chunks a single budget at the component level."""
        parent_context = self._build_parent_context(budget)

        return [
            self._build_chunk(component, budget, parent_context)
            for component in budget.components
        ]

    def _build_parent_context(self, budget: Budget) -> str:
        """Builds the parent context for a budget."""
        metadata = budget.client_metadata

        return (
            f"[Project: {budget.project_summary}]\n"
            f"[Client sector: {metadata.sector} | "
            f"Year: {budget.year} | "
            f"Main Technology: {budget.main_technology}]"
        )

    def _build_chunk(self, component: BudgetComponent, budget: Budget, parent_context: str) -> Chunk:
        """Builds a chunk for a single budget component."""

        text = self._render_component_text(component, parent_context)
        return Chunk(
            chunk_id=f"{budget.budget_id}::{component.component_id}",
            text=text,
            metadata=self._build_metadata(component, budget),
            token_count=len(self._tokenizer.encode(text)),
        )
    
    def _render_component_text(self, component: BudgetComponent, parent_context: str) -> str:
        """Renders the text for a single budget component."""

        return (
            f"{parent_context}\n"
            f"Component: {component.component_id}\n"
            f"Description: {component.description}\n"
            f"Tech stack: {', '.join(component.tech_stack)}\n"
            f"Complexity: {component.complexity}\n"
            f"Estimated Hours: {component.estimated_hours}\n"
        )

    def _build_metadata(self, component: BudgetComponent, budget: Budget) -> dict[str, Any]:
        return {
            "budget_id": budget.budget_id,
            "component_id": component.component_id,
            "client_sector": budget.client_metadata.sector,
            "main_technology": budget.main_technology,
            "year": budget.year,
            "complexity": component.complexity,
            "estimated_hours": component.estimated_hours,
        }
