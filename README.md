# Sensei

Sensei is a learner-directed math and chemistry tutor. It uses a hosted
Responses-compatible LLM API for tutoring and problem generation while keeping the
learner profile, attempts, mastery, XP, misconceptions, and review schedule in the
existing local SQLite database.

Repository: [GizmosGarage/Sensei](https://github.com/GizmosGarage/Sensei)

## Architecture

- `data/sensei.db` remains the default and only durable learning store.
- The dashboard remains loopback-only at `http://127.0.0.1:8765/`.
- LLM requests go to the configured hosted Responses API.
- API credentials are read from a local `.env` file or process environment variables
  and are never saved to SQLite or committed to the repository.
- Deterministic SymPy checks remain the correctness boundary for supported math.
- The API is called with remote response storage disabled.

The current default is OpenAI's `gpt-5.4-mini`, but both the model name and API base
URL are configurable for another Responses-compatible service.

## Setup

Sensei requires Python 3.11 or newer and an API key. Install the project:

```powershell
python -m pip install -e .
```

For OpenAI, copy the local configuration template and add your key to `.env`:

```powershell
Copy-Item .env.example .env
```

```dotenv
OPENAI_API_KEY=your-api-key
SENSEI_LLM_MODEL=gpt-5.6-sol
SENSEI_LLM_BASE_URL=https://api.openai.com/v1
```

Sensei loads `.env` from the directory where it is started. The file is ignored by
Git. Existing process environment variables take precedence over values in `.env`.
You can therefore still set a key for one PowerShell session with
`$env:OPENAI_API_KEY = "your-api-key"`.

Sensei also accepts `SENSEI_LLM_API_KEY`. Optional connection overrides are:

```powershell
$env:SENSEI_LLM_MODEL = "gpt-5.4-mini"
$env:SENSEI_LLM_BASE_URL = "https://api.openai.com/v1"
```

The key is required at startup. Sensei exits with a clear error when neither
`SENSEI_LLM_API_KEY` nor `OPENAI_API_KEY` is available from `.env` or the process
environment.

## Run

Start the terminal tutor:

```powershell
python -m sensei
```

Start the browser dashboard:

```powershell
python -m sensei.dashboard
```

Choose a different API model or endpoint without changing source code:

```powershell
python -m sensei.dashboard --model "gpt-5.4-mini" --api-base-url "https://api.openai.com/v1"
```

The dashboard lets a learner name a subject, topic, and practice instructions. The
configured LLM drafts and reviews one problem at a time, while protected answer keys
stay in the dashboard process until the attempt is checked and recorded. Every Atlas
topic also has two confirmed data controls: **Restart** clears that topic's attempts,
mastery, misconceptions, review progress, and earned XP while keeping the topic in the
Atlas; **Delete** removes the topic and its topic-specific learning data from the active
database.

During a generated problem, **Ask Sensei for help** reveals one solution step at a
time. Each request lowers the available XP and mastery evidence; reaching the final
answer makes both rewards zero for that attempt.

The terminal supports `/quest`, `/answer`, `/hint`, `/solve`, `/done`, `/profile`,
`/skills`, `/review`, `/new`, `/status`, `/errors`, `/export`, `/backup`,
`/delete-data`, `/help`, and `/quit`.

## Local data

Existing learner data needs no migration. The default database remains
`data/sensei.db`, and `data/` remains excluded from Git. Use `--database PATH` to
select another SQLite file.

The terminal provides:

- `/export [path]` to create a JSON export.
- `/backup [path]` to create a SQLite backup.
- `/delete-data` to clear learning records only after an exact confirmation.

Running tests uses temporary databases and does not modify `data/sensei.db`.

## Documentation

- [API setup](docs/API_SETUP.md)
- [Terminal tutor](docs/TEXT_TUTOR.md)
- [Dashboard](docs/LOCAL_DASHBOARD.md)
- [Learning memory and progression](docs/LEARNING_MEMORY.md)
- [Deterministic verification](docs/DETERMINISTIC_VERIFICATION.md)
- [Review quests](docs/REVIEW_QUESTS.md)
- [Precalculus path](docs/PRECALCULUS.md)
- [Structured error log](docs/ERROR_LOG.md)
- [Architecture decisions](docs/decisions)
