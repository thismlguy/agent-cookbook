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
import statistics
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.providers.select import parse_spec


def _stats(values: list[float]) -> dict[str, float | int] | None:
    """Min/median/avg/max + count for a list of measurements. None if empty."""
    if not values:
        return None
    return {
        "count": len(values),
        "min": round(min(values), 2),
        "median": round(statistics.median(values), 2),
        "avg": round(sum(values) / len(values), 2),
        "max": round(max(values), 2),
    }


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
        self._assert_passed = 0
        self._assert_total = 0
        self._lock = threading.Lock()

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

    def assertion_counts(self) -> dict[str, Any]:
        """Aggregate per-assertion pass/fail across all tasks.

        Complements the task-level `counts` (which is all-or-nothing: a task
        passes only if every assertion passes). The assertion-level pass rate
        is a finer-grained signal — it shows partial credit on tasks that miss
        one of several checks.
        """
        passed, total = self._assert_passed, self._assert_total
        return {
            "passed": passed,
            "failed": total - passed,
            "total": total,
            "pass_rate": round(passed / total, 4) if total else None,
        }

    def _write_summary(self) -> None:
        counts = {"PASS": 0, "FAIL": 0, "ERROR": 0}
        counts_by_intent: dict[str, dict[str, int]] = {}
        all_times: list[float] = []
        rows: list[dict[str, Any]] = []
        for row in self._per_task:
            counts[row["score"]] = counts.get(row["score"], 0) + 1
            for intent in row.get("intents") or []:
                bucket = counts_by_intent.setdefault(intent, {"PASS": 0, "FAIL": 0, "ERROR": 0})
                bucket[row["score"]] = bucket.get(row["score"], 0) + 1
            raw_times = row.pop("_raw_times", []) or []
            all_times.extend(raw_times)
            rows.append(row)
        _write_json(
            self.run_dir / "summary.json",
            {
                "counts": counts,
                "assertion_counts": self.assertion_counts(),
                "counts_by_intent": counts_by_intent,
                "response_time_stats_ms": _stats(all_times),
                "tasks": sorted(rows, key=lambda r: str(r["task_id"])),
            },
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
        agent_response_times_ms: list[float] | None = None,
        intents: list[str] | None = None,
    ) -> None:
        times = list(agent_response_times_ms or [])
        transcript_payload: dict[str, Any] = {
            "task_id": task_id,
            "terminated_by": terminated_by,
            "transcript": transcript,
            "turn_count": turn_count,
        }
        # Only persist the response-time list when we actually collected
        # measurements. This keeps rejudge byte-identical for old run dirs
        # that predate the metric.
        if times:
            transcript_payload["agent_response_times_ms"] = times
        _write_json(self.run_dir / "transcripts" / f"{task_id}.json", transcript_payload)
        eval_payload = dict(evaluation)
        if error is not None:
            eval_payload.setdefault("error", error)
        _write_json(self.run_dir / "evaluations" / f"{task_id}.json", eval_payload)
        assertions = evaluation.get("assertions") or []
        n_passed = sum(1 for a in assertions if a.get("passed"))
        n_total = len(assertions)
        with self._lock:
            self._assert_passed += n_passed
            self._assert_total += n_total
            self._per_task.append({
                "_raw_times": times,
                "assertions_passed": n_passed,
                "assertions_total": n_total,
                "intents": list(intents or []),
                "response_time_stats_ms": _stats(times),
                "score": score,
                "summary": evaluation.get("summary", ""),
                "task_id": task_id,
                "terminated_by": terminated_by,
                "turn_count": turn_count,
            })


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
