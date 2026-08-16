-- SSC CGL prep: core schema (Postgres / Neon)

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS questions (
    id SERIAL PRIMARY KEY,
    subject TEXT NOT NULL,           -- Quant | Reasoning | English | GA
    topic TEXT NOT NULL,             -- e.g. 'Simple & Compound Interest'
    text TEXT NOT NULL,
    option_a TEXT NOT NULL,
    option_b TEXT NOT NULL,
    option_c TEXT NOT NULL,
    option_d TEXT NOT NULL,
    correct_option CHAR(1) NOT NULL CHECK (correct_option IN ('A','B','C','D')),
    difficulty TEXT NOT NULL DEFAULT 'medium', -- easy | medium | hard
    source TEXT NOT NULL DEFAULT 'generated',  -- generated | manual | pyq
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'active', -- active | completed
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS session_questions (
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    question_id INTEGER NOT NULL REFERENCES questions(id),
    seq INTEGER NOT NULL,
    sent_at TIMESTAMPTZ,
    PRIMARY KEY (session_id, question_id)
);

CREATE TABLE IF NOT EXISTS responses (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    question_id INTEGER NOT NULL REFERENCES questions(id),
    selected_option CHAR(1) NOT NULL CHECK (selected_option IN ('A','B','C','D')),
    is_correct BOOLEAN NOT NULL,
    time_taken_sec NUMERIC NOT NULL,
    answered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, question_id)
);

CREATE TABLE IF NOT EXISTS explanation_cache (
    question_id INTEGER PRIMARY KEY REFERENCES questions(id),
    explanation_text TEXT NOT NULL,
    model_used TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_responses_session ON responses(session_id);
CREATE INDEX IF NOT EXISTS idx_questions_subject_topic ON questions(subject, topic);

-- Daily current affairs: question_date/source_url are only set for
-- subject='Current Affairs' rows; NULL for the regular question bank.
ALTER TABLE questions ADD COLUMN IF NOT EXISTS question_date DATE;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS source_url TEXT;
CREATE INDEX IF NOT EXISTS idx_questions_date ON questions(question_date);

CREATE TABLE IF NOT EXISTS daily_ca_runs (
    question_date DATE PRIMARY KEY,      -- the date the quiz is published under
    source_date DATE NOT NULL,           -- the date whose article was actually scraped (may lag behind on fallback)
    source_url TEXT NOT NULL,
    question_count INTEGER NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    telegram_posted_at TIMESTAMPTZ
);

ALTER TABLE daily_ca_runs ADD COLUMN IF NOT EXISTS pdf_posted_at TIMESTAMPTZ;

-- Paid mock tests: admin-uploaded question sets, gated behind a shared
-- access key. Questions live in the shared `questions` table just like
-- Current Affairs does (subject='Paid Mock'), keyed by paid_mock_test_id.
ALTER TABLE questions ADD COLUMN IF NOT EXISTS paid_mock_test_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_questions_paid_mock ON questions(paid_mock_test_id);

CREATE TABLE IF NOT EXISTS paid_mock_tests (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    is_live BOOLEAN NOT NULL DEFAULT FALSE,
    uploaded_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS access_keys (
    id SERIAL PRIMARY KEY,
    key_value TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS paid_mock_attempts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    paid_mock_test_id INTEGER NOT NULL REFERENCES paid_mock_tests(id),
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, paid_mock_test_id)
);
