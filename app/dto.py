"""Typed payloads exchanged between the workflow and its activities.

These are plain dataclasses so Temporal's default JSON data converter can
serialize them into and out of workflow history without extra config.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RunInput:
    """Everything a single run is launched with."""

    run_id: str
    tenant_id: str
    task: str
    code: str  # the untrusted Python the "coder" agent hands to the sandbox
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class Plan:
    """Planner-agent output: how the run will be carried out."""

    objective: str
    steps: list[str]
    language: str
    notes: str = ""


@dataclass
class CodeArtifact:
    """Coder-agent output: the concrete payload bound for the sandbox."""

    entrypoint: str
    code: str
    language: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class SandboxResult:
    """Raw outcome of executing the payload inside the Firecracker microVM."""

    ok: bool  # did the payload run to completion (exit code captured)?
    boot_ok: bool  # did the microVM boot and the guest runner report back?
    exit_code: Optional[int]
    stdout: str
    stderr: str
    duration_ms: int
    guest_timed_out: bool
    host_timed_out: bool
    error: str = ""


@dataclass
class Summary:
    """Summarizer-agent output: the human-facing result of the run."""

    success: bool
    answer: str
    exit_code: Optional[int]
    duration_ms: int
    notes: str = ""


@dataclass
class RunResult:
    """Final value returned by the workflow."""

    run_id: str
    status: str  # "completed" | "failed"
    summary: Summary
    plan: Plan
    sandbox: SandboxResult
