"""The multi-agent pipeline's individual agents.

These are deterministic stand-ins for what would otherwise be LLM-backed
agents. They are intentionally simple: the focus of this service is the
*durable orchestration* of the pipeline and the *isolation* of the one
untrusted step (execution), not the sophistication of the agents themselves.
Each function is pure so it can run inside a Temporal activity and be retried
safely.
"""
from __future__ import annotations

from app.dto import CodeArtifact, Plan, RunInput, SandboxResult, Summary


def plan(run_input: RunInput) -> Plan:
    """Planner agent: decompose the task into an executable plan."""
    return Plan(
        objective=run_input.task,
        steps=[
            "validate and prepare the requested code",
            "execute the code inside an isolated, network-less microVM",
            "summarize the execution output for the caller",
        ],
        language="python",
        notes="execution is delegated to a Firecracker sandbox with no host network",
    )


def code(plan: Plan, run_input: RunInput) -> CodeArtifact:
    """Coder agent: turn the plan into the concrete payload to execute.

    Here the untrusted code is supplied on the run request; the coder agent
    normalizes it and binds the run input. (Swapping in an LLM that *writes*
    the code would change only this function.)
    """
    src = (run_input.code or "").strip()
    if not src:
        raise ValueError("no code to execute: run request carried an empty payload")
    return CodeArtifact(
        entrypoint="payload.py",
        code=src,
        language="python",
        input=run_input.input,
    )


def summarize(sandbox: SandboxResult) -> Summary:
    """Summarizer agent: produce the human-facing result from raw output."""
    success = sandbox.ok and sandbox.exit_code == 0 and not sandbox.guest_timed_out
    if not sandbox.boot_ok:
        answer = f"execution environment failed: {sandbox.error or 'microVM did not report back'}"
    elif sandbox.host_timed_out:
        answer = "execution exceeded the host time budget and was terminated"
    elif sandbox.guest_timed_out:
        answer = "the code exceeded its in-sandbox time budget and was terminated"
    elif success:
        answer = sandbox.stdout.strip() or "(the code produced no output)"
    else:
        answer = (
            f"the code exited with status {sandbox.exit_code}\n"
            f"{sandbox.stderr.strip()}"
        ).strip()
    return Summary(
        success=success,
        answer=answer,
        exit_code=sandbox.exit_code,
        duration_ms=sandbox.duration_ms,
        notes="" if success else "see stderr / status above",
    )
