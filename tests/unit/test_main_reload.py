"""Local reload mode preserves config selection and the normal server mode."""

from contextlib import nullcontext
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from lute import main


def test_reload_files_include_templates_assets_schema_and_selected_config(tmp_path):
    watched = [
        "templates/read/panel.html",
        "static/js/panel.js",
        "static/css/panel.css",
        "db/schema/migrations/change.sql",
    ]
    ignored = ["static/image.png", "data/lute.db", "data/book.txt", "output/server.log"]
    for name in watched + ignored:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test")
    config = tmp_path / "config.yml"
    config.write_text("test")
    files = set(
        main._reload_files(SimpleNamespace(root_path=str(tmp_path)), str(config))
    )
    assert files == {str(tmp_path / name) for name in watched} | {str(config)}


@pytest.mark.parametrize("reload_enabled", [False, True])
@pytest.mark.parametrize("local", [False, True])
@pytest.mark.parametrize("serving_child", [False, True])
def test_start_uses_requested_server_and_host(
    monkeypatch, tmp_path, reload_enabled, local, serving_child
):
    app = SimpleNamespace(
        root_path=str(tmp_path),
        env_config=SimpleNamespace(is_docker=False),
        app_context=nullcontext,
    )
    create = Mock(return_value=app)
    serve = Mock()
    run = Mock()
    config = str(tmp_path / "selected.yml")
    monkeypatch.setattr(main, "_get_config_file_path", lambda path: config)
    monkeypatch.setattr(main, "create_app", create)
    monkeypatch.setattr(main, "data_initialization", Mock())
    monkeypatch.setattr(main, "serve", serve)
    monkeypatch.setattr(main, "run_simple", run)
    monkeypatch.setattr(main, "_print", Mock())
    monkeypatch.setattr(main, "is_running_from_reloader", lambda: serving_child)
    main._start(
        SimpleNamespace(config=config, reload=reload_enabled, local=local, port=5123)
    )
    host = "127.0.0.1" if local else "0.0.0.0"
    if reload_enabled:
        serve.assert_not_called()
        run.assert_called_once_with(
            host,
            5123,
            app,
            use_reloader=True,
            use_debugger=False,
            threaded=True,
            reloader_type="stat",
            extra_files=[config],
        )
        assert create.call_args.kwargs["extra_config"] == {
            "TEMPLATES_AUTO_RELOAD": True,
            "SEND_FILE_MAX_AGE_DEFAULT": 0,
            "BOOK_TRANSLATION_WORKER_ENABLED": serving_child,
        }
    else:
        run.assert_not_called()
        serve.assert_called_once_with(app, host=host, port=5123)
        assert create.call_args.kwargs["extra_config"] == {
            "BOOK_TRANSLATION_WORKER_ENABLED": True
        }
    assert create.call_args.args == (config,)


@pytest.mark.parametrize("flag,expected", [([], False), (["--reload"], True)])
def test_command_accepts_optional_reload(monkeypatch, flag, expected):
    start = Mock()
    monkeypatch.setattr(main, "_start", start)
    monkeypatch.setattr(
        sys, "argv", ["lute", "--port", "5123", "--config", "custom.yml", *flag]
    )
    main.start()
    args = start.call_args.args[0]
    assert args.reload is expected
    assert args.port == 5123
    assert args.config == "custom.yml"
