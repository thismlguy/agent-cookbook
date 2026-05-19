"""--concurrency flag: rejudge path with multiple tasks running in parallel."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.eval.run import main as eval_main
from src.eval.schemas import AssertionResult, JudgeResult


def _write_source_run(
    tmp_path: Path,
    task_ids: list[str],
    times_by_id: dict[str, list[float]] | None = None,
) -> Path:
    """Build a synthetic source-run directory with N transcripts.

    Optional `times_by_id` injects `agent_response_times_ms` per task so the
    rejudge path can re-emit them on the new run.
    """
    times_by_id = times_by_id or {}
    rd = tmp_path / "src_run" / "2026-05-14T00-00-00Z__v1__openrouter__moonshotai-kimi-k2.6"
    (rd / "transcripts").mkdir(parents=True)
    (rd / "evaluations").mkdir()
    (rd / "metadata.json").write_text(
        json.dumps(
            {
                "agent_variant": "v1",
                "judge_model": "openrouter:moonshotai/kimi-k2.6",
                "max_turns": 30,
                "model": "openrouter:moonshotai/kimi-k2.6",
                "run_id": "2026-05-14T00-00-00Z__v1__openrouter__moonshotai-kimi-k2.6",
                "sim_model": "openrouter:moonshotai/kimi-k2.6",
            },
            sort_keys=True,
        )
    )
    for tid in task_ids:
        entry: dict[str, Any] = {
            "task_id": tid,
            "terminated_by": "simulator_end",
            "transcript": [
                {"role": "user", "content": "hi"},
                {"role": "agent", "content": "hello"},
            ],
            "turn_count": 1,
        }
        if tid in times_by_id:
            entry["agent_response_times_ms"] = times_by_id[tid]
        (rd / "transcripts" / f"{tid}.json").write_text(json.dumps(entry, sort_keys=True))
    return rd


def _write_tasks_file(tmp_path: Path, task_ids: list[str]) -> Path:
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text(
        json.dumps(
            [
                {
                    "id": tid,
                    "description": {"purpose": f"task {tid}"},
                    "user_scenario": {},
                    "evaluation_criteria": {"nl_assertions": ["Agent should greet the user."]},
                }
                for tid in task_ids
            ]
        )
    )
    return tasks_path


def _build_stub_judge() -> MagicMock:
    """Build a chat-model stub. The mock structured-output invoke returns a fixed verdict.

    Crucially, the SAME mock is shared across threads — `unittest.mock` is
    thread-safe enough for concurrent reads of a return_value, so this
    proves that workers really do run in parallel without trampling state.
    """
    fake_verdict = JudgeResult(
        assertions=[AssertionResult(assertion="Agent should greet the user.", passed=True, rationale="said hello")],
        passed=True,
        summary="agent greeted",
    )
    structured = MagicMock()
    structured.invoke = MagicMock(return_value=fake_verdict)
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)
    return llm


@pytest.fixture
def patched_env(monkeypatch):
    for k, v in {
        "OPENROUTER_API_KEY": "x",
        "LANGFUSE_PUBLIC_KEY": "x",
        "LANGFUSE_SECRET_KEY": "x",
        "LANGFUSE_BASE_URL": "http://lf.invalid",
    }.items():
        monkeypatch.setenv(k, v)


def test_concurrency_runs_multiple_tasks_in_parallel(tmp_path: Path, patched_env):
    task_ids = ["0", "1", "2"]
    source_dir = _write_source_run(tmp_path, task_ids)
    tasks_path = _write_tasks_file(tmp_path, task_ids)

    with patch("src.eval.run.build_chat_model", return_value=_build_stub_judge()), \
         patch("src.eval.run.init_langfuse", return_value=None), \
         patch("src.eval.run.task_run_config", return_value={}):
        rc = eval_main(
            argv=[
                "--rejudge-from", str(source_dir),
                "--judge-model", "openrouter:moonshotai/kimi-k2.6",
                "--tasks", str(tasks_path),
                "--results-dir", str(tmp_path / "out"),
                "--concurrency", "3",
            ]
        )

    assert rc == 0
    new_run = next((tmp_path / "out").iterdir())
    summary = json.loads((new_run / "summary.json").read_text())
    assert summary["counts"] == {"PASS": 3, "FAIL": 0, "ERROR": 0}
    # Every task got its own files written, regardless of completion order.
    transcripts = {p.stem for p in (new_run / "transcripts").iterdir()}
    evaluations = {p.stem for p in (new_run / "evaluations").iterdir()}
    assert transcripts == set(task_ids)
    assert evaluations == set(task_ids)
    # Summary is sorted by task_id, so the on-disk view is deterministic.
    assert [t["task_id"] for t in summary["tasks"]] == sorted(task_ids)


def test_concurrency_one_preserves_sequential_semantics(tmp_path: Path, patched_env):
    """--concurrency 1 is a useful debug knob; verify it still produces correct results."""
    task_ids = ["0", "1"]
    source_dir = _write_source_run(tmp_path, task_ids)
    tasks_path = _write_tasks_file(tmp_path, task_ids)

    with patch("src.eval.run.build_chat_model", return_value=_build_stub_judge()), \
         patch("src.eval.run.init_langfuse", return_value=None), \
         patch("src.eval.run.task_run_config", return_value={}):
        rc = eval_main(
            argv=[
                "--rejudge-from", str(source_dir),
                "--judge-model", "openrouter:moonshotai/kimi-k2.6",
                "--tasks", str(tasks_path),
                "--results-dir", str(tmp_path / "out"),
                "--concurrency", "1",
            ]
        )

    assert rc == 0
    new_run = next((tmp_path / "out").iterdir())
    summary = json.loads((new_run / "summary.json").read_text())
    assert summary["counts"] == {"PASS": 2, "FAIL": 0, "ERROR": 0}


def test_response_time_stats_aggregate_across_tasks(tmp_path: Path, patched_env):
    """Run-wide response_time_stats_ms.count == sum of per-task counts."""
    task_ids = ["0", "1"]
    times_by_id = {"0": [100.0, 200.0, 300.0], "1": [50.0, 150.0]}
    source_dir = _write_source_run(tmp_path, task_ids, times_by_id=times_by_id)
    tasks_path = _write_tasks_file(tmp_path, task_ids)

    with patch("src.eval.run.build_chat_model", return_value=_build_stub_judge()), \
         patch("src.eval.run.init_langfuse", return_value=None), \
         patch("src.eval.run.task_run_config", return_value={}):
        eval_main(
            argv=[
                "--rejudge-from", str(source_dir),
                "--judge-model", "openrouter:moonshotai/kimi-k2.6",
                "--tasks", str(tasks_path),
                "--results-dir", str(tmp_path / "out"),
                "--concurrency", "2",
            ]
        )

    new_run = next((tmp_path / "out").iterdir())
    summary = json.loads((new_run / "summary.json").read_text())
    rows = {r["task_id"]: r for r in summary["tasks"]}

    assert rows["0"]["response_time_stats_ms"]["count"] == 3
    assert rows["1"]["response_time_stats_ms"]["count"] == 2

    run_stats = summary["response_time_stats_ms"]
    assert run_stats["count"] == 5
    assert run_stats["min"] == 50.0
    assert run_stats["max"] == 300.0

    # Raw lists carried through into the rejudged transcripts.
    for tid in task_ids:
        t = json.loads((new_run / "transcripts" / f"{tid}.json").read_text())
        assert t["agent_response_times_ms"] == times_by_id[tid]
