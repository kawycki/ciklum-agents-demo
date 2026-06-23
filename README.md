# ciklum temporal demo
A demo service that runs a example **multi-agent system as a durable Temporal workflow**,
where the one untrusted step — executing code — runs inside an
**isolated Firecracker microVM with no host network access**. Each step emits a
**Langfuse-style structured trace**, and a minimal HTTP API starts runs and
streams their status.

**It has been run and tested in WSL environment**

## Prerequisities

1. Firecracker binary. It was build and setup according to the documentation - https://github.com/firecracker-microvm/firecracker#getting-started

2. FIRECRACKER_BIN in ('app/config.py') set to binary built in previous step

## The multi-agent pipeline

A run flows through four agents, each a Temporal **activity**:

**currently these activities are mocks. They should be replaced with real LLM calls.**

1. **planner** — turns the task into a plan.
2. **coder** — produces the concrete code payload to execute.
3. **executor** — **the untrusted step**: runs the payload inside a Firecracker
   microVM and captures its output.
4. **summarizer** — turns the raw execution output into the final answer.

## Isolation model

The executor activity (`app/sandbox.py`) launches a fresh Firecracker microVM


| Layer | Control |
| --- | --- |
| **No host network** | We **never** configure a `/network-interfaces` device, so the guest has no NIC. |
| **Hardware-virtualized boundary** | Code runs in a separate kernel/VM under KVM, not just a namespace. |
| **Read-only shared rootfs** | The root drive is attached `is_read_only: true` at the **block layer**, |
| **Single-use job disk** | The payload enters on a per-run ext4 disk built rootless with `mke2fs -d`, attached read-only, and destroyed after the run. Input goes in; nothing persists. |
| **In-guest privilege drop** | `init` (PID 1) runs the payload as the unprivileged `nobody` user. |
| **Resource caps** | The VM is capped to 1 vCPU / 256 MiB and bounded by the host + in-guest timeouts; the microVM itself is the resource limit. |
| **Seccomp** | Firecracker's built-in seccomp filter. |
| **Result channel** | |

## Retry & timeout strategy

Everything is bounded at two levels and retried where it's safe to do so.

**Timeouts**

(TODO)

**Retries** (Temporal `RetryPolicy` per activity)

(TODO)

**Durability & resumability** come from Temporal: every activity result is
persisted to workflow history.

- The dev server runs with `--db-filename ./temporal.db`, so workflow history is
  **persisted to disk and survives a Temporal server restart** — a completed or
  in-flight run is still there after the server comes back.

## Tracing (Langfuse-style)

(TODO)

## API

| Method & path | Purpose |
| --- | --- |
| `POST /runs` | Start a run. Body: `{task, code, input?, tenant_id?}`. Returns `{run_id, workflow_id, status}`. |
| `GET /runs/{id}/stream` | Server-Sent-Events: `trace` (each Langfuse span), `status` (step progression), then `result` and `done`. |

## Running it

(TODO)

### Known limitations (local demo)

(TODO)

- Currenlty runs the bare `firecracker` binary
- Agents are deterministic stand-ins (see scoping note above).
- The Temporal dev server persists to a local SQLite file (survives restart);
  use a multi-node persistent cluster for HA in production.
