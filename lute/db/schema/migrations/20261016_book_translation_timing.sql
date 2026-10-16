-- Active processing time per word; pauses and retry delays are excluded.
CREATE TABLE booktranslationwordtimings (
    job_id INTEGER NOT NULL REFERENCES booktranslationjobs(id) ON DELETE CASCADE,
    word_index INTEGER NOT NULL,
    word TEXT NOT NULL,
    page INTEGER NOT NULL,
    duration_seconds FLOAT NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL,
    started_at DATETIME,
    finished_at DATETIME,
    PRIMARY KEY (job_id, word_index)
);
