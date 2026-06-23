"""Minimal API to initiate a run and stream its status.

  POST /runs              -> start a durable run, returns its id
  GET  /runs/{id}         -> current durable status (+ result once finished)
  GET  /runs/{id}/stream  -> Server-Sent-Events stream of step traces + status
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from temporalio.client import Client

from app import config, tracing
from app.dto import RunInput
from app.models import RunRequest, StartRunResponse
from app.workflows import AgentRunWorkflow

_client: Optional[Client] = None


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


@app.post("/runs", response_model=StartRunResponse)
async def start_run(req: RunRequest) -> StartRunResponse:
    run_id = uuid.uuid4().hex
    run_input = RunInput(
        run_id=run_id, tenant_id=req.tenant_id, task=req.task,
        code=req.code, input=req.input,
    )
    tracing.trace_create(
        run_id, name="agent-run", tenant_id=req.tenant_id,
        input={"task": req.task, "code_preview": req.code[:500]},
        status="running",
    )
    await client().start_workflow(
        AgentRunWorkflow.run, run_input, id=run_id, task_queue=config.TASK_QUEUE,
    )
    return StartRunResponse(run_id=run_id, workflow_id=run_id, status="running")


async def _query_status(run_id: str) -> dict:
    handle = client().get_workflow_handle(run_id)
    return await handle.query(AgentRunWorkflow.status)


@app.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    try:
        status = await _query_status(run_id)
    except Exception as exc:
        raise HTTPException(404, f"run not found or not queryable: {exc}")
    resp: dict = {"run_id": run_id, **status}
    if status.get("status") in ("completed", "failed"):
        try:
            result = await client().get_workflow_handle(run_id).result()
            resp["result"] = _to_jsonable(result)
        except Exception as exc:
            resp["error"] = str(exc)
    return resp


def _to_jsonable(result) -> dict:
    # Without a client-side type hint Temporal returns the decoded JSON (a dict);
    # if a dataclass instance is returned instead, convert it.
    if dataclasses.is_dataclass(result) and not isinstance(result, type):
        return dataclasses.asdict(result)
    return result


def _tenant_from_trace(run_id: str) -> str:
    path = tracing.trace_file(run_id)
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ev = json.loads(line)
                if ev.get("type") == "trace-create":
                    return ev["body"].get("userId", "default")
            except Exception:
                continue
    return "default"


def _already_finalized(run_id: str) -> bool:
    path = tracing.trace_file(run_id)
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
            if ev.get("type") == "trace-create" and "output" in ev.get("body", {}):
                return True
        except Exception:
            continue
    return False


@app.get("/runs/{run_id}/stream")
async def stream_run(run_id: str) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
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
                status = await _query_status(run_id)
            except Exception as exc:
                yield f"event: status\ndata: {json.dumps({'status': 'unknown', 'error': str(exc)})}\n\n"
                await asyncio.sleep(0.5)
                continue

            yield f"event: status\ndata: {json.dumps(status)}\n\n"

            if status.get("status") in ("completed", "failed"):
                await asyncio.sleep(0.2)  # let final spans flush
                if path.exists():
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        fh.seek(pos)
                        for line in fh:
                            if line.strip():
                                yield f"event: trace\ndata: {line.strip()}\n\n"
                        pos = fh.tell()

                out: dict = {}
                try:
                    result = await client().get_workflow_handle(run_id).result()
                    out = _to_jsonable(result)
                except Exception as exc:
                    out = {"error": str(exc)}
                if not _already_finalized(run_id):
                    tracing.trace_create(
                        run_id, name="agent-run", tenant_id=_tenant_from_trace(run_id),
                        output=out, status=status["status"],
                    )
                yield f"event: result\ndata: {json.dumps(out)}\n\n"
                yield "event: done\ndata: {}\n\n"
                return

            await asyncio.sleep(0.5)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
