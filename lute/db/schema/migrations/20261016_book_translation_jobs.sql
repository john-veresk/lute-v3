-- Durable server-side queue for bulk book translations.
CREATE TABLE IF NOT EXISTS booktranslationjobs (
    id INTEGER PRIMARY KEY,
    book_id INTEGER REFERENCES books(BkID) ON DELETE SET NULL,
    title TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    start_page INTEGER NOT NULL DEFAULT 1,
    errors TEXT NOT NULL DEFAULT '[]',
    position INTEGER NOT NULL,
    settings TEXT NOT NULL,
    items TEXT,
    total INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    translated INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    current_word TEXT NOT NULL DEFAULT '',
    current_context TEXT NOT NULL DEFAULT '',
    current_page INTEGER,
    error TEXT NOT NULL DEFAULT '',
    error_count INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    retry_at DATETIME,
    created_at DATETIME NOT NULL,
    started_at DATETIME,
    finished_at DATETIME,
    updated_at DATETIME NOT NULL
);
CREATE INDEX IF NOT EXISTS booktranslationjobs_queue ON booktranslationjobs(status, position);
