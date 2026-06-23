"""The durable, retryable, resumable multi-agent workflow.

Temporal persists every activity result to the workflow's event history. If a
worker crashes mid-run, another worker replays that history and resumes from
the last completed step — the untrusted execution is never silently re-run
unless its retry policy says so. The workflow body is deterministic; all I/O is
delegated to activities.
"""
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app import config
    from app.activities import (
        code_activity,
        execute_activity,
        plan_activity,
        summarize_activity,
    )
    from app.dto import RunInput, RunResult

# The executor activity must outlast the sandbox's own host timeout plus the
# time to build the job disk and boot the microVM.
_EXECUTE_TIMEOUT = timedelta(seconds=config.SANDBOX_TIMEOUT_S + 120)
_SHORT = timedelta(seconds=30)

_LIGHT_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    non_retryable_error_types=["ValueError"],
)
_EXECUTE_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
)


@workflow.defn
class AgentRunWorkflow:
    def __init__(self) -> None:
        self._status = "pending"
        self._current_step: str | None = None
        self._steps: list[dict] = []

    def _begin(self, name: str) -> None:
        self._current_step = name
        self._steps.append({"name": name, "status": "running"})

    def _end(self, name: str, status: str = "completed") -> None:
        for step in reversed(self._steps):
            if step["name"] == name:
                step["status"] = status
                return

    @workflow.run
    async def run(self, ri: RunInput) -> RunResult:
        self._status = "running"
        try:
            self._begin("planner")
            plan = await workflow.execute_activity(
                plan_activity, ri, start_to_close_timeout=_SHORT, retry_policy=_LIGHT_RETRY
            )
            self._end("planner")

            self._begin("coder")
            artifact = await workflow.execute_activity(
                code_activity, args=[ri, plan], start_to_close_timeout=_SHORT, retry_policy=_LIGHT_RETRY
            )
            self._end("coder")

            self._begin("executor")
            sandbox_result = await workflow.execute_activity(
                execute_activity,
                args=[ri.run_id, artifact],
                start_to_close_timeout=_EXECUTE_TIMEOUT,
                heartbeat_timeout=timedelta(seconds=10),
                retry_policy=_EXECUTE_RETRY,
            )
            self._end("executor")

            self._begin("summarizer")
            summary = await workflow.execute_activity(
                summarize_activity,
                args=[ri.run_id, sandbox_result],
                start_to_close_timeout=_SHORT,
                retry_policy=_LIGHT_RETRY,
            )
            self._end("summarizer")

            self._status = "completed"
            return RunResult(
                run_id=ri.run_id, status="completed",
                summary=summary, plan=plan, sandbox=sandbox_result,
            )
        except Exception:
            self._status = "failed"
            if self._current_step:
                self._end(self._current_step, "failed")
            raise

    @workflow.query
    def status(self) -> dict:
        return {"status": self._status, "current_step": self._current_step, "steps": self._steps}
