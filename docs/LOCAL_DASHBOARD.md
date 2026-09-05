# Study dashboard

Run `python -m sensei.dashboard` and open http://127.0.0.1:8765/.
The service is loopback-only and requires the configured hosted model API key.
See [API setup](API_SETUP.md) for configuration.

## Start from a guide

Upload a PDF (up to 20 MB), a PNG/JPEG/WebP photo (up to 8 MB), or paste
plain text (up to 200 KB). Sensei extracts a reviewable list of concepts,
class instructions, and examples. The original upload is not persisted;
the accepted learning plan and extracted material are saved locally.

Choose **Use this guide**, then **Start check-in** on its guide card.
The dashboard provides one next action per guide, without manual topic management.
Unseen concepts get a check first. Saved mistakes and use of help identify areas
for explanation and independent follow-up practice. Due reviews come next, then
practice in concepts with less mastery evidence.

## Learn and remember

Answers are checked and saved automatically. **Continue with Sensei** takes the
next recommended step within the same guide. If saving fails, use **Retry saving
progress** before continuing. Help reveals a step at a time and is remembered as
support, rather than independent evidence. Lessons allow questions about each
step and end with a practice check; completion alone does not establish mastery.

Expand **What Sensei is learning about you** for concept coverage and possible
misconceptions. **Learning history** shows recent saved practice. The new database starts empty and only receives concepts from guides.

The browser has no RPG ranks, XP display, or topic/folder management controls.
The legacy terminal, catalog, RPG fields, and management endpoints have been removed.

## Scope and verification

The initial workflow uses structured math and chemistry practice. Recommendations
are transparent rules over saved evidence, not a validated diagnostic or exam
readiness score. Model generation, review, and lesson quality depend on the
configured provider. Tests use temporary databases and deterministic provider
fixtures; they do not modify learner data.
