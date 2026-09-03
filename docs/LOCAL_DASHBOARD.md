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
- `--scanner-model NAME`: model used only to scan uploaded class material.
- `--api-base-url URL`: override the Responses-compatible API root.
- `--error-log PATH`: select the local structured error log.

The dashboard requires API credentials at startup. See [API setup](API_SETUP.md).

## Import a study guide

The Dojo opens with **Turn a study guide into a study plan**. Upload a PDF or photo, or
paste the text, optionally with a subject and study-set name. Sensei sends the document
to the scanner model once (with one compact retry if the answer is cut off) and returns
a plan to review:

- **Subject** and **study set name** (for example `MAC2311 Calculus I` and `Test 1`).
- **Course profile**: document-wide rules such as calculator policy or required
  notation, saved for the subject when it has no profile yet.
- **Topics**: 3-24 skill-level topics in document order, each with a section label, a
  practice brief, and up to six example problems transcribed from the document with
  their printed answers.

Uncheck topics you do not need, rename them, edit briefs, then **Create study plan**.
The study set becomes an Atlas folder; each topic keeps its brief and examples as class
material. Importing the same guide again reuses the folder, refreshes the briefs, and
skips example problems that are already saved. The document itself is never stored.
There is no manual topic form; topics come from analyzed documents, and a topic's
brief and examples can be edited in its Class material panel.

## Class material

Every topic card has a **Class material** button that opens a panel with three
tools:

- **Course profile** for the subject: the professor's conventions, exam format,
  calculator policy, and answer expectations. It applies to every topic in that
  subject and is stored in `subject_profiles`.
- **Paste a problem**: the problem text (keep parts (a), (b), (c) on their own
  lines), an optional solution or answer key, a kind (problem, worked example, or
  notes), and a source label such as `HW 4 #7`. Up to 40 items per topic, 4,000
  characters each.
- **Scan a page**: upload one PDF (20 MB) or PNG, JPEG, or WebP image (8 MB). The
  scanner model transcribes the problems it finds; you review, edit, and choose
  which to save. The file is sent only to the scanner request and is never stored.

Saved material becomes the exemplars the practice model must imitate. Each new
problem is anchored to one exemplar in rotation, so every saved style gets covered.
Restart keeps a topic's material; Delete removes it.

## Practice flow

1. Choose **Train this topic** on a card in a study set (Dojo) or the Atlas (Profile).
2. Sensei loads that topic's practice brief from SQLite.
3. Sensei gathers the topic's class material, the course profile, and a learner
   signal: mastery score and label, the last five outcomes, unresolved
   misconceptions, and the difficulty tier derived from them.
4. The hosted LLM drafts one problem isomorphic to the anchor exemplar at the target
   tier, using one of the answer formats: expression, numeric with tolerance,
   solution set, interval, point, multiple choice, or multi-part.
5. A separate LLM pass recomputes every answer and rejects drafts that ignore the
   brief, are easier or shorter than the class examples, use a different method, or
   copy an exemplar.
6. Sensei validates the returned schema and checks every answer key against its own
   checker before the problem is issued.
7. The protected answer keys and ordered help steps remain process-local.
8. **Ask Sensei for help** reveals only the next step. Each click reduces the pending
   correct-answer ceiling by 5 XP and 15 mastery-evidence points.
9. If the next help step reveals the final answer, both reward ceilings become zero.
10. Submitting an answer checks it locally. Multi-part problems are checked part by
    part: all parts right is **correct**, some right is **partial** (55 evidence,
    12 XP), none right is **incorrect**.
11. When the result is not fully correct and the final answer was not revealed, one
    short classification call names the likely mistake. It is shown as "Sensei
    noticed" and saved with the attempt.
12. Recording the attempt atomically updates the SQLite mastery, XP, and
    misconception records; two independent correct answers in a row resolve that
    topic's open misconceptions.

Each topic card has **Restart** and **Delete** actions. After a reset warning,
**Restart** removes that topic's attempts, XP events, mastery, misconceptions, review
progress, and pending in-process questions while preserving the learner-created topic
and its folder. The card returns to 0/100 with no encounters. **Delete** clears the same
learning data and also removes learner-created topic metadata. Bundled catalog
definitions remain available, but a deleted practiced catalog topic leaves the Atlas
when its personal learning records are cleared.

Curated and deterministic generators remain available for their supported skills.
Symbolic math answers are checked with the restricted SymPy verifier.

## Learn flow

Learn is separate from practice: its own panel, routes, and saved state. Opening a
lesson closes the practice chat and vice versa.

1. Choose **Learn this topic** on a card. A card with a saved lesson shows **Resume
   lesson · step k of n** or **Review lesson** instead.
2. Sensei gathers the same study brief practice uses: practice brief, class material,
   course profile, and learner signal. Known weak spots get their own step.
3. The hosted LLM writes one lesson: an overview, four to seven steps (explanation,
   optional worked example, key takeaway, and a check-in question with a private
   expected answer and rubric), and a closing summary.
4. A separate LLM pass recomputes every worked example and check-in answer and rejects
   lessons that drift from the subject, reorder the method, or copy an exemplar.
5. The validated lesson is stored in `topic_lessons`. The browser receives the lesson
   without the check-in answers.
6. Steps appear one at a time. Answering the check-in sends the answer to a short
   grading call that compares it with the private rubric: **correct** or **partial**
   unlocks the next step; **incorrect** explains the gap and lets you try again.
7. **Ask Sensei about this step** sends a free-text question with the current step as
   context and shows the explanation in the thread.
8. Passing the last step marks the lesson complete and awards 25 XP once per topic.
   Mastery does not change. **Start lesson over** writes a new lesson and resets the
   step without awarding the bonus again.
9. **Restart** or **Delete** on the topic removes the lesson and its XP.

Routes: `POST /api/study/learn/start` (`skill_id`, `restart`), `POST
/api/study/learn/check` (`skill_id`, `step_index`, `answer`), and `POST
/api/study/learn/ask` (`skill_id`, `step_index`, `question`). All three require the
CSRF header like every other write.

## Security and privacy

- The HTTP server binds only to `127.0.0.1`.
- Browser writes require a per-process CSRF token and same-origin checks.
- Request bodies are size-bounded and exact-shape validated.
- Hidden answers and verification targets are not returned in public quest documents.
- API keys never enter dashboard JSON or browser storage.
- Personal learning history remains in `data/sensei.db`.
- Relevant prompt and learner-context text is sent to the configured LLM API,
  including saved class material and the course profile.
- An uploaded page is sent only to the scanner model request; Sensei keeps only the
  transcribed items you choose to save.

The browser is a local interface, not a second durable data store.
