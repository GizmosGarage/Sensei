# Hosted LLM API setup

Sensei requires a hosted endpoint that implements the OpenAI Responses API. The
default connection is:

- Base URL: `https://api.openai.com/v1`
- Endpoint: `POST /responses`
- Model: `gpt-5.4-mini`

## Configure OpenAI

From the repository root, copy the template and put your API key in `.env`:

```powershell
Copy-Item .env.example .env
```

```dotenv
OPENAI_API_KEY=your-api-key
SENSEI_LLM_MODEL=gpt-5.6-sol
SENSEI_LLM_BASE_URL=https://api.openai.com/v1
```

Then start Sensei from the same directory:

```powershell
python -m sensei.dashboard
```

Sensei loads `.env` from its startup directory, and Git ignores the file. Existing
process environment variables take precedence over `.env`. The key is sent only in
the HTTPS authorization header; Sensei does not copy it into SQLite, logs, or browser
storage.

## Connection overrides

The `SENSEI_LLM_*` variables make the provider explicit and can point Sensei at
another Responses-compatible service:

```powershell
$env:SENSEI_LLM_API_KEY = "your-api-key"
$env:SENSEI_LLM_MODEL = "provider-model-name"
$env:SENSEI_LLM_BASE_URL = "https://provider.example/v1"
python -m sensei.dashboard
```

Command-line `--model`, `--scanner-model`, and `--api-base-url` values override the
corresponding environment variables. `SENSEI_SCANNER_MODEL` (or `--scanner-model`)
names the model used to analyze study guides ;
it must accept PDF `input_file` and `input_image` content and long JSON outputs (a
study-plan request allows up to 16,384 output tokens) and defaults to the practice
model. The API key
intentionally has no command-line option so it does not enter shell history or
process listings.

## Data boundary

Sensei keeps learning records in `data/study.db`. LLM requests contain the current
problem, recent bounded conversation context, and a small relevant summary of learner
memory when available. Practice requests also include the topic's saved class
material, the subject's course profile, and a compact learner signal. The provider
request sets `store` to `false`.

Uploaded study guides, homework, or exam pages are sent only to the scanner model.
The practice model receives the plan or transcribed items you save, never the file.
Sensei does not write uploaded bytes to disk or SQLite.

The API is required for dashboard startup. Missing
credentials cause startup to fail before a tutoring request is sent.
