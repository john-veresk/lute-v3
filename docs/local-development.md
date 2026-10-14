# Automatic server reload

Start Lute from the repository with:

```sh
.venv/bin/python -m lute.main --port 5001 --reload --local
```

`--reload` uses the local development server and automatically restarts its
worker after changes to Python code, existing HTML templates, CSS, JavaScript,
database schema scripts or the selected configuration file. The interactive
debugger stays disabled. Without this flag, Lute uses the usual Waitress server.
Remove `--local` if you also access Lute from other devices on your network.

The normal configuration selection applies: `--config` takes priority, followed
by `config.yml` in the working directory and then `lute/config/config.yml`.
Your existing database and settings are used.

The browser does not refresh automatically. Reload the page after editing to
see the new interface or scripts. In this mode, templates are reloaded and
static assets are revalidated on every request. CSS and JavaScript changes
normally need only a browser refresh; watching them also restarts the server
so each edit uses a fresh process.

Vocabulary changes, book imports, backups and logs do not trigger restarts.
New template or asset files join the watched list at the next restart, usually
triggered by editing the Python code or template that references them.
