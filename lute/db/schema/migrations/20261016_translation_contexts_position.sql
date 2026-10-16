-- Upgrade databases which already created usage notes before positions were added.
-- Old notes cannot identify an exact occurrence and stay unavailable until refreshed.
ALTER TABLE translationcontexts ADD COLUMN sentence_index INTEGER NOT NULL DEFAULT -1;
