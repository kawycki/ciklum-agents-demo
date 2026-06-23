"""Dataclass payloads passed between the workflow and its activities.

Plain dataclasses so Temporal's default JSON converter serializes them into
workflow history.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RunInput:
    run_id: str
    tenant_id: str
    task: str
    code: str  # the untrusted Python handed to the sandbox
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
    ok: bool            # payload ran to completion (exit code captured)
    boot_ok: bool       # microVM booted and the guest runner reported back
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
