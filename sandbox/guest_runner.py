#!/usr/bin/env python3
"""In-guest runner (PID-child of init) for the Firecracker sandbox.

Reads the untrusted payload + inputs + caps from the read-only /job disk, runs
the payload as the unprivileged `nobody` user under rlimits, and prints the
result as JSON between two markers on the serial console for the host to parse.
Kept deliberately dependency-free (stdlib only) so it runs on a minimal rootfs.
"""
import json
import os
import pwd
import resource
import subprocess
import sys
import time

RESULT_START = "---FCRUN-RESULT-START---"
RESULT_END = "---FCRUN-RESULT-END---"
JOB = "/job"
RUN = "/tmp/run"

DEFAULT_LIMITS = {"cpu_s": 15, "as_mib": 192, "fsize_mib": 16, "nproc": 64}


def emit(obj):
    sys.stdout.write("\n" + RESULT_START + "\n" + json.dumps(obj) + "\n" + RESULT_END + "\n")
    sys.stdout.flush()


def read_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return default


def main():
    try:
        with open(os.path.join(JOB, "payload.py")) as fh:
            code = fh.read()
    except Exception as exc:
        emit({"ok": False, "exit_code": None, "stdout": "", "stderr": "",
              "duration_ms": 0, "timed_out": False, "error": f"cannot read payload: {exc}"})
        return

    input_obj = read_json(os.path.join(JOB, "input.json"), {})
    limits = read_json(os.path.join(JOB, "limits.json"), DEFAULT_LIMITS)
    try:
        with open(os.path.join(JOB, "timeout")) as fh:
            guest_timeout = int(fh.read().strip())
    except Exception:
        guest_timeout = 20

    # Stage into writable tmpfs (the job disk is read-only).
    os.makedirs(RUN, exist_ok=True)
    with open(os.path.join(RUN, "payload.py"), "w") as fh:
        fh.write(code)
    with open(os.path.join(RUN, "input.json"), "w") as fh:
        fh.write(json.dumps(input_obj))
    os.chmod(RUN, 0o777)
    for name in ("payload.py", "input.json"):
        try:
            os.chmod(os.path.join(RUN, name), 0o644)
        except Exception:
            pass

    try:
        nobody = pwd.getpwnam("nobody")
    except Exception:
        nobody = None

    def preexec():
        # Defence-in-depth rlimits on top of the microVM's own caps.
        for res, val in (
            (resource.RLIMIT_CPU, limits.get("cpu_s", 15)),
            (resource.RLIMIT_AS, limits.get("as_mib", 192) * 1024 * 1024),
            (resource.RLIMIT_FSIZE, limits.get("fsize_mib", 16) * 1024 * 1024),
            (resource.RLIMIT_NPROC, limits.get("nproc", 64)),
            (resource.RLIMIT_CORE, 0),
        ):
            try:
                resource.setrlimit(res, (val, val))
            except Exception:
                pass
        # Drop to an unprivileged user so the payload cannot remount/escalate.
        if nobody is not None:
            try:
                os.setgroups([])
                os.setgid(nobody.pw_gid)
                os.setuid(nobody.pw_uid)
            except Exception:
                pass

    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": RUN,
        "TMPDIR": RUN,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "INPUT_JSON": os.path.join(RUN, "input.json"),
    }

    start = time.time()
    try:
        proc = subprocess.run(
            ["/usr/local/bin/python3", os.path.join(RUN, "payload.py")],
            cwd=RUN, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=guest_timeout, preexec_fn=preexec,
        )
        emit({
            "ok": True,
            "exit_code": proc.returncode,
            "stdout": proc.stdout.decode("utf-8", "replace")[:200000],
            "stderr": proc.stderr.decode("utf-8", "replace")[:50000],
            "duration_ms": int((time.time() - start) * 1000),
            "timed_out": False,
            "error": "",
        })
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or b""
        err = exc.stderr or b""
        emit({
            "ok": False,
            "exit_code": None,
            "stdout": (out.decode("utf-8", "replace") if isinstance(out, (bytes, bytearray)) else str(out))[:200000],
            "stderr": ((err.decode("utf-8", "replace") if isinstance(err, (bytes, bytearray)) else str(err)) + "\n[guest] payload exceeded its time budget")[:50000],
            "duration_ms": int((time.time() - start) * 1000),
            "timed_out": True,
            "error": "",
        })
    except Exception as exc:
        emit({"ok": False, "exit_code": None, "stdout": "", "stderr": "",
              "duration_ms": int((time.time() - start) * 1000), "timed_out": False,
              "error": f"runner error: {exc}"})


main()
