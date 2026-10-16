ALTER TABLE languages ADD COLUMN LgTranslationMode TEXT NOT NULL DEFAULT 'translation';
ALTER TABLE codextranslations ADD COLUMN CtProfile TEXT NOT NULL DEFAULT '';

-- Keep existing cached translations in their current output language.
UPDATE codextranslations SET CtProfile = (
  SELECT 'translation:' || LENGTH(LgName) || ':' || LgName || LgTranslationTarget
  FROM languages WHERE LgID = CtLgID
);
