"""Comando `chamados`: migrações e exportação do contrato OpenAPI.

Os comandos de administração (`admin create`) e o `worker` entram nas Sprints 2 e 4.
"""

import argparse
import json
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from chamados.config import get_settings

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", database_url or get_settings().database_url)
    return cfg


def _openapi(out: str | None) -> None:
    from chamados.main import create_app

    spec = json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n"
    if out:
        Path(out).write_text(spec, encoding="utf-8")
    else:
        sys.stdout.write(spec)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="chamados", description="TicketFlow")
    sub = parser.add_subparsers(dest="cmd", required=True)

    db = sub.add_parser("db", help="migrações do banco").add_subparsers(
        dest="db_cmd", required=True
    )
    up = db.add_parser("upgrade", help="aplica as migrações")
    up.add_argument("revision", nargs="?", default="head")
    down = db.add_parser("downgrade", help="desfaz migrações até a revisão indicada")
    down.add_argument("revision")
    db.add_parser("current", help="mostra a revisão atual")

    api = sub.add_parser("openapi", help="exporta o contrato OpenAPI em JSON")
    api.add_argument("-o", "--output", help="arquivo de saída (padrão: stdout)")

    args = parser.parse_args(argv)
    if args.cmd == "db":
        cfg = alembic_config()
        if args.db_cmd == "upgrade":
            command.upgrade(cfg, args.revision)
        elif args.db_cmd == "downgrade":
            command.downgrade(cfg, args.revision)
        else:
            command.current(cfg)
    elif args.cmd == "openapi":
        _openapi(args.output)
