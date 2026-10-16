CLI commands.

Offline vocabulary tools (read-only SQLite access; no migrations, workers or model calls):

```sh
python -m lute.cli.vocabulary check Finnish "Minulla ei ollut tarpeeksi aikaa."
python -m lute.cli.vocabulary lookup Finnish minulla ollut tarpeeksi
python -m lute.cli.vocabulary search Finnish tarpe
python -m lute.cli.vocabulary --database /path/to/lute.db check Finnish "Some text"
```

The JSON shows exact matches, learning statuses, explicit parents, locally inferred
lemmas, and known/unknown/ignored classifications. Finnish morphology uses the
offline Simplemma dictionary; stored parents take precedence. Dictionary analysis
can be ambiguous, and unrecognized forms remain unfamiliar rather than being
guessed from similar spellings. The same checker is available as local HTTP tools:
`POST /translation/vocabulary` with `language_id` and `words`,
`GET /translation/vocabulary?language_id=1&q=tarpe`, and
`POST /translation/vocabulary/check` with `language_id` and `text`.

Note the lute.app_factory has to be specified as the `--app`.

Samples:

```
flask --app lute.app_factory cli --help

flask --app lute.app_factory cli language_export English ./hello.csv
```

See the  help for a command:

```
flask --app lute.app_factory cli language_export --help

Usage: flask cli language_export [OPTIONS] LANGUAGE OUTPUT_PATH

  Get all terms from active books in the language, and write a data file of
  term frequencies and children.
```
