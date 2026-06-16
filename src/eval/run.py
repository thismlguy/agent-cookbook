"""`python -m src.eval.run` — run an agent variant + provider against tasks.json.

Each task is run through the conversation runner, judged by the LLM-as-judge,
and written to a per-run results directory. Per-task spans are sent to
Langfuse as one trace per task.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from src.eval.judge import judge as judge_task
from src.eval.schemas import JudgeResult
from src.obs.langfuse import init_langfuse, task_run_config
from src.providers import build_chat_model, required_keys_for, validate_env
from src.results import ResultsWriter, compose_run_id
from src.runner import TurnEvent, run_task

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_TASKS_PATH = REPO_ROOT / "data" / "tasks.json"
DEFAULT_RESULTS_DIR = REPO_ROOT / "results"
DEFAULT_AGENT_MODEL = "openrouter:moonshotai/kimi-k2.6"
DEFAULT_AGENT = "v1"
DEFAULT_MAX_TURNS = 15
DEFAULT_CONCURRENCY = 10

# Serializes the per-task stdout blocks so concurrent workers print one task
# at a time instead of interleaving lines.
_print_lock = threading.Lock()

UNCONDITIONAL_KEYS = (
    "OPENROUTER_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
)


# ────────────────────────── CLI plumbing ──────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="src.eval.run", description="Run an agent variant + provider against tasks.json.")
    p.add_argument("--agent", default=DEFAULT_AGENT, help=f"agent variant id (default: {DEFAULT_AGENT})")
    p.add_argument("--model", default=DEFAULT_AGENT_MODEL, help=f"agent model spec '<provider>:<model>' (default: {DEFAULT_AGENT_MODEL})")
    p.add_argument("--sim-model", default=None, help="simulator model spec (default: same as --model)")
    p.add_argument("--judge-model", default=None, help="judge model spec (default: same as --model)")
    p.add_argument(
        "--task-id",
        default=None,
        help="run only these task ids — comma-separated for multiple (e.g. '7,21,38'). Default: all.",
    )
    p.add_argument("--limit", type=int, default=None, help="run only the first N tasks (after --task-id filter)")
    p.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS, help="conversation turn cap")
    p.add_argument(
        "--effort",
        default=None,
        choices=["low", "medium", "high", "max"],
        help="agent reasoning effort (output_config.effort). Anthropic Sonnet/Opus only; "
        "Haiku rejects it. Applies to the agent model, not the simulator or judge.",
    )
    p.add_argument(
        "--thinking",
        default=None,
        choices=["adaptive"],
        help="enable agent extended thinking (adaptive). Pair with --effort to control depth. "
        "Applies to the agent model only.",
    )
    p.add_argument(
        "--sim-reasoning",
        action="store_true",
        help="enable reasoning for an openrouter Kimi-K2.x simulator model "
        "(off for every other provider/model). No effect unless --sim-model is Kimi.",
    )
    p.add_argument(
        "--judge-reasoning",
        action="store_true",
        help="same as --sim-reasoning, for the judge model.",
    )
    p.add_argument(
        "--sim-reasoning-budget",
        type=int,
        default=None,
        help="cap Kimi sim reasoning to N tokens (OpenRouter token-budget form). "
        "Only meaningful with --sim-reasoning; Moonshot treats it as a soft cap.",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=(
            f"number of tasks to run in parallel (default: {DEFAULT_CONCURRENCY}). "
            "Set to 1 for fully sequential / easier debugging. Higher values may "
            "trip provider rate limits or credit-reservation caps."
        ),
    )
    p.add_argument("--tasks", default=str(DEFAULT_TASKS_PATH), help="path to tasks.json (default: data/tasks.json)")
    p.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR), help="parent directory for per-run results")
    p.add_argument(
        "--rejudge-from",
        default=None,
        help=(
            "path to an existing results/<run_id>/ directory; when set, the simulator "
            "and agent are skipped and the judge is re-applied to each saved transcript. "
            "--model and --sim-model are ignored in this mode."
        ),
    )
    return p.parse_args(argv)


def _load_tasks(path: Path, task_id: str | None) -> list[dict[str, Any]]:
    tasks = json.loads(path.read_text())
    if task_id is None:
        return tasks
    wanted = [s.strip() for s in task_id.split(",") if s.strip()]
    by_id = {str(t.get("id")): t for t in tasks}
    missing = [w for w in wanted if w not in by_id]
    if missing:
        raise SystemExit(f"task id(s) {missing!r} not found in {path}")
    return [by_id[w] for w in wanted]


def _load_source_run(source_dir: Path) -> tuple[str, dict[str, Any], dict[str, dict[str, Any]]]:
    """Read an existing results dir and return (source_run_id, source_metadata, transcripts_by_id).

    `transcripts_by_id` maps `task_id -> parsed transcript JSON` (the per-task
    file as written by the runner: `{task_id, terminated_by, transcript, turn_count}`).
    """
    if not source_dir.is_dir():
        raise SystemExit(f"--rejudge-from path does not exist or is not a directory: {source_dir}")
    metadata_path = source_dir / "metadata.json"
    transcripts_dir = source_dir / "transcripts"
    if not transcripts_dir.is_dir():
        raise SystemExit(f"no transcripts/ subdirectory under {source_dir}")
    source_metadata = json.loads(metadata_path.read_text()) if metadata_path.is_file() else {}
    source_run_id = source_metadata.get("run_id") or source_dir.name
    transcripts: dict[str, dict[str, Any]] = {}
    for tf in sorted(transcripts_dir.glob("*.json")):
        entry = json.loads(tf.read_text())
        transcripts[str(entry.get("task_id", tf.stem))] = entry
    return source_run_id, source_metadata, transcripts


# ────────────────────────── per-turn stream ──────────────────────────


def _format_event(ev: TurnEvent) -> list[str]:
    lines: list[str] = []
    if ev.user is not None:
        lines.append(f"[turn {ev.turn}] USER: {ev.user}")
    for tc in ev.tool_calls:
        args = json.dumps(tc.get("args", {}), sort_keys=True)
        result = (tc.get("result") or "")
        if len(result) > 240:
            result = result[:240] + "…"
        lines.append(f"[turn {ev.turn}] TOOL {tc.get('name')}({args}) -> {result}")
    if ev.agent:
        lines.append(f"[turn {ev.turn}] AGENT: {ev.agent}")
    if ev.ended:
        lines.append(f"[turn {ev.turn}] (simulator ended the conversation)")
    return lines


def _make_event_collector() -> tuple[Callable[[TurnEvent], None], list[str]]:
    """Build an `on_event` callback that buffers formatted lines into a list.

    With multiple tasks running concurrently we cannot print per-turn lines
    immediately without garbling stdout. Each task collects its own buffer
    and the worker flushes it atomically (under `_print_lock`) when done.
    """
    lines: list[str] = []

    def cb(ev: TurnEvent) -> None:
        lines.extend(_format_event(ev))

    return cb, lines


def _flush_task_block(header: str, lines: list[str], verdict_line: str, *, error: bool = False) -> None:
    """Print one task's buffered output as a single contiguous block."""
    with _print_lock:
        print(header)
        for line in lines:
            print(line)
        print(verdict_line, file=sys.stderr if error else sys.stdout)


