"""Temporal worker: hosts the workflow and activities on the task queue.

Run several of these for capacity/HA — Temporal load-balances tasks across
them and a crash mid-run is recovered by whichever worker picks up the history.
"""
from __future__ import annotations

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from app import config
from app.activities import (
    code_activity,
    execute_activity,
    plan_activity,
    summarize_activity,
)
from app.workflows import AgentRunWorkflow

# These modules only run inside activities (or hold plain config) and use
# host facilities the workflow sandbox would otherwise flag. Pass them through
# so they are not re-imported in the sandbox; the workflow module itself stays
# sandboxed for determinism checking.
_PASSTHROUGH = (
    "app.config", "app.dto", "app.agents",
    "app.activities", "app.sandbox", "app.tracing",
)


async def main() -> None:
    client = await Client.connect(config.TEMPORAL_ADDRESS, namespace=config.TEMPORAL_NAMESPACE)
    runner = SandboxedWorkflowRunner(
        restrictions=SandboxRestrictions.default.with_passthrough_modules(*_PASSTHROUGH)
    )
    worker = Worker(
        client,
        task_queue=config.TASK_QUEUE,
        workflows=[AgentRunWorkflow],
        activities=[plan_activity, code_activity, execute_activity, summarize_activity],
        workflow_runner=runner,
    )
    print(f"worker running: task_queue={config.TASK_QUEUE} address={config.TEMPORAL_ADDRESS}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
