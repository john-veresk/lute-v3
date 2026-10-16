-- Keep personal explanations and each fallback language side by side.
DROP INDEX IF EXISTS CtLgIDTextLC;
CREATE UNIQUE INDEX CtLgIDTextLCProfile
  ON codextranslations (CtLgID, CtTextLC, CtProfile);
