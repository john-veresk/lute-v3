-- Discard generated explanations, preserving ordinary target-language translations.
DELETE FROM codextranslations WHERE CtProfile LIKE 'personal:%';
DELETE FROM translationcontexts
  WHERE profile = 'personal' OR profile LIKE 'personal:%';
UPDATE codextranslations
SET CtResult = json_remove(CtResult, '$.fallback', '$.fallback_language', '$.vocabulary')
WHERE json_type(CtResult, '$.fallback') IS NOT NULL
  OR json_type(CtResult, '$.fallback_language') IS NOT NULL
  OR json_type(CtResult, '$.vocabulary') IS NOT NULL;

-- Personal jobs must translate their words again into their saved target language.
-- Pause them so resuming is explicit; ordinary jobs and vocabulary cards are untouched.
DELETE FROM booktranslationwordtimings
WHERE job_id IN (
  SELECT id FROM booktranslationjobs
  WHERE json_extract(settings, '$.translation_mode') = 'personal'
    AND status IN ('queued', 'running', 'waiting', 'paused', 'error')
);
UPDATE booktranslationjobs
SET status = 'paused', done = 0, translated = 0, skipped = 0, attempts = 0,
    current_word = '', current_context = '', current_page = NULL,
    error = '', retry_at = NULL, finished_at = NULL
WHERE json_extract(settings, '$.translation_mode') = 'personal'
  AND status IN ('queued', 'running', 'waiting', 'paused', 'error');

UPDATE booktranslationjobs
SET settings = json_set(settings, '$.target', COALESCE(
  NULLIF(json_extract(settings, '$.fallback_target'), ''),
  (SELECT LgTranslationTarget FROM languages
   WHERE LgID = json_extract(settings, '$.language_id')),
  'Russian'
))
WHERE json_extract(settings, '$.translation_mode') = 'personal';
UPDATE booktranslationjobs
SET settings = json_remove(settings, '$.translation_mode', '$.fallback_target',
  '$.target_label', '$.known_words', '$.vocabulary_revision');

ALTER TABLE languages DROP COLUMN LgTranslationMode;
