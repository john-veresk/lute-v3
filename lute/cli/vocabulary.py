"""Offline, read-only database tools: python -m lute.cli.vocabulary --help."""

import argparse
import json
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Register the application's related ORM models, without creating or starting it.
import lute.app_factory  # pylint: disable=unused-import
from lute.config.app_config import AppConfig
from lute.models.language import Language
from lute.parse.registry import init_parser_plugins
from lute.translation.vocabulary import Vocabulary


def main():
    """Search terms or check text without running migrations, jobs or model requests."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", help="SQLite file; defaults to Lute's configured database"
    )
    parser.add_argument("operation", choices=("check", "search", "lookup"))
    parser.add_argument("language", help="Language name as saved in Lute")
    parser.add_argument(
        "text", nargs="+", help="Text to check, query, or individual words"
    )
    args = parser.parse_args()
    path = (
        args.database
        or AppConfig(
            "config.yml"
            if Path("config.yml").exists()
            else AppConfig.default_config_filename()
        ).dbfilename
    )
    path = Path(path).resolve()
    if not path.is_file():
        parser.error(f"Database not found: {path}")
    init_parser_plugins()
    engine = create_engine(f"sqlite:///file:{path.as_posix()}?mode=ro&uri=true")
    with Session(engine) as session:
        language = session.query(Language).filter_by(name=args.language).one_or_none()
        if language is None:
            parser.error(f"Language not found: {args.language}")
        vocabulary = Vocabulary(session, language)
        if args.operation == "check":
            result = vocabulary.check(" ".join(args.text))
        elif args.operation == "search":
            result = vocabulary.search(" ".join(args.text))
        else:
            result = vocabulary.lookup(args.text)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    engine.dispose()


if __name__ == "__main__":
    main()
