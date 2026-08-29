# Terminal tutor

The terminal tutor combines a hosted Responses-compatible LLM with local SQLite
learning memory and deterministic mathematical verification.

## Start

```powershell
$env:OPENAI_API_KEY = "your-api-key"
python -m sensei
```

For one-shot use:

```powershell
python -m sensei --prompt "Evaluate lim_(x->0) sin(x)/x" --mode hint
```

Connection options are `--model NAME` and `--api-base-url URL`. Storage options
include `--database PATH` and `--no-memory`. Use `--no-stream` when complete
responses should be printed at once.

## Commands

| Command | Purpose |
| --- | --- |
| `/quest` | Start the next verifier-backed review quest. |
| `/answer EXPR` | Check an answer to the active quest. |
| `/hint [question]` | Request one bounded hint. |
| `/solve [question]` | Request a complete walkthrough. |
| `/check TYPE` | Run a deterministic derivative, limit, antiderivative, or equivalence check. |
| `/done [outcome]` | Validate and record the current learning event. |
| `/profile` | Show level, XP, attempts, and mastery totals. |
| `/skills [all]` | Show practiced skills or the full catalog. |
| `/review` | Show the next scheduled review. |
| `/new [problem]` | Clear the transient problem context. |
| `/status` | Show the hosted model and bounded context usage. |
| `/errors` | Show the structured error-log path. |
| `/export [path]` | Create a new JSON export. |
| `/backup [path]` | Create a new SQLite backup. |
| `/delete-data` | Clear learning records after an exact confirmation. |
| `/quit` | Exit Sensei. |

## Context and storage

Each LLM request contains one system policy, the current problem, and at most 12,000
characters of recent exchanges. Starting a new problem clears transient history.

Long-term skills, attempts, misconceptions, mastery, review dates, and XP stay in
`data/sensei.db`. A small relevant summary can be added to a tutoring request so
instruction adapts to the learner. Raw transcripts are not written to learning
memory.

The provider calls `POST /responses`, supports streaming text events, requests JSON
mode for structured extraction, and disables remote response storage. See
[API setup](API_SETUP.md).
