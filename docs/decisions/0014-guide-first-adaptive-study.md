# Guide-first adaptive study

Sensei starts from an uploaded study guide and offers one recommended next step.
Guide concepts, examples, practice evidence, misconceptions, review dates, and
lessons form the complete learning model. Concepts are scoped to a guide, so a
second upload cannot move material out of the first.

The application is a loopback web dashboard backed by a fresh SQLite schema and
hosted model calls. The terminal tutor, RPG rewards, fixed skill/quest catalogs,
manual topic and folder management, old migrations, and their tests are removed.
Both Python entry points launch the dashboard. The new database is `data/study.db`.
Old `data/sensei.db` records are never loaded or migrated.

Check unseen concepts first, then prioritize recent errors or supported answers,
unresolved misconceptions, due reviews, and lower mastery evidence. A gap suggests
a guided explanation; a completed lesson is followed by independent practice.
Checked answers save automatically. The next step is recomputed from SQLite.

The first version uses structured math/chemistry answer checking. It does not
provide unrestricted conversational assessment for every subject, prerequisite
inference, or a validated estimate of exam readiness.
