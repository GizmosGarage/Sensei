# Local error log

Sensei keeps a durable, structured record of application failures at:

```text
data/logs/sensei-errors.jsonl
```

The file is local, ignored by Git, and written only when something fails. Each line
is a complete JSON object, so it can be read one record at a time even if the
application stops abruptly. Every record includes:

- a unique `error_id` shown with user-facing terminal and dashboard failures;
- a UTC timestamp, severity, component, and operation;
- the exception type, message, chained traceback, process, and thread;
- bounded diagnostic context such as the dashboard route or verification kind.

Raw answers and HTTP request bodies are deliberately excluded from diagnostic
context. Exception messages and browser stack traces can still contain technical
details, so the error log remains personal local data and should be reviewed before
sharing it.

## Coverage

The terminal records startup, model/provider, verification, quest, learning-memory,
and unexpected application failures. Use `/errors` to print the active path.

The dashboard records startup and server failures, rejected or failed API actions,
generation-validation failures, and JavaScript errors. Browser errors that occur
while the local server is temporarily unreachable are queued locally (up to 25)
and submitted after the dashboard reconnects. Incorrect student answers are normal
learning outcomes and are not application errors.

The managed `llama.cpp` process continues to write its detailed runtime output to
`data/runtime/llama-server.log`; related Sensei errors point there when appropriate.

## Configuration and retention

Both entry points accept a different path:

```powershell
python -m sensei --error-log D:\logs\sensei-errors.jsonl
python -m sensei.dashboard --error-log D:\logs\sensei-errors.jsonl
```

The active file rotates at 5 MiB. Ten archives are retained beside it as
`sensei-errors.jsonl.1` through `sensei-errors.jsonl.10`, with `.1` being the newest.
Logging is best-effort: if the log itself cannot be written, Sensei reports that on
stderr without hiding the original failure.

To inspect the newest entries in PowerShell:

```powershell
Get-Content data\logs\sensei-errors.jsonl -Tail 20 |
  ForEach-Object { $_ | ConvertFrom-Json } |
  Format-List timestamp,error_id,component,operation,message
```
