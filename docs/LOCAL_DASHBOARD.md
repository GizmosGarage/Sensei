# Local dashboard

Sensei's dashboard is a loopback-only web application. The page and API server run
on the learner's computer, learning memory stays in SQLite, and tutoring requests use
the configured hosted LLM API.

## Start

Set an API key, then run:

```powershell
$env:OPENAI_API_KEY = "your-api-key"
python -m sensei.dashboard
```

The default address is `http://127.0.0.1:8765/`. Available options are:

- `--database PATH`: select the local SQLite database.
- `--port PORT`: select the loopback port.
- `--no-open`: do not open a browser automatically.
- `--model NAME`: override the hosted model.
- `--scanner-model NAME`: set the default PDF curriculum scanner model independently.
- `--api-base-url URL`: override the Responses-compatible API root.
- `--error-log PATH`: select the local structured error log.

The dashboard requires API credentials at startup. See [API setup](API_SETUP.md).

## Textbook PDF import and model routing

Expand **Model routing** to choose one model for practice problems and another model
used exclusively for PDF curriculum scanning. The choices are kept in browser local
storage and sent with only their corresponding requests.

The **Import textbook pages** form accepts one PDF up to 20 MB. An optional subject or
folder-name hint can force the exact Atlas labels; otherwise the scanner infers them.
The scanner receives the PDF as a high-detail Responses API file input so it can inspect
text, diagrams, tables, and scanned page images. Sensei validates the returned JSON and
atomically creates every topic plus one containing Atlas folder. A failed scan or folder
conflict does not leave a partial import behind.

Sensei does not save the source PDF to disk or SQLite. Only the generated subject,
folder, topic names, and practice briefs become durable learning data.

## Practice flow

1. Enter a broad subject, a specific topic, and optional practice instructions.
2. Sensei stores or reuses that learner-created topic in SQLite.
3. The hosted LLM drafts one confined problem.
4. A separate LLM pass reviews the answer and checks topic fit.
5. Sensei validates the returned schema and deterministic answer contract.
6. The protected answer and ordered help steps remain process-local.
7. **Ask Sensei for help** reveals only the next step. Each click reduces the pending
   correct-answer ceiling by 5 XP and 15 mastery-evidence points.
8. If the next help step reveals the final answer, both reward ceilings become zero.
9. Submitting an answer captures the server-counted help use, and recording the attempt
   atomically updates the SQLite mastery and XP records.

Each topic card has its own **Delete** action. After a permanent-deletion warning,
Sensei removes that topic's attempts, XP events, mastery, misconceptions, and pending
in-process questions. Learner-created topic metadata is removed as well. Bundled
catalog definitions remain available, but a deleted practiced catalog topic leaves the
Atlas when its personal learning records are cleared.

Curated and deterministic generators remain available for their supported skills.
Symbolic math answers are checked with the restricted SymPy verifier.

## Security and privacy

- The HTTP server binds only to `127.0.0.1`.
- Browser writes require a per-process CSRF token and same-origin checks.
- Request bodies are size-bounded and exact-shape validated.
- Hidden answers and verification targets are not returned in public quest documents.
- API keys never enter dashboard JSON or browser storage.
- Personal learning history remains in `data/sensei.db`.
- Relevant prompt and learner-context text is sent to the configured LLM API.
- Uploaded PDFs are sent only to the selected scanner LLM and are discarded by Sensei
  after the scan request; the practice-problem LLM receives only saved topic briefs.

The browser is a local interface, not a second durable data store.
