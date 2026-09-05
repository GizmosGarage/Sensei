# Sensei

Sensei turns your study guide into a starting point for learning. Upload a PDF or
photo, or paste text, review the extracted concepts, and let Sensei choose a check-in.
It remembers mistakes and help used, offers guided explanations, and revisits gaps
with independent practice.

## Setup and run

Requires Python 3.11+ and a hosted Responses-compatible model API.

```powershell
python -m pip install -e .
```

Copy `.env.example` to `.env` if you have not configured it yet, and add your API key.
Then run either command from this directory:

```powershell
python -m sensei
python -m sensei.dashboard
```

Both start the same study dashboard at `http://127.0.0.1:8765/`.
Use `--no-open` to start without opening a browser.

## Learning flow

1. Upload a guide or paste its text.
2. Review the extracted concepts and examples; choose **Use this guide**.
3. Start the recommended check-in. Unseen concepts are unknown, not assumed weak.
4. Answers save automatically. Continue with Sensei for the next check, explanation,
   or review within that guide.
5. After a lesson, practice independently. Expand the guide's learning-memory panel
   to see possible misconceptions and which concepts have been checked.

The first version checks structured math and chemistry answers. Recommendations
use saved evidence; they are not a validated diagnostic or exam-readiness score.

## Local data

The new app starts empty in `data/study.db`; it does not import the old RPG database.
There are no seeded courses, quests, XP, ranks, terminal tutor, or topic-management
routes. Guide concepts are internal units for remembering learning evidence.

Uploads are sent to the configured model and are not stored as files. Accepted
concepts, extracted examples, attempts, misconceptions, and lessons stay in SQLite.
Requests disable remote response storage. API credentials stay in `.env` or process
environment variables. Local errors go to `data/logs/study-errors.jsonl`.

`--database PATH` selects a different fresh database. The old schema is intentionally
unsupported. Tests use temporary databases and do not change learner data.

## Verification

```powershell
python -m unittest discover -s tests -v
```

See [API setup](docs/API_SETUP.md), [Dashboard](docs/LOCAL_DASHBOARD.md),
[Learning memory](docs/LEARNING_MEMORY.md), and [Verification](docs/DETERMINISTIC_VERIFICATION.md).
