"""Central configuration, read from the environment with sane defaults.

Every tunable lives here so call sites stay declarative and the whole service
can be reconfigured (e.g. pointed at a different kernel or given tighter
sandbox limits) without touching code.
"""
from __future__ import annotations

import os
from pathlib import Path

# NB: avoid Path.resolve() here -- this module is imported by the workflow and
# resolve() is disallowed inside Temporal's workflow sandbox.
ROOT = Path(__file__).parent.parent

# --- Temporal -------------------------------------------------------------
TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")
TASK_QUEUE = os.environ.get("TASK_QUEUE", "agent-runs")

# --- Tracing (Langfuse-style JSONL sink) ----------------------------------
TRACES_DIR = Path(os.environ.get("TRACES_DIR", ROOT / "traces"))

# --- Firecracker ----------------------------------------------------------
_FC_DEFAULT_DIR = (
    "/home/kamwy/repos/misc/firecracker/build/cargo_target/"
    "x86_64-unknown-linux-musl/debug"
)
FIRECRACKER_BIN = os.environ.get("FIRECRACKER_BIN", f"{_FC_DEFAULT_DIR}/firecracker")
KERNEL_IMAGE = Path(os.environ.get("KERNEL_IMAGE", ROOT / "images" / "vmlinux.bin"))
ROOTFS_IMAGE = Path(os.environ.get("ROOTFS_IMAGE", ROOT / "images" / "rootfs.ext4"))

# --- Sandbox resource caps (applied per untrusted run) --------------------
SANDBOX_VCPUS = int(os.environ.get("SANDBOX_VCPUS", "1"))
SANDBOX_MEM_MIB = int(os.environ.get("SANDBOX_MEM_MIB", "256"))
# Host wall-clock budget: the whole microVM is SIGKILLed past this.
SANDBOX_TIMEOUT_S = int(os.environ.get("SANDBOX_TIMEOUT_S", "30"))
# In-guest budget for the payload itself (must be < host budget).
SANDBOX_GUEST_TIMEOUT_S = int(os.environ.get("SANDBOX_GUEST_TIMEOUT_S", "20"))
# Defence-in-depth rlimits applied to the untrusted payload inside the guest.
SANDBOX_RLIMIT_CPU_S = int(os.environ.get("SANDBOX_RLIMIT_CPU_S", "15"))
SANDBOX_RLIMIT_AS_MIB = int(os.environ.get("SANDBOX_RLIMIT_AS_MIB", "192"))
SANDBOX_RLIMIT_FSIZE_MIB = int(os.environ.get("SANDBOX_RLIMIT_FSIZE_MIB", "16"))
SANDBOX_RLIMIT_NPROC = int(os.environ.get("SANDBOX_RLIMIT_NPROC", "64"))
