-- pgvector activation
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE users (
    user_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_name   VARCHAR(30) NOT NULL,
    email       TEXT UNIQUE NOT NULL,
    preferences JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(user_id),
    title      TEXT,
    source     TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at   TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- rolling transcript buffer, one row per audio chunk (Week 2)
CREATE TABLE transcript_chunks (
    chunk_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(session_id),
    seq        INTEGER NOT NULL,          -- order within the session
    text       TEXT NOT NULL,
    start_ts   REAL,                      -- seconds from session start
    end_ts     REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE concepts (
    concept_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    description TEXT,
    embedding   VECTOR(1536),             -- OpenAI text-embedding-3-small = 1536 dims
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- pgvector's graph-based approximate-nearest-neighbor index (after the table exists)
CREATE INDEX concepts_embedding_idx ON concepts USING hnsw (embedding vector_cosine_ops);

CREATE TABLE quizzes (
    quiz_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id     UUID NOT NULL REFERENCES sessions(session_id),
    triggered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    trigger_reason TEXT                   -- 'topic_shift' | 'length_threshold'
);

CREATE TABLE questions (
    question_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(session_id),
    concept_id      UUID REFERENCES concepts(concept_id),
    quiz_id         UUID REFERENCES quizzes(quiz_id),
    prompt          TEXT NOT NULL,
    answer_key      TEXT,
    question_type   TEXT,
    options         JSONB,
    transcript_span JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE attempts (
    attempt_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID NOT NULL REFERENCES questions(question_id),
    user_id     UUID NOT NULL REFERENCES users(user_id),
    user_answer TEXT,
    is_correct  BOOLEAN,
    score       REAL,
    feedback    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- per-user Elo mastery, one row per (user, concept) (Week 4)
CREATE TABLE mastery (
    user_id    UUID NOT NULL REFERENCES users(user_id),
    concept_id UUID NOT NULL REFERENCES concepts(concept_id),
    elo        REAL NOT NULL DEFAULT 1200,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, concept_id)
);

-- agent run tracing (Week 2)
CREATE TABLE agent_traces (
    trace_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(session_id),
    kind       TEXT,                      -- 'topic_detect' | 'quiz_gen' | 'grade' | ...
    payload    JSONB,                     -- inputs/outputs/tokens for debugging
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- single dev user for local work
INSERT INTO users (user_name, email) VALUES ('Brandon', 'bgao2005@gmail.com');
