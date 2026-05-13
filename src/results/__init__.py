"""Per-run results export — durable on-disk artifact for cross-run comparison."""
from src.results.writer import ResultsWriter, compose_run_id

__all__ = ["ResultsWriter", "compose_run_id"]
