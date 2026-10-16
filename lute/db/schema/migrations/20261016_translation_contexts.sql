-- Per-book usage notes do not change the shared dictionary entry.
CREATE TABLE translationcontexts (
  id INTEGER PRIMARY KEY,
  language_id INTEGER NOT NULL REFERENCES languages(LgID) ON DELETE CASCADE,
  book_id INTEGER NOT NULL REFERENCES books(BkID) ON DELETE CASCADE,
  text_lc TEXT NOT NULL,
  profile TEXT NOT NULL,
  context_key TEXT NOT NULL,
  page INTEGER NOT NULL,
  sentence TEXT NOT NULL,
  excerpt TEXT NOT NULL,
  note TEXT NOT NULL,
  updated DATETIME NOT NULL
);
CREATE UNIQUE INDEX TranslationContextOccurrence
  ON translationcontexts(language_id, text_lc, profile, book_id, context_key);
