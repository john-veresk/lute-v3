-- The latest Codex result for each term, reused instead of a new request.

CREATE TABLE IF NOT EXISTS codextranslations (
  "CtID" INTEGER PRIMARY KEY,
  "CtLgID" INTEGER NOT NULL,
  "CtTextLC" TEXT NOT NULL,
  "CtContext" TEXT NOT NULL DEFAULT '',
  "CtResult" TEXT NOT NULL,
  "CtUpdated" DATETIME NOT NULL,
  FOREIGN KEY("CtLgID") REFERENCES "languages" ("LgID") ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS CtLgIDTextLC ON codextranslations (CtLgID, CtTextLC);
