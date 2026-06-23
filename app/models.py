"""Pydantic models for the HTTP API surface."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    task: str = Field(..., description="Human description of what the run should accomplish")
    code: str = Field(..., description="Untrusted Python executed in the Firecracker sandbox")
    input: dict[str, Any] = Field(default_factory=dict, description="JSON input exposed to the code")
    tenant_id: str = Field(default="default", description="Caller/tenant identity for isolation & tracing")


class StartRunResponse(BaseModel):
    run_id: str
    workflow_id: str
    status: str
