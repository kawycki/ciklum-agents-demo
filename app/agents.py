"""The pipeline's agents: deterministic stand-ins for LLM-backed agents.

The focus is the durable orchestration and the isolation of the untrusted
step, not agent quality. Swapping in a real model touches only this file.
"""
from __future__ import annotations

from app.dto import CodeArtifact, Plan, RunInput, SandboxResult, Summary


def plan(run_input: RunInput) -> Plan:
    return Plan(
        objective=run_input.task,
        steps=["prepare code", "execute in isolated network-less microVM", "summarize output"],
    )


def code(plan: Plan, run_input: RunInput) -> CodeArtifact:
    src = (run_input.code or "").strip()
    if not src:
        raise ValueError("empty code payload")
    return CodeArtifact(code=src, input=run_input.input)


def summarize(sandbox: SandboxResult) -> Summary:
    success = sandbox.ok and sandbox.exit_code == 0 and not sandbox.guest_timed_out
    if not sandbox.boot_ok:
        answer = f"execution environment failed: {sandbox.error or 'microVM did not report back'}"
    elif sandbox.host_timed_out:
        answer = "execution exceeded the host time budget and was terminated"
    elif sandbox.guest_timed_out:
        answer = "the code exceeded its in-sandbox time budget and was terminated"
    elif success:
        answer = sandbox.stdout.strip() or "(no output)"
    else:
        answer = f"the code exited with status {sandbox.exit_code}\n{sandbox.stderr.strip()}".strip()
    return Summary(
        success=success, answer=answer,
        exit_code=sandbox.exit_code, duration_ms=sandbox.duration_ms,
    )
