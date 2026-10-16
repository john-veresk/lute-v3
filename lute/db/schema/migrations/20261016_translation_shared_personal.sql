-- Reuse the newest personal explanation across vocabulary revisions and books.
-- Preserve historical cache rows; only seed the stable dictionary identity.
INSERT OR IGNORE INTO codextranslations
  (CtLgID, CtTextLC, CtContext, CtResult, CtUpdated, CtProfile)
SELECT saved.CtLgID, saved.CtTextLC, saved.CtContext, saved.CtResult, saved.CtUpdated,
       'personal:' || LENGTH(language.LgName) || ':' || language.LgName
FROM codextranslations saved
JOIN languages language ON language.LgID = saved.CtLgID
WHERE saved.CtProfile LIKE 'personal:%'
  AND saved.CtID = (
    SELECT latest.CtID FROM codextranslations latest
    WHERE latest.CtLgID = saved.CtLgID AND latest.CtTextLC = saved.CtTextLC
      AND latest.CtProfile LIKE 'personal:%'
    ORDER BY latest.CtUpdated DESC, latest.CtID DESC LIMIT 1
  );