# ────────────────────────── per-task pipeline ──────────────────────────


def _rejudge_one_task(
    *,
    task: dict[str, Any],
    transcript_entry: dict[str, Any],
    judge_spec: str,
    writer: ResultsWriter,
    run_id: str,
    source_run_id: str,
    source_agent_variant: str,
    source_model: str,
    source_sim_model: str,
) -> str:
    """Re-run the judge against a previously-saved transcript.

    Skips the simulator and agent entirely. Preserves the source
    transcript verbatim in the new run dir; only the evaluation file
    is freshly produced.
    """
    task_id = str(task.get("id"))
    saved_transcript: list[dict[str, Any]] = transcript_entry.get("transcript") or []
    terminated_by = transcript_entry.get("terminated_by") or "unknown"
    turn_count = int(transcript_entry.get("turn_count") or 0)
    saved_times: list[float] = list(transcript_entry.get("agent_response_times_ms") or [])
    header = f"\n=== task {task_id} (rejudge) ==="

    cfg = task_run_config(
        run_id=run_id,
        task_id=task_id,
        agent_variant=source_agent_variant,
        model=source_model,
        sim_model=source_sim_model,
        judge_model=judge_spec,
        mode="rejudge",
        source_run_id=source_run_id,
    )

    if not saved_transcript:
        writer.write_task(
            task_id=task_id,
            score="ERROR",
            terminated_by=terminated_by,
            turn_count=turn_count,
            transcript=[],
            evaluation={
                "assertions": [],
                "passed": False,
                "summary": "source transcript was empty; rejudge skipped.",
            },
            error="source transcript was empty",
            intents=task.get("intents") or [],
        )
        _flush_task_block(header, [], f"task {task_id}: ERROR — source transcript empty; skipped", error=True)
        return "ERROR"

    try:
        judge_llm = build_chat_model(judge_spec)
        verdict: JudgeResult = judge_task(task, saved_transcript, judge_llm)
        score = "PASS" if verdict.passed else "FAIL"
        writer.write_task(
            task_id=task_id,
            score=score,
            terminated_by=terminated_by,
            turn_count=turn_count,
            transcript=saved_transcript,
            evaluation=verdict.model_dump(),
            agent_response_times_ms=saved_times,
            intents=task.get("intents") or [],
        )
        _flush_task_block(
            header,
            [],
            f"task {task_id}: {score} — {verdict.summary}",
        )
        return score
    except Exception as e:  # noqa: BLE001 — per-task isolation
        tb = traceback.format_exc()
        writer.write_task(
            task_id=task_id,
            score="ERROR",
            terminated_by=terminated_by,
            turn_count=turn_count,
            transcript=saved_transcript,
            evaluation={
                "assertions": [], "passed": False,
                "summary": "error during rejudge",
            },
            error=tb,
            agent_response_times_ms=saved_times,
            intents=task.get("intents") or [],
        )
        _flush_task_block(header, [], f"task {task_id}: ERROR — {e}", error=True)
        return "ERROR"


