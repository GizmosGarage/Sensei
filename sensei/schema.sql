CREATE TABLE IF NOT EXISTS misconceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT NOT NULL REFERENCES skills(id),
    normalized_key TEXT NOT NULL,
    description TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 1 CHECK (occurrence_count >= 1),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    resolved_at TEXT,
    UNIQUE (skill_id, normalized_key)
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT NOT NULL REFERENCES skills(id),
    problem TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('correct', 'partial', 'incorrect')),
    outcome_source TEXT NOT NULL CHECK (outcome_source IN ('student', 'model')),
    misconception_id INTEGER REFERENCES misconceptions(id),
    evidence TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    hints_used INTEGER NOT NULL CHECK (hints_used >= 0),
    solution_revealed INTEGER NOT NULL CHECK (solution_revealed IN (0, 1)),
    tutor_turns INTEGER NOT NULL CHECK (tutor_turns >= 1),
    created_at TEXT NOT NULL
, reported_outcome TEXT
    CHECK (reported_outcome IN ('correct', 'partial', 'incorrect')), effective_outcome_source TEXT NOT NULL DEFAULT 'reported'
    CHECK (effective_outcome_source IN ('reported', 'verifier')), verification_status TEXT NOT NULL DEFAULT 'unverified'
    CHECK (verification_status IN (
        'unverified', 'verified_correct', 'verified_incorrect', 'inconclusive'
    )), verification_kind TEXT
    CHECK (verification_kind IN ('derivative', 'limit', 'antiderivative', 'equivalent')), verifier_version TEXT, verification_submitted TEXT, verification_expected TEXT, verification_detail TEXT, quest_id TEXT, mastery_evidence REAL NOT NULL DEFAULT 0
    CHECK (mastery_evidence >= 0 AND mastery_evidence <= 100));

CREATE TABLE IF NOT EXISTS mastery (
    skill_id TEXT PRIMARY KEY REFERENCES skills(id),
    mastery_score REAL NOT NULL CHECK (mastery_score >= 0 AND mastery_score <= 100),
    attempts_count INTEGER NOT NULL CHECK (attempts_count >= 0),
    correct_count INTEGER NOT NULL CHECK (correct_count >= 0),
    partial_count INTEGER NOT NULL CHECK (partial_count >= 0),
    incorrect_count INTEGER NOT NULL CHECK (incorrect_count >= 0),
    independent_correct_count INTEGER NOT NULL CHECK (independent_correct_count >= 0),
    success_streak INTEGER NOT NULL CHECK (success_streak >= 0),
    last_practiced_at TEXT NOT NULL,
    next_review_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attempts_skill_created
    ON attempts(skill_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_mastery_review
    ON mastery(next_review_at);

CREATE INDEX IF NOT EXISTS idx_misconceptions_skill
    ON misconceptions(skill_id, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS "skills" (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    description TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    course TEXT NOT NULL CHECK (length(trim(course)) > 0),
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS study_guides (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL CHECK (length(trim(subject)) > 0),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    normalized_name TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (subject, normalized_name)
);

CREATE TABLE IF NOT EXISTS guide_concepts (
    folder_id TEXT NOT NULL REFERENCES study_guides(id) ON DELETE CASCADE,
    skill_id TEXT NOT NULL UNIQUE REFERENCES skills(id) ON DELETE CASCADE,
    PRIMARY KEY (folder_id, skill_id)
);

CREATE INDEX IF NOT EXISTS idx_study_guides_subject_order
    ON study_guides(subject, sort_order);

CREATE INDEX IF NOT EXISTS idx_guide_concepts_folder
    ON guide_concepts(folder_id);

CREATE TABLE IF NOT EXISTS topic_materials (
    id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('example_problem', 'worked_example', 'notes')),
    body TEXT NOT NULL CHECK (length(trim(body)) > 0),
    solution TEXT,
    source_label TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_topic_materials_skill
    ON topic_materials(skill_id, created_at);

CREATE TABLE IF NOT EXISTS subject_profiles (
    subject TEXT PRIMARY KEY CHECK (length(trim(subject)) > 0),
    profile TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_lessons (
    id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL UNIQUE REFERENCES skills(id) ON DELETE CASCADE,
    document_json TEXT NOT NULL CHECK (length(document_json) > 0),
    step_count INTEGER NOT NULL CHECK (step_count >= 1),
    current_step INTEGER NOT NULL DEFAULT 0
        CHECK (current_step >= 0 AND current_step <= step_count),
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
