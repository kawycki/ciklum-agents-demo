"""Run an untrusted payload inside a single-use Firecracker microVM.

Isolation properties enforced here:
  * **No host network** — we never configure a network interface, so the guest
    has no NIC and cannot reach the host or anything else.
  * **Read-only shared rootfs** — the root drive is attached `is_read_only`, so
    a malicious guest cannot tamper with the image other tenants reuse.
  * **Single-use job disk** — the payload enters on a per-run ext4 disk
    (also read-only to the guest) that is destroyed afterwards.
  * **Hard timeout** — the whole VM (and its process group) is SIGKILLed past
    the host wall-clock budget; an inner guest timeout bounds the payload too.
  * Firecracker's built-in seccomp filter is on by default; the guest further
    drops to an unprivileged user with rlimits (see the guest runner).

The Firecracker REST API is driven over its unix socket with a tiny inline
HTTP client so the module has no extra dependency and we get block-level
control (read-only root) that `firectl` does not expose.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from app import config
from app.dto import SandboxResult

# Markers the in-guest runner wraps its JSON result with (kept in sync with
# sandbox/guest_runner.py). Unique enough not to collide with kernel logs.
RESULT_START = "---FCRUN-RESULT-START---"
RESULT_END = "---FCRUN-RESULT-END---"


class SandboxError(Exception):
    """Infrastructure-level failure (treated as retryable by the activity)."""


# --------------------------------------------------------------------------
# Minimal async HTTP client over the Firecracker API unix socket.
# --------------------------------------------------------------------------
async def _api(sock: Path, method: str, path: str, body: Optional[dict[str, Any]] = None) -> None:
    reader, writer = await asyncio.open_unix_connection(path=str(sock))
    payload = b"" if body is None else json.dumps(body).encode()
    head = [
        f"{method} {path} HTTP/1.1",
        "Host: localhost",
        "Accept: application/json",
        "Connection: close",
    ]
    if body is not None:
        head += ["Content-Type: application/json", f"Content-Length: {len(payload)}"]
    writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + payload)
    await writer.drain()

    # Read exactly one response (headers, then Content-Length bytes). Firecracker
    # keeps the connection open, so reading until EOF would block forever.
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = await reader.read(4096)
        if not chunk:
            break
        buf += chunk
    header_blob, _, rest = buf.partition(b"\r\n\r\n")
    lines = header_blob.split(b"\r\n")
    status_line = lines[0].decode("latin1", "replace")
    sl_parts = status_line.split(" ", 2)
    status = int(sl_parts[1]) if len(sl_parts) > 1 and sl_parts[1].isdigit() else 0
    clen = 0
    for h in lines[1:]:
        if h.lower().startswith(b"content-length:"):
            clen = int(h.split(b":", 1)[1].strip() or b"0")
    body = rest
    while len(body) < clen:
        chunk = await reader.read(clen - len(body))
        if not chunk:
            break
        body += chunk
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    if not (200 <= status < 300):
        raise SandboxError(f"firecracker API {method} {path} -> {status_line!r}; body={body[-400:]!r}")


async def _wait_for_socket(sock: Path, proc: asyncio.subprocess.Process) -> None:
    for _ in range(200):  # up to ~4s
        if sock.exists():
            return
        if proc.returncode is not None:
            raise SandboxError(f"firecracker exited before opening API socket (rc={proc.returncode})")
        await asyncio.sleep(0.02)
    raise SandboxError("firecracker API socket never appeared")


# --------------------------------------------------------------------------
# Job disk: pack the payload into a small read-only ext4 image (rootless).
# --------------------------------------------------------------------------
async def _run(cmd: list[str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out, _ = await proc.communicate()
    return proc.returncode, out.decode("utf-8", "replace")


async def _build_job_disk(workdir: Path, code: str, input_obj: dict[str, Any], guest_timeout_s: int) -> Path:
    job_dir = workdir / "job"
    job_dir.mkdir()
    (job_dir / "payload.py").write_text(code, encoding="utf-8")
    (job_dir / "input.json").write_text(json.dumps(input_obj), encoding="utf-8")
    (job_dir / "timeout").write_text(str(guest_timeout_s), encoding="utf-8")
    # Host-controlled rlimits the guest runner applies to the untrusted payload.
    (job_dir / "limits.json").write_text(json.dumps({
        "cpu_s": config.SANDBOX_RLIMIT_CPU_S,
        "as_mib": config.SANDBOX_RLIMIT_AS_MIB,
        "fsize_mib": config.SANDBOX_RLIMIT_FSIZE_MIB,
        "nproc": config.SANDBOX_RLIMIT_NPROC,
    }), encoding="utf-8")
    img = workdir / "job.ext4"
    rc, out = await _run(["mke2fs", "-q", "-F", "-t", "ext4", "-d", str(job_dir), str(img), "16M"])
    if rc != 0:
        raise SandboxError(f"failed to build job disk: {out}")
    return img


def _parse_result(console: str) -> Optional[dict[str, Any]]:
    # Kernel printk shares the serial console with the guest's stdout and can
    # interleave mid-line. Strip "[   12.345678] ..." fragments so split markers
    # and the (single-line) JSON result rejoin cleanly.
    console = re.sub(r"\[\s*\d+\.\d+\][^\n]*\n?", "", console)
    start = console.rfind(RESULT_START)
    end = console.rfind(RESULT_END)
    if start == -1 or end == -1 or end < start:
        return None
    blob = console[start + len(RESULT_START) : end].strip()
    try:
        return json.loads(blob)
    except Exception:
        return None


# --------------------------------------------------------------------------
# Public entry point.
# --------------------------------------------------------------------------
async def run_payload(
    code: str,
    input_obj: dict[str, Any],
    *,
    vcpus: int = config.SANDBOX_VCPUS,
    mem_mib: int = config.SANDBOX_MEM_MIB,
    host_timeout_s: int = config.SANDBOX_TIMEOUT_S,
    guest_timeout_s: int = config.SANDBOX_GUEST_TIMEOUT_S,
) -> SandboxResult:
    for label, p in (("firecracker binary", config.FIRECRACKER_BIN), ("kernel", config.KERNEL_IMAGE), ("rootfs", config.ROOTFS_IMAGE)):
        if not Path(p).exists():
            raise SandboxError(f"{label} not found at {p}; build/fetch images first")

    workdir = Path(tempfile.mkdtemp(prefix="fcjob-"))
    sock = workdir / "fc.sock"
    console_path = workdir / "console.log"
    proc: Optional[asyncio.subprocess.Process] = None
    started = time.monotonic()
    host_timed_out = False
    try:
        job_img = await _build_job_disk(workdir, code, input_obj, guest_timeout_s)

        console = open(console_path, "wb")
        # Launch firecracker; the guest serial console (ttyS0) is wired to stdout.
        # start_new_session=True puts it in its own process group for clean kill.
        proc = await asyncio.create_subprocess_exec(
            str(config.FIRECRACKER_BIN), "--api-sock", str(sock),
            stdout=console, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL, start_new_session=True, cwd=str(workdir),
        )
        console.close()

        await _wait_for_socket(sock, proc)

        # reboot=k makes the guest reset via the i8042 controller, which
        # Firecracker traps to exit cleanly -- so we do NOT disable i8042.
        boot_args = (
            "console=ttyS0 loglevel=2 reboot=k panic=1 pci=off nomodules "
            "random.trust_cpu=on root=/dev/vda ro init=/init"
        )
        await _api(sock, "PUT", "/boot-source", {
            "kernel_image_path": str(config.KERNEL_IMAGE),
            "boot_args": boot_args,
        })
        await _api(sock, "PUT", "/machine-config", {
            "vcpu_count": vcpus, "mem_size_mib": mem_mib, "smt": False,
        })
        await _api(sock, "PUT", "/drives/rootfs", {
            "drive_id": "rootfs", "path_on_host": str(config.ROOTFS_IMAGE),
            "is_root_device": True, "is_read_only": True,
        })
        await _api(sock, "PUT", "/drives/job", {
            "drive_id": "job", "path_on_host": str(job_img),
            "is_root_device": False, "is_read_only": True,
        })
        # No /network-interfaces is ever configured -> the guest has no NIC.
        await _api(sock, "PUT", "/actions", {"action_type": "InstanceStart"})

        try:
            await asyncio.wait_for(proc.wait(), timeout=host_timeout_s)
        except asyncio.TimeoutError:
            host_timed_out = True
            _kill_group(proc)
            await proc.wait()

        # Read the console BEFORE the finally clause removes the workdir.
        elapsed_ms = int((time.monotonic() - started) * 1000)
        console_text = (
            console_path.read_text(encoding="utf-8", errors="replace")
            if console_path.exists() else ""
        )
    finally:
        if proc is not None and proc.returncode is None:
            _kill_group(proc)
        if os.environ.get("FCJOB_KEEP"):
            print(f"[sandbox] kept workdir: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)

    parsed = _parse_result(console_text)

    if parsed is None and not host_timed_out:
        # Booted but never reported a result: treat as a (retryable) infra fault.
        rc = proc.returncode if proc is not None else "n/a"
        tail = console_text[-1500:]
        raise SandboxError(
            f"microVM produced no result (boot/runner failure). "
            f"firecracker_rc={rc} console_bytes={len(console_text)}\nconsole tail:\n{tail}"
        )

    if parsed is None:  # host timeout killed it before it reported
        return SandboxResult(
            ok=False, boot_ok=True, exit_code=None, stdout="", stderr="",
            duration_ms=elapsed_ms, guest_timed_out=False, host_timed_out=True,
            error="killed after exceeding host time budget",
        )

    return SandboxResult(
        ok=bool(parsed.get("ok")),
        boot_ok=True,
        exit_code=parsed.get("exit_code"),
        stdout=parsed.get("stdout", ""),
        stderr=parsed.get("stderr", ""),
        duration_ms=parsed.get("duration_ms", elapsed_ms),
        guest_timed_out=bool(parsed.get("timed_out")),
        host_timed_out=host_timed_out,
        error=parsed.get("error", ""),
    )


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
