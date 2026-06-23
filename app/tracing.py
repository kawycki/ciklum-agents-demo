"""Langfuse-style structured tracing to a per-run JSONL sink.
"""
from __future__ import annotations

import json
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from app import config

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def trace_file(run_id: str) -> Path:
    return config.TRACES_DIR / f"{run_id}.jsonl"


def _emit(run_id: str, event: dict[str, Any]) -> None:
    config.TRACES_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, default=str)
    with _lock:
        with open(trace_file(run_id), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()


def trace_create(
    run_id: str,
    *,
    name: str,
    tenant_id: str,
    input: Any = None,
    output: Any = None,
    status: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Create or upsert the run-level trace.
    """
    body: dict[str, Any] = {
        "id": run_id,
        "name": name,
        "userId": tenant_id,
        "timestamp": _now(),
        "metadata": {**(metadata or {}), **({"status": status} if status else {})},
    }
    if input is not None:
        body["input"] = input
    if output is not None:
        body["output"] = output
    _emit(run_id, {"id": _new_id(), "type": "trace-create", "timestamp": _now(), "body": body})


class _Span:
    """Mutable handle for a span; set `.output`/`.metadata`/`.status_message`."""

    def __init__(self) -> None:
        self.output: Any = None
        self.metadata: dict[str, Any] = {}
        self.level: str = "DEFAULT"
        self.status_message: str = ""


@contextmanager
def span(
    run_id: str,
    name: str,
    *,
    input: Any = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Iterator[_Span]:
    """Record a workflow step as a Langfuse span observation."""
    obs_id = _new_id()
    start = _now()
    _emit(
        run_id,
        {
            "id": _new_id(),
            "type": "span-create",
            "timestamp": start,
            "body": {
                "id": obs_id,
                "traceId": run_id,
                "name": name,
                "startTime": start,
                "input": input,
                "metadata": metadata or {},
            },
        },
    )
    handle = _Span()
    try:
        yield handle
    except Exception as exc:
        _emit(
            run_id,
            {
                "id": _new_id(),
                "type": "span-update",
                "timestamp": _now(),
                "body": {
                    "id": obs_id,
                    "traceId": run_id,
                    "name": name,
                    "endTime": _now(),
                    "level": "ERROR",
                    "statusMessage": f"{type(exc).__name__}: {exc}",
                    "metadata": handle.metadata,
                },
            },
        )
        raise
    else:
        _emit(
            run_id,
            {
                "id": _new_id(),
                "type": "span-update",
                "timestamp": _now(),
                "body": {
                    "id": obs_id,
                    "traceId": run_id,
                    "name": name,
                    "endTime": _now(),
                    "output": handle.output,
                    "level": handle.level,
                    "statusMessage": handle.status_message,
                    "metadata": handle.metadata,
                },
            },
        )
