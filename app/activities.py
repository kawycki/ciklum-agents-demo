"""Temporal activities: the side-effecting steps of the pipeline.

Each activity wraps one agent (or the sandbox) and records a Langfuse span.
Activities are where all non-determinism lives (I/O, the subprocess that boots
the microVM, tracing writes) — the workflow itself stays deterministic.
"""
from __future__ import annotations

import asyncio

from temporalio import activity

from app import agents, sandbox, tracing
from app.dto import CodeArtifact, Plan, RunInput, SandboxResult, Summary


def _attempt_meta() -> dict:
    info = activity.info()
    return {"temporal_attempt": info.attempt, "activity": info.activity_type}


@activity.defn(name="plan")
async def plan_activity(run_input: RunInput) -> Plan:
    with tracing.span(run_input.run_id, "planner", input={"task": run_input.task}, metadata=_attempt_meta()) as sp:
        plan = agents.plan(run_input)
        sp.output = {"objective": plan.objective, "steps": plan.steps}
        return plan


@activity.defn(name="code")
async def code_activity(run_input: RunInput, plan: Plan) -> CodeArtifact:
    with tracing.span(run_input.run_id, "coder", input={"plan_steps": plan.steps}, metadata=_attempt_meta()) as sp:
        artifact = agents.code(plan, run_input)
        sp.output = {"code_preview": artifact.code[:500]}
        return artifact


@activity.defn(name="execute")
async def execute_activity(run_id: str, artifact: CodeArtifact) -> SandboxResult:
    span_input = {"code_preview": artifact.code[:500], "input": artifact.input}
    with tracing.span(run_id, "executor (firecracker microVM)", input=span_input, metadata=_attempt_meta()) as sp:
        # Run the microVM as a task and heartbeat while it works, so Temporal
        # detects a worker crash within heartbeat_timeout and retries promptly.
        task = asyncio.ensure_future(sandbox.run_payload(artifact.code, artifact.input))
        while True:
            done, _ = await asyncio.wait({task}, timeout=2)
            if done:
                break
            activity.heartbeat()
        result = task.result()
        sp.output = {
            "ok": result.ok, "exit_code": result.exit_code,
            "guest_timed_out": result.guest_timed_out, "host_timed_out": result.host_timed_out,
            "duration_ms": result.duration_ms, "stdout_preview": result.stdout[:500],
        }
        if not result.ok:
            sp.level = "WARNING"
            sp.status_message = result.error or f"exit_code={result.exit_code}"
        return result


@activity.defn(name="summarize")
async def summarize_activity(run_id: str, result: SandboxResult) -> Summary:
    with tracing.span(run_id, "summarizer", input={"exit_code": result.exit_code}, metadata=_attempt_meta()) as sp:
        summary = agents.summarize(result)
        sp.output = {"success": summary.success, "answer_preview": summary.answer[:500]}
        return summary
