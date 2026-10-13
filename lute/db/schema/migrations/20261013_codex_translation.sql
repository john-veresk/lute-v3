ALTER TABLE languages ADD COLUMN LgTranslationProvider TEXT NOT NULL DEFAULT 'dictionaries';
ALTER TABLE languages ADD COLUMN LgTranslationTarget TEXT NOT NULL DEFAULT 'Russian';
ALTER TABLE languages ADD COLUMN LgCodexModel TEXT NOT NULL DEFAULT '';
