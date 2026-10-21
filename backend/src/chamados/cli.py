"""Comando `chamados`: migrações, primeiro administrador, anexos, worker e contrato OpenAPI."""

import argparse
import asyncio
import json
import sys
from datetime import timedelta
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


async def _create_admin(email: str, name: str) -> str:
    """Cria um administrador sem senha e devolve o link para defini-la (docs/09 §9.2)."""
    from sqlalchemy import select

    from chamados.db.engine import create_engine
    from chamados.db.session import make_sessionmaker
    from chamados.modules.audit.service import record
    from chamados.modules.identity.models import User
    from chamados.modules.identity.service import issue_token, link
    from chamados.modules.organization.models import Role

    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        async with make_sessionmaker(engine)() as db:
            if await db.scalar(select(User.id).where(User.email == email)):
                raise SystemExit(f"Já existe um usuário com o e-mail {email}.")
            role = await db.scalar(select(Role).where(Role.code == "admin"))
            if role is None:
                raise SystemExit("Papéis não encontrados: rode `chamados db upgrade` antes.")
            user = User(email=email, full_name=name, display_name=name, role=role)
            db.add(user)
            await db.flush()
            raw = await issue_token(db, user, "invite", timedelta(hours=24))
            record(
                db,
                "user.created",
                target_type="user",
                target_id=user.public_id,
                after={"email": email, "full_name": name, "role": "admin", "via": "cli"},
            )
            await db.commit()
            return link(settings, "invite", raw)
    finally:
        await engine.dispose()


async def _purge_attachments() -> int:
    """À mão; o worker já roda a limpeza todo dia (docs/11 §11.4)."""
    from chamados.db.engine import create_engine
    from chamados.db.session import make_sessionmaker
    from chamados.modules.attachments.service import purge

    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        async with make_sessionmaker(engine)() as db:
            return await purge(db, settings.files_dir)
    finally:
        await engine.dispose()


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

    admin = sub.add_parser("admin", help="administração").add_subparsers(
        dest="admin_cmd", required=True
    )
    create = admin.add_parser("create", help="cria um administrador e mostra o link de senha")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)

    files = sub.add_parser("attachments", help="anexos").add_subparsers(
        dest="attachments_cmd", required=True
    )
    files.add_parser("purge", help="apaga os envios não vinculados há mais de 24 h")

    sub.add_parser("worker", help="fila de tarefas e rotinas (ticketflow-worker.service)")

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
    elif args.cmd == "admin":
        url = asyncio.run(_create_admin(args.email.strip(), args.name.strip()))
        print(f"Administrador criado. Para definir a senha (link válido por 24 h):\n{url}")
    elif args.cmd == "attachments":
        print(f"Envios não vinculados apagados: {asyncio.run(_purge_attachments())}")
    elif args.cmd == "worker":
        from chamados.core.logging import configure_logging
        from chamados.modules.jobs import worker

        settings = get_settings()
        configure_logging(settings.log_level, settings.log_format)
        worker.main(settings)
    elif args.cmd == "openapi":
        _openapi(args.output)
