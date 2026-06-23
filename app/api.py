"""Minimal API: initiate a run and stream its status.

  POST /runs              -> start a durable run, returns its id
  GET  /runs/{id}/stream  -> Server-Sent-Events: per-step traces + status, then result
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from temporalio.client import Client

from app import config, tracing
from app.dto import RunInput
from app.workflows import AgentRunWorkflow

_client: Optional[Client] = None


class RunRequest(BaseModel):
    task: str
    code: str = Field(..., description="Untrusted Python executed in the Firecracker sandbox")
    input: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str = "default"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = await Client.connect(config.TEMPORAL_ADDRESS, namespace=config.TEMPORAL_NAMESPACE)
    yield


app = FastAPI(title="agent-sandbox-service", lifespan=lifespan)


def client() -> Client:
    if _client is None:
        raise HTTPException(503, "temporal client not ready")
    return _client


def _to_jsonable(result):
    if dataclasses.is_dataclass(result) and not isinstance(result, type):
        return dataclasses.asdict(result)
    return result


@app.post("/runs")
async def start_run(req: RunRequest) -> dict:
    run_id = uuid.uuid4().hex
    tracing.trace_create(
        run_id, name="agent-run", tenant_id=req.tenant_id,
        input={"task": req.task, "code_preview": req.code[:500]}, status="running",
    )
    await client().start_workflow(
        AgentRunWorkflow.run,
        RunInput(run_id=run_id, tenant_id=req.tenant_id, task=req.task, code=req.code, input=req.input),
        id=run_id, task_queue=config.TASK_QUEUE,
    )
    return {"run_id": run_id, "workflow_id": run_id, "status": "running"}


@app.get("/runs/{run_id}/stream")
async def stream_run(run_id: str) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        handle = client().get_workflow_handle(run_id)
        path = tracing.trace_file(run_id)
        pos = 0
        while True:
            if path.exists():
                with open(path, encoding="utf-8", errors="replace") as fh:
                    fh.seek(pos)
                    for line in fh:
                        if line.strip():
                            yield f"event: trace\ndata: {line.strip()}\n\n"
                    pos = fh.tell()

            try:
                status = await handle.query(AgentRunWorkflow.status)
            except Exception as exc:
                yield f"event: status\ndata: {json.dumps({'status': 'unknown', 'error': str(exc)})}\n\n"
                await asyncio.sleep(0.5)
                continue
            yield f"event: status\ndata: {json.dumps(status)}\n\n"

            if status.get("status") in ("completed", "failed"):
                try:
                    out = _to_jsonable(await handle.result())
                except Exception as exc:
                    out = {"error": str(exc)}
                yield f"event: result\ndata: {json.dumps(out)}\n\n"
                yield "event: done\ndata: {}\n\n"
                return

            await asyncio.sleep(0.5)

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
