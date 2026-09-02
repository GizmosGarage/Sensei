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
- Study guides are analyzed once by the scanner model into a reviewable plan of
  skill-level topics; only the plan you create is stored. Class material (imported,
  pasted, or scanned problems) is stored per topic in SQLite and steers generation.
  Uploaded documents are never written to disk or SQLite.
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
SENSEI_SCANNER_MODEL=gpt-5.6-sol
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

`--scanner-model` (or `SENSEI_SCANNER_MODEL`) selects the model used only to read
uploaded class material; it must accept PDF and image inputs. It defaults to the
practice model.

The dashboard starts with a study guide. Upload an exam study guide, syllabus, review
sheet, or textbook section (PDF, photo, or pasted text) and Sensei returns a study
plan to review: the subject, a study-set name, a course profile, and skill-level
topics, each with a practice brief and example problems taken from the document.
Creating the plan builds the study set in the Atlas. **Train this topic** on any card
starts a practice chat; the configured LLM drafts and reviews one problem at a time,
while protected answer keys stay in the dashboard process until the attempt is
checked and recorded. Every Atlas
topic also has two confirmed data controls: **Restart** clears that topic's attempts,
mastery, misconceptions, review progress, and earned XP while keeping the topic in the
Atlas; **Delete** removes the topic and its topic-specific learning data from the active
database.

## Class-accurate practice

An imported study plan fills each topic's class material with the document's own
problems. Each Atlas topic also has a **Class material** panel. Paste real homework, quiz, or exam
problems (with their solutions when you have them), or upload a PDF or photo of a
page and let the scanner model transcribe the problems for review before saving. A
subject-level **course profile** records the professor's conventions. Every
generated problem is built to be isomorphic to one saved exemplar: the same
structure, method, notation, and difficulty with different numbers or scenario. The
independent reviewer sees the same exemplars and rejects drafts that are easier or
use a different method than the class examples.

Problems use the answer forms a class actually collects:

| Format | Learner enters | Checked by |
| --- | --- | --- |
| `expression` | one expression, or `DNE` | symbolic equivalence |
| `numeric` | a number, optionally with its unit | relative tolerance (default 1%) |
| `solution_set` | `2, -3` or `x = 2, x = -3`; `none` when there is no solution | order-independent symbolic match |
| `interval` | `(-oo, 1) U [3, oo)` | SymPy set equality |
| `point` | `(2, -5)`; several points separated by commas | order-independent match |
| `multiple_choice` | A, B, C, or D | exact key |
| `multi_part` | one answer per part (a), (b), (c) | each part separately; some right parts record a **partial** outcome |

Generation also receives a learner signal: the topic's mastery, its last five
outcomes, unresolved misconceptions, and a difficulty tier (`foundational`,
`standard`, `challenging`, `synthesis`) derived from them. When an answer is wrong
or partial, one short classification call names the likely mistake; it is stored
with the attempt, shown as "Sensei noticed", targeted by later problems, and
resolved after two independent correct answers in a row.

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
