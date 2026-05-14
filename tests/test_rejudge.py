"""--rejudge-from path: re-run the judge on saved transcripts without sim/agent."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.eval.run import main as eval_main
from src.eval.schemas import AssertionResult, JudgeResult


def _write_source_run(tmp_path: Path) -> Path:
    """Build a synthetic source-run directory with one transcript file."""
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
    (rd / "transcripts" / "0.json").write_text(
        json.dumps(
            {
                "task_id": "0",
                "terminated_by": "simulator_end",
                "transcript": [
                    {"role": "user", "content": "hi"},
                    {"role": "agent", "content": "hello, how can I help?"},
                ],
                "turn_count": 1,
            },
            sort_keys=True,
        )
    )
    return rd


def _write_tasks_file(tmp_path: Path) -> Path:
    """Single-task tasks.json with one nl_assertion."""
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text(
        json.dumps(
            [
                {
                    "id": "0",
                    "description": {"purpose": "synthetic", "relevant_policies": None, "notes": None},
                    "user_scenario": {"persona": None, "instructions": {}},
                    "initial_state": None,
                    "evaluation_criteria": {
                        "actions": [],
                        "communicate_info": [],
                        "nl_assertions": ["Agent should greet the user."],
                        "reward_basis": ["COMMUNICATE"],
                    },
                    "annotations": None,
                }
            ]
        )
    )
    return tasks_path


@pytest.fixture
def patched_env(monkeypatch):
    """Set the env keys the CLI's validate_env() requires."""
    for k, v in {
        "OPENROUTER_API_KEY": "x",
        "LANGFUSE_PUBLIC_KEY": "x",
        "LANGFUSE_SECRET_KEY": "x",
        "LANGFUSE_BASE_URL": "http://lf.invalid",
    }.items():
        monkeypatch.setenv(k, v)


def _stub_judge_chat_model() -> MagicMock:
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


def test_rejudge_produces_new_run_dir_with_source_lineage(tmp_path: Path, patched_env):
    source_dir = _write_source_run(tmp_path)
    tasks_path = _write_tasks_file(tmp_path)
    out_dir = tmp_path / "out"

    with patch("src.eval.run.build_chat_model", return_value=_stub_judge_chat_model()), \
         patch("src.eval.run.init_langfuse", return_value=None), \
         patch("src.eval.run.task_run_config", return_value={}):
        rc = eval_main(
            argv=[
                "--rejudge-from", str(source_dir),
                "--judge-model", "openrouter:moonshotai/kimi-k2.6",
                "--tasks", str(tasks_path),
                "--results-dir", str(out_dir),
            ]
        )

    assert rc == 0
    runs = list(out_dir.iterdir())
    assert len(runs) == 1
    new_run = runs[0]
    assert "rejudge" in new_run.name

    files = {p.relative_to(new_run).as_posix() for p in new_run.rglob("*") if p.is_file()}
    assert files == {
        "metadata.json",
        "summary.json",
        "transcripts/0.json",
        "evaluations/0.json",
    }

    meta = json.loads((new_run / "metadata.json").read_text())
    assert meta["mode"] == "rejudge"
    assert meta["source_run_id"] == source_dir.name
    assert meta["agent_variant"] == "v1"
    assert meta["judge_model"] == "openrouter:moonshotai/kimi-k2.6"

    # Transcript was copied through verbatim.
    new_transcript = json.loads((new_run / "transcripts" / "0.json").read_text())
    src_transcript = json.loads((source_dir / "transcripts" / "0.json").read_text())
    assert new_transcript == src_transcript

    # New evaluation reflects the stubbed judge verdict.
    new_eval = json.loads((new_run / "evaluations" / "0.json").read_text())
    assert new_eval["passed"] is True
    assert new_eval["summary"] == "agent greeted"

    summary = json.loads((new_run / "summary.json").read_text())
    assert summary["counts"] == {"PASS": 1, "FAIL": 0, "ERROR": 0}


def test_rejudge_skips_tasks_with_empty_transcripts(tmp_path: Path, patched_env):
    """If the source task errored before producing a transcript, rejudge carries the ERROR forward without calling the judge."""
    source_dir = _write_source_run(tmp_path)
    # Overwrite transcript with an empty conversation, simulating a source ERROR.
    (source_dir / "transcripts" / "0.json").write_text(
        json.dumps(
            {"task_id": "0", "terminated_by": "error", "transcript": [], "turn_count": 0},
            sort_keys=True,
        )
    )
    tasks_path = _write_tasks_file(tmp_path)
    out_dir = tmp_path / "out"

    judge_mock = _stub_judge_chat_model()
    with patch("src.eval.run.build_chat_model", return_value=judge_mock), \
         patch("src.eval.run.init_langfuse", return_value=None), \
         patch("src.eval.run.task_run_config", return_value={}):
        rc = eval_main(
            argv=[
                "--rejudge-from", str(source_dir),
                "--judge-model", "openrouter:moonshotai/kimi-k2.6",
                "--tasks", str(tasks_path),
                "--results-dir", str(out_dir),
            ]
        )

    assert rc != 0  # ERROR makes the exit code non-zero
    judge_mock.with_structured_output.assert_not_called()  # judge never invoked

    new_run = next(out_dir.iterdir())
    new_eval = json.loads((new_run / "evaluations" / "0.json").read_text())
    assert new_eval["passed"] is False
    assert "empty" in new_eval["summary"].lower()
    summary = json.loads((new_run / "summary.json").read_text())
    assert summary["counts"]["ERROR"] == 1


def test_rejudge_respects_limit(tmp_path: Path, patched_env):
    """--limit is applied to the rejudge task set just like normal eval."""
    source_dir = _write_source_run(tmp_path)
    # Add a second transcript so --limit has something to filter.
    (source_dir / "transcripts" / "1.json").write_text(
        json.dumps(
            {"task_id": "1", "terminated_by": "simulator_end", "transcript": [{"role": "user", "content": "x"}], "turn_count": 1},
            sort_keys=True,
        )
    )
    # Tasks file must also list task 1.
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text(
        json.dumps(
            [
                {"id": "0", "description": {"purpose": ""}, "user_scenario": {}, "evaluation_criteria": {"nl_assertions": ["a"]}},
                {"id": "1", "description": {"purpose": ""}, "user_scenario": {}, "evaluation_criteria": {"nl_assertions": ["a"]}},
            ]
        )
    )

    with patch("src.eval.run.build_chat_model", return_value=_stub_judge_chat_model()), \
         patch("src.eval.run.init_langfuse", return_value=None), \
         patch("src.eval.run.task_run_config", return_value={}):
        eval_main(
            argv=[
                "--rejudge-from", str(source_dir),
                "--judge-model", "openrouter:moonshotai/kimi-k2.6",
                "--tasks", str(tasks_path),
                "--results-dir", str(tmp_path / "out"),
                "--limit", "1",
            ]
        )

    new_run = next((tmp_path / "out").iterdir())
    summary = json.loads((new_run / "summary.json").read_text())
    assert summary["counts"]["PASS"] + summary["counts"]["FAIL"] + summary["counts"]["ERROR"] == 1
