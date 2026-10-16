# Translation model API

Use JSON requests to change translation settings without a browser form.

| Endpoint | GET | PATCH |
| --- | --- | --- |
| `/language/<id>/translation-settings` | Current language CLI, model and effort | Defaults for reading and newly queued jobs |
| `/jobs/<id>/settings` | Job state and settings | Settings for this existing job only |

PATCH accepts any non-empty subset of `cli` (`codex` or `cursor`), `model`
(model ID, or `""` for the CLI default), and `effort` (Codex reasoning level,
or `""` for default). Unknown fields and invalid values return HTTP 400;
missing records return 404. Cursor effort and speed are part of the model ID,
for example `cursor-grok-4.6-medium` or `cursor-grok-4.6-medium-fast`.

```sh
curl -X PATCH http://localhost:5001/language/1/translation-settings \
  -H 'Content-Type: application/json' \
  -d '{"cli":"cursor","model":"cursor-grok-4.6-medium"}'

curl -X PATCH http://localhost:5001/jobs/8/settings \
  -H 'Content-Type: application/json' \
  -d '{"cli":"cursor","model":"cursor-grok-4.6-medium"}'
```

Language updates do not change existing jobs. Job updates preserve progress,
starting page, results, pause/error status and all output settings. They do not
resume a paused job; use `POST /jobs/<id>/resume` separately. Completed and
cancelled jobs reject updates with HTTP 409.

Running jobs finish the current word using its original settings, then use the
new settings for the next word. The job response contains `job` and
`applies_after_current_word`, which is true while a word is in flight. No server
restart is needed to apply settings.

`GET /translation/models?cli=cursor` (or `cli=codex`, the default) returns
`{"cli":"cursor","models":[...]}` with cached model suggestions. The list can
be empty when the CLI or its model metadata is unavailable. Custom IDs are
accepted independently of this list.

On the Jobs page, **Change model** opens the same settings for an active job.
Choose the harness and a model suggestion, or enter a custom ID. Saving keeps
the job's current status and checkpoint; **Resume** remains a separate action.