def _run_one_task(
    task: dict[str, Any],
    *,
    args: argparse.Namespace,
    sim_spec: str,
    judge_spec: str,
    writer: ResultsWriter,
    run_id: str,
) -> str:
    task_id = str(task.get("id"))
    header = f"\n=== task {task_id} ==="
    on_event, event_lines = _make_event_collector()
    cfg = task_run_config(
        run_id=run_id,
        task_id=task_id,
        agent_variant=args.agent,
        model=args.model,
        sim_model=sim_spec,
        judge_model=judge_spec,
    )

    try:
        thinking = {"type": args.thinking} if args.thinking else None
        agent_llm = build_chat_model(args.model, effort=args.effort, thinking=thinking)
        sim_llm = build_chat_model(
            sim_spec,
            enable_reasoning=args.sim_reasoning,
            reasoning_max_tokens=args.sim_reasoning_budget,
        )
        judge_llm = build_chat_model(judge_spec, enable_reasoning=args.judge_reasoning)

        run_result = run_task(
            task=task,
            agent_id=args.agent,
            agent_llm=agent_llm,
            sim_llm=sim_llm,
            max_turns=args.max_turns,
            on_event=on_event,
            invoke_config=cfg,
        )
        verdict: JudgeResult = judge_task(task, run_result.transcript, judge_llm)
        score = "PASS" if verdict.passed else "FAIL"
        writer.write_task(
            task_id=task_id,
            score=score,
            terminated_by=run_result.terminated_by,
            turn_count=run_result.turn_count,
            transcript=run_result.transcript,
            evaluation=verdict.model_dump(),
            agent_response_times_ms=run_result.agent_response_times_ms,
            intents=task.get("intents") or [],
        )
        _flush_task_block(
            header,
            event_lines,
            f"task {task_id}: {score} — {verdict.summary}",
        )
        return score
    except Exception as e:  # noqa: BLE001 — per-task isolation
        tb = traceback.format_exc()
        writer.write_task(
            task_id=task_id,
            score="ERROR",
            terminated_by="error",
            turn_count=0,
            transcript=[],
            evaluation={
                "assertions": [], "passed": False,
                "summary": "error during run/judge",
            },
            error=tb,
            intents=task.get("intents") or [],
        )
        _flush_task_block(header, event_lines, f"task {task_id}: ERROR — {e}", error=True)
        return "ERROR"


# ────────────────────────── main ──────────────────────────


def _print_summary(counts: dict[str, int], assertion_counts: dict[str, Any] | None = None) -> None:
    print("\n=== summary ===")
    total_tasks = counts.get("PASS", 0) + counts.get("FAIL", 0) + counts.get("ERROR", 0)
    print(
        f"tasks          PASS: {counts.get('PASS', 0)}  "
        f"FAIL: {counts.get('FAIL', 0)}  "
        f"ERROR: {counts.get('ERROR', 0)}"
        + (f"   ({counts.get('PASS', 0)}/{total_tasks})" if total_tasks else "")
    )
    if assertion_counts and assertion_counts.get("total"):
        rate = assertion_counts.get("pass_rate")
        print(
            f"assertions     PASS: {assertion_counts['passed']}  "
            f"FAIL: {assertion_counts['failed']}  "
            f"({assertion_counts['passed']}/{assertion_counts['total']}"
            + (f", {rate:.1%}" if rate is not None else "")
            + ")"
        )


def _init_langfuse_from_env(model_id_for_config: str) -> None:
    """Re-use the Config dataclass to spin up Langfuse with already-validated keys."""
    from src.config import Config

    cfg = Config(
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        langfuse_public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        langfuse_secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        langfuse_base_url=os.environ["LANGFUSE_BASE_URL"],
        model_id=model_id_for_config,
    )
    init_langfuse(cfg)


