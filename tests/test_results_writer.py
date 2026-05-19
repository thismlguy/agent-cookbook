"""Results-export round-trip + diff-stability tests."""
from __future__ import annotations

import json
from pathlib import Path

from src.results import ResultsWriter, compose_run_id


def _write_two_runs(tmpdir: Path) -> tuple[Path, Path]:
    """Two back-to-back runs with identical content. Their per-task files
    should be byte-equal so cross-run diffs are content-only."""
    rid = compose_run_id("v1", "openrouter:moonshotai/kimi-k2.6", ts="2026-05-13T00-00-00Z")
    paths: list[Path] = []
    for suffix in ("a", "b"):
        rd = tmpdir / f"{rid}-{suffix}"
        with ResultsWriter(
            rd,
            run_id=rid,
            agent="v1",
            model="openrouter:moonshotai/kimi-k2.6",
            sim_model="openrouter:moonshotai/kimi-k2.6",
            judge_model="openrouter:moonshotai/kimi-k2.6",
            max_turns=30,
            api_keys_used=["OPENROUTER_API_KEY", "LANGFUSE_BASE_URL"],
        ) as w:
            w.write_task(
                task_id="0",
                score="PASS",
                terminated_by="simulator_end",
                turn_count=2,
                transcript=[
                    {"role": "user", "content": "hello"},
                    {"role": "agent", "content": "hi! how can I help?"},
                ],
                evaluation={
                    "assertions": [],
                    "passed": True,
                    "summary": "no assertions",
                },
            )
        paths.append(rd)
    return paths[0], paths[1]


def test_results_writer_creates_expected_layout(tmp_path: Path):
    rid = compose_run_id("v1", "openrouter:moonshotai/kimi-k2.6")
    rd = tmp_path / rid
    with ResultsWriter(
        rd, run_id=rid, agent="v1", model="openrouter:moonshotai/kimi-k2.6",
        sim_model="openrouter:moonshotai/kimi-k2.6", judge_model="openrouter:moonshotai/kimi-k2.6",
        max_turns=30, api_keys_used=["OPENROUTER_API_KEY"],
    ) as w:
        w.write_task(
            task_id="42", score="FAIL", terminated_by="max_turns", turn_count=30,
            transcript=[{"role": "user", "content": "x"}],
            evaluation={"assertions": [], "passed": False, "summary": "ran out"},
            agent_response_times_ms=[120.5, 80.0],
        )

    files = {p.relative_to(rd).as_posix() for p in rd.rglob("*") if p.is_file()}
    assert files == {
        "metadata.json",
        "summary.json",
        "transcripts/42.json",
        "evaluations/42.json",
    }

    summary = json.loads((rd / "summary.json").read_text())
    assert summary["counts"]["FAIL"] == 1
    assert summary["tasks"][0]["task_id"] == "42"
    assert summary["tasks"][0]["summary"] == "ran out"

    # Raw per-turn list lives in the transcript file.
    transcript = json.loads((rd / "transcripts" / "42.json").read_text())
    assert transcript["agent_response_times_ms"] == [120.5, 80.0]

    # Per-task stats on the summary row + run-wide aggregate at the top.
    expected_stats = {"count": 2, "min": 80.0, "median": 100.25, "avg": 100.25, "max": 120.5}
    assert summary["tasks"][0]["response_time_stats_ms"] == expected_stats
    assert summary["response_time_stats_ms"] == expected_stats
    # The internal aggregation key must not leak into the on-disk row.
    assert "_raw_times" not in summary["tasks"][0]

    meta = json.loads((rd / "metadata.json").read_text())
    assert meta["agent_variant"] == "v1"
    assert meta["task_count"] == 1
    assert meta["end_ts"] is not None


def test_results_files_diff_cleanly_between_identical_runs(tmp_path: Path):
    rd_a, rd_b = _write_two_runs(tmp_path)
    for rel in ("transcripts/0.json", "evaluations/0.json", "summary.json"):
        assert (rd_a / rel).read_text() == (rd_b / rel).read_text(), rel


def test_compose_run_id_collapses_unsafe_chars():
    rid = compose_run_id("v1", "openrouter:moonshotai/kimi-k2.6", ts="2026-05-13T00-00-00Z")
    # `/` should be collapsed to a safe char so the id is filesystem-safe.
    assert "/" not in rid
    assert "moonshotai-kimi-k2.6" in rid
