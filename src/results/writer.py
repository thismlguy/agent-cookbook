"""Per-run results directory writer.

Each run produces a directory like:

  results/<UTC ts>__<agent>__<provider>__<model>/
    metadata.json
    summary.json
    transcripts/<task_id>.json
    evaluations/<task_id>.json
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.providers.select import parse_spec


def _ts_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe(s: str) -> str:
    return _UNSAFE_RE.sub("-", s).strip("-") or "unknown"


def compose_run_id(agent: str, model_spec: str, ts: str | None = None) -> str:
    """Build a filesystem-safe run id `<ts>__<agent>__<provider>__<model>`."""
    provider, model = parse_spec(model_spec)
    return f"{ts or _ts_utc()}__{_safe(agent)}__{_safe(provider)}__{_safe(model)}"


def _git_sha() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            cwd=Path(__file__).resolve().parent.parent.parent,
        )
        return out.decode().strip() or None
    except Exception:
        return None


def _resolve_collision(base: Path) -> Path:
    if not base.exists():
        return base
    for suffix in range(1, 1000):
        candidate = base.with_name(f"{base.name}-{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"too many run-dir collisions for {base}")


class ResultsWriter:
    """Context manager that owns a single run's results directory."""

    def __init__(
        self,
        run_dir: Path,
        *,
        run_id: str,
        agent: str,
        model: str,
        sim_model: str,
        judge_model: str,
        max_turns: int,
        api_keys_used: list[str],
        extra_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.run_dir = _resolve_collision(run_dir)
        self.run_id = run_id
        self.agent = agent
        self.model = model
        self.sim_model = sim_model
        self.judge_model = judge_model
        self.max_turns = max_turns
        self.api_keys_used = sorted(set(api_keys_used))
        self.extra_metadata = dict(extra_metadata) if extra_metadata else {}
        self._start_ts = datetime.now(timezone.utc).isoformat()
        self._per_task: list[dict[str, Any]] = []

    def __enter__(self) -> "ResultsWriter":
        self.run_dir.mkdir(parents=True, exist_ok=False)
        (self.run_dir / "transcripts").mkdir()
        (self.run_dir / "evaluations").mkdir()
        self._write_metadata(end_ts=None, task_count=None)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._write_summary()
        self._write_metadata(end_ts=datetime.now(timezone.utc).isoformat(), task_count=len(self._per_task))

    # ── internals ───────────────────────────────────────────────────────

    def _metadata(self, *, end_ts: str | None, task_count: int | None) -> dict[str, Any]:
        return {
            "agent_variant": self.agent,
            "api_keys_used": self.api_keys_used,
            "end_ts": end_ts,
            "git_sha": _git_sha(),
            "judge_model": self.judge_model,
            "max_turns": self.max_turns,
            "model": self.model,
            "run_id": self.run_id,
            "sim_model": self.sim_model,
            "start_ts": self._start_ts,
            "task_count": task_count,
            **self.extra_metadata,
        }

    def _write_metadata(self, *, end_ts: str | None, task_count: int | None) -> None:
        _write_json(self.run_dir / "metadata.json", self._metadata(end_ts=end_ts, task_count=task_count))

    def _write_summary(self) -> None:
        counts = {"PASS": 0, "FAIL": 0, "ERROR": 0}
        for row in self._per_task:
            counts[row["score"]] = counts.get(row["score"], 0) + 1
        _write_json(
            self.run_dir / "summary.json",
            {"counts": counts, "tasks": sorted(self._per_task, key=lambda r: str(r["task_id"]))},
        )

    # ── public API ──────────────────────────────────────────────────────

    def write_task(
        self,
        *,
        task_id: str,
        score: str,
        terminated_by: str,
        turn_count: int,
        transcript: list[dict[str, Any]],
        evaluation: dict[str, Any],
        error: str | None = None,
    ) -> None:
        _write_json(self.run_dir / "transcripts" / f"{task_id}.json", {
            "task_id": task_id,
            "terminated_by": terminated_by,
            "transcript": transcript,
            "turn_count": turn_count,
        })
        eval_payload = dict(evaluation)
        if error is not None:
            eval_payload.setdefault("error", error)
        _write_json(self.run_dir / "evaluations" / f"{task_id}.json", eval_payload)
        self._per_task.append({
            "score": score,
            "task_id": task_id,
            "terminated_by": terminated_by,
            "turn_count": turn_count,
        })


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
