DROP TABLE IF EXISTS srsexportspecs;

DELETE FROM settings
WHERE StKey IN ('use_ankiconnect', 'ankiconnect_url', 'hotkey_PostTermsToAnki');
