"""Configuration"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).parent.parent

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")
TASK_QUEUE = os.environ.get("TASK_QUEUE", "agent-runs")

TRACES_DIR = Path(os.environ.get("TRACES_DIR", ROOT / "traces"))

FIRECRACKER_BIN = os.environ.get(
    "FIRECRACKER_BIN",
    "/home/kamwy/repos/misc/firecracker/build/cargo_target/"
    "x86_64-unknown-linux-musl/debug/firecracker",
)
KERNEL_IMAGE = Path(os.environ.get("KERNEL_IMAGE", ROOT / "images" / "vmlinux.bin"))
ROOTFS_IMAGE = Path(os.environ.get("ROOTFS_IMAGE", ROOT / "images" / "rootfs.ext4"))

SANDBOX_VCPUS = int(os.environ.get("SANDBOX_VCPUS", "1"))
SANDBOX_MEM_MIB = int(os.environ.get("SANDBOX_MEM_MIB", "256"))
SANDBOX_TIMEOUT_S = int(os.environ.get("SANDBOX_TIMEOUT_S", "30"))
SANDBOX_GUEST_TIMEOUT_S = int(os.environ.get("SANDBOX_GUEST_TIMEOUT_S", "20"))
