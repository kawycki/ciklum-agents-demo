#!/usr/bin/env python3
"""In-guest runner: run the untrusted payload as `nobody`, report JSON on the console."""
import json
import os
import pwd
import subprocess
import sys
import time

RESULT_START = "---FCRUN-RESULT-START---"
RESULT_END = "---FCRUN-RESULT-END---"
JOB = "/job"
RUN = "/tmp/run"


def emit(obj):
    sys.stdout.write("\n" + RESULT_START + "\n" + json.dumps(obj) + "\n" + RESULT_END + "\n")
    sys.stdout.flush()


def main():
    try:
        code = open(os.path.join(JOB, "payload.py")).read()
    except Exception as exc:
        emit({"ok": False, "exit_code": None, "stdout": "", "stderr": "",
              "duration_ms": 0, "timed_out": False, "error": f"cannot read payload: {exc}"})
        return
    try:
        input_obj = json.load(open(os.path.join(JOB, "input.json")))
    except Exception:
        input_obj = {}
    try:
        guest_timeout = int(open(os.path.join(JOB, "timeout")).read().strip())
    except Exception:
        guest_timeout = 20

    # Stage into writable tmpfs (the job disk is read-only).
    os.makedirs(RUN, exist_ok=True)
    open(os.path.join(RUN, "payload.py"), "w").write(code)
    open(os.path.join(RUN, "input.json"), "w").write(json.dumps(input_obj))
    os.chmod(RUN, 0o777)

    try:
        nobody = pwd.getpwnam("nobody")
    except Exception:
        nobody = None

    def drop_priv():
        if nobody is not None:
            os.setgroups([])
            os.setgid(nobody.pw_gid)
            os.setuid(nobody.pw_uid)

    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": RUN, "TMPDIR": RUN,
           "PYTHONDONTWRITEBYTECODE": "1", "INPUT_JSON": os.path.join(RUN, "input.json")}
    start = time.time()
    try:
        proc = subprocess.run(
            ["/usr/local/bin/python3", os.path.join(RUN, "payload.py")],
            cwd=RUN, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=guest_timeout, preexec_fn=drop_priv,
        )
        emit({"ok": True, "exit_code": proc.returncode,
              "stdout": proc.stdout.decode("utf-8", "replace")[:200000],
              "stderr": proc.stderr.decode("utf-8", "replace")[:50000],
              "duration_ms": int((time.time() - start) * 1000), "timed_out": False, "error": ""})
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or b""
        emit({"ok": False, "exit_code": None,
              "stdout": (out.decode("utf-8", "replace") if isinstance(out, (bytes, bytearray)) else str(out))[:200000],
              "stderr": "[guest] payload exceeded its time budget",
              "duration_ms": int((time.time() - start) * 1000), "timed_out": True, "error": ""})
    except Exception as exc:
        emit({"ok": False, "exit_code": None, "stdout": "", "stderr": "",
              "duration_ms": int((time.time() - start) * 1000), "timed_out": False, "error": f"runner error: {exc}"})


main()
