"""Dataclass payloads passed between the workflow and its activities.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RunInput:
    run_id: str
    tenant_id: str
    task: str
    code: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class Plan:
    objective: str
    steps: list[str]


@dataclass
class CodeArtifact:
    code: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class SandboxResult:
    ok: bool
    boot_ok: bool
    exit_code: Optional[int]
    stdout: str
    stderr: str
    duration_ms: int
    guest_timed_out: bool
    host_timed_out: bool
    error: str = ""


@dataclass
class Summary:
    success: bool
    answer: str
    exit_code: Optional[int]
    duration_ms: int


@dataclass
class RunResult:
    run_id: str
    status: str  # "completed" | "failed"
    summary: Summary
    plan: Plan
    sandbox: SandboxResult