def _main_rejudge(args: argparse.Namespace) -> int:
    """Re-run only the judge against an existing results/<run_id>/ directory."""
    judge_spec = args.judge_model or args.model
    validate_env({"judge": judge_spec}, extra_required=UNCONDITIONAL_KEYS)
    _init_langfuse_from_env(judge_spec.split(":", 1)[1])

    source_dir = Path(args.rejudge_from)
    source_run_id, source_metadata, source_transcripts = _load_source_run(source_dir)

    tasks_path = Path(args.tasks)
    tasks = _load_tasks(tasks_path, args.task_id)
    tasks = [t for t in tasks if str(t.get("id")) in source_transcripts]
    if args.limit is not None:
        tasks = tasks[: args.limit]
    if not tasks:
        raise SystemExit(
            "no tasks to rejudge — every requested task either missing from "
            f"tasks.json or absent from {source_dir}/transcripts/"
        )

    source_agent = str(source_metadata.get("agent_variant") or "unknown")
    source_model = str(source_metadata.get("model") or "unknown")
    source_sim_model = str(source_metadata.get("sim_model") or "unknown")

    run_id = compose_run_id("rejudge", judge_spec)
    run_dir = Path(args.results_dir) / run_id
    api_keys = sorted(
        required_keys_for(judge_spec)
        | {"LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"}
    )

    print(f"mode:           rejudge")
    print(f"source run:     {source_dir}")
    print(f"source run id:  {source_run_id}")
    print(f"new run id:     {run_id}")
    print(f"new results:    {run_dir}")
    print(f"tasks:          {len(tasks)} (filtered by intersection with source transcripts)")
    print(f"judge:          {judge_spec}")
    print(f"concurrency:    {args.concurrency}")

    counts = {"PASS": 0, "FAIL": 0, "ERROR": 0}
    with ResultsWriter(
        run_dir,
        run_id=run_id,
        agent=source_agent,
        model=source_model,
        sim_model=source_sim_model,
        judge_model=judge_spec,
        max_turns=int(source_metadata.get("max_turns") or 0),
        api_keys_used=api_keys,
        extra_metadata={"mode": "rejudge", "source_run_id": source_run_id},
    ) as writer:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as ex:
            futures = [
                ex.submit(
                    _rejudge_one_task,
                    task=task,
                    transcript_entry=source_transcripts[str(task.get("id"))],
                    judge_spec=judge_spec,
                    writer=writer,
                    run_id=run_id,
                    source_run_id=source_run_id,
                    source_agent_variant=source_agent,
                    source_model=source_model,
                    source_sim_model=source_sim_model,
                )
                for task in tasks
            ]
            for fut in as_completed(futures):
                score = fut.result()
                counts[score] = counts.get(score, 0) + 1

    _print_summary(counts, writer.assertion_counts())
    print(f"results written to: {run_dir}")
    return 0 if counts["FAIL"] == 0 and counts["ERROR"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / ".env")
    args = _parse_args(argv)

    if args.rejudge_from is not None:
        return _main_rejudge(args)

    sim_spec = args.sim_model or args.model
    judge_spec = args.judge_model or args.model

    validate_env(
        {"agent": args.model, "sim": sim_spec, "judge": judge_spec},
        extra_required=UNCONDITIONAL_KEYS,
    )
    _init_langfuse_from_env(args.model.split(":", 1)[1])

    tasks_path = Path(args.tasks)
    tasks = _load_tasks(tasks_path, args.task_id)
    if args.limit is not None:
        tasks = tasks[: args.limit]

    run_id = compose_run_id(args.agent, args.model)
    run_dir = Path(args.results_dir) / run_id
    api_keys = sorted(
        required_keys_for(args.model)
        | required_keys_for(sim_spec)
        | required_keys_for(judge_spec)
        | {"LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"}
    )

    print(f"run id:      {run_id}")
    print(f"results:     {run_dir}")
    print(f"tasks:       {len(tasks)} from {tasks_path}")
    print(f"agent:       {args.agent} @ {args.model}")
    print(f"sim:         {sim_spec}")
    print(f"judge:       {judge_spec}")
    print(f"concurrency: {args.concurrency}")

    counts = {"PASS": 0, "FAIL": 0, "ERROR": 0}
    with ResultsWriter(
        run_dir,
        run_id=run_id,
        agent=args.agent,
        model=args.model,
        sim_model=sim_spec,
        judge_model=judge_spec,
        max_turns=args.max_turns,
        api_keys_used=api_keys,
    ) as writer:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as ex:
            futures = [
                ex.submit(
                    _run_one_task,
                    task,
                    args=args,
                    sim_spec=sim_spec,
                    judge_spec=judge_spec,
                    writer=writer,
                    run_id=run_id,
                )
                for task in tasks
            ]
            for fut in as_completed(futures):
                score = fut.result()
                counts[score] = counts.get(score, 0) + 1

    _print_summary(counts, writer.assertion_counts())
    print(f"results written to: {run_dir}")
    return 0 if counts["FAIL"] == 0 and counts["ERROR"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
