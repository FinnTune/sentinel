# Sentinel

A CI-failure triage agent. When a CI run fails, Sentinel pulls the logs, finds the
root cause with Claude, and posts a diagnosis on the pull request.

| Component | Language | Role |
|-----------|----------|------|
| `gateway/` | Go | Webhook receiver, job queue, REST API |
| `logscan/` | Rust | Log parsing and error-window extraction |
| `agent/` | Python | Claude tool-use loop |
| `evals/` | Python | Golden-log evaluation harness |

Status: early scaffolding.
