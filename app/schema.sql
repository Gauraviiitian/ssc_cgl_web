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
