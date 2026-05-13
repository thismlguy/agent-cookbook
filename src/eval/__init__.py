"""Evaluation — LLM-as-judge over full transcripts."""
from src.eval.judge import judge
from src.eval.schemas import AssertionResult, JudgeResult

__all__ = ["AssertionResult", "JudgeResult", "judge"]
