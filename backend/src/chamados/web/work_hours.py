"""Expediente nas telas (Configurações e os painéis de grupo e de usuário): o texto curto, a
lista de vigências e o formulário "Nova vigência a partir de". As regras (precedência, vigência,
auditoria) ficam em `modules/system/work_hours.py`; aqui só se lê o formulário e se monta o
que a tela mostra.
"""

import uuid
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.modules.identity.models import User
from chamados.modules.organization.models import Team
from chamados.modules.system.work_hours import (
    DEFAULT_SCHEDULE,
    TZ,
    Schedule,
    Vigencies,
    describe,
    load_calendar,
    vigencies,
)
from chamados.web.formatting import format_date
from chamados.web.page import Page

DAYS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")  # expediente.diasCurtos.*


def today() -> date:
    return datetime.now(TZ).date()


def text(page: Page, schedule: Schedule | None) -> str:
    """O expediente em texto curto ("seg–sex 08:00–18:00"), ou "Sem expediente próprio" (a
    vigência que volta ao de cima)."""
    if schedule is None:
        return page.t("expediente.semProprio")
    return describe(schedule, [page.t(f"expediente.diasCurtos.{d}") for d in DAYS])


def _current(found: Vigencies, day: date) -> int | None:
    """A posição da vigência que vale no dia (a mais recente que começou até ele)."""
    return max((i for i, (start, _) in enumerate(found) if start <= day), default=None)


def rows(page: Page, found: Vigencies) -> list[dict[str, Any]]:
    """As vigências para a lista: o início ("Desde sempre" para date.min), o expediente e se é a
    que vale hoje (as futuras também aparecem, sem a marca)."""
    current = _current(found, today())
    return [
        {
            "start": page.t("expediente.desdeSempre")
            if start == date.min
            else page.t("expediente.aPartirDe", data=format_date(page.locale, start)),
            "text": text(page, schedule),
            "current": i == current,
        }
        for i, (start, schedule) in enumerate(found)
    ]


def form_values(schedule: Schedule) -> dict[str, Any]:
    """O formulário "Nova vigência" preenchido com o expediente que vale hoje, a partir de hoje;
    sem intervalo, sugere o padrão (apagar os dois campos grava sem intervalo)."""
    break_start = schedule.break_start or DEFAULT_SCHEDULE.break_start
    break_end = schedule.break_end or DEFAULT_SCHEDULE.break_end
    return {
        "valid_from": today().isoformat(),
        "weekdays": list(schedule.weekdays),
        "start": f"{schedule.start:%H:%M}",
        "end": f"{schedule.end:%H:%M}",
        "break_start": f"{break_start:%H:%M}" if break_start else "",
        "break_end": f"{break_end:%H:%M}" if break_end else "",
        "none": False,
    }


def typed(
    valid_from: str,
    weekdays: list[int] | None,
    start: str,
    end: str,
    break_start: str,
    break_end: str,
    none: bool,
) -> dict[str, Any]:
    """O que veio do formulário, para ler (`read_form`) e para devolver na tela com o erro."""
    return {
        "valid_from": valid_from,
        "weekdays": weekdays or [],
        "start": start,
        "end": end,
        "break_start": break_start,
        "break_end": break_end,
        "none": none,
    }


def read_form(page: Page, form: dict[str, Any]) -> tuple[date, Schedule | None] | str:
    """A vigência digitada, ou a mensagem do erro (data inválida, nenhum dia, fim antes do
    início, intervalo pela metade ou fora do horário). Com "sem expediente próprio", os dias e
    o horário não contam."""
    try:
        valid_from = date.fromisoformat(form["valid_from"])
    except ValueError:
        return page.t("expediente.dataInvalida")
    if form["none"]:
        return valid_from, None
    weekdays = tuple(sorted({d for d in form["weekdays"] if 0 <= d <= 6}))
    if not weekdays:
        return page.t("expediente.semDias")
    try:
        start, end = time.fromisoformat(form["start"]), time.fromisoformat(form["end"])
    except ValueError:
        return page.t("expediente.horarioInvalido")
    if end <= start:
        return page.t("expediente.horarioInvalido")
    break_start = break_end = None
    if form["break_start"] or form["break_end"]:
        try:
            break_start = time.fromisoformat(form["break_start"])
            break_end = time.fromisoformat(form["break_end"])
        except ValueError:
            return page.t("expediente.intervaloInvalido")
        if not start < break_start < break_end < end:
            return page.t("expediente.intervaloInvalido")
    return valid_from, Schedule(
        weekdays,
        start.replace(second=0, microsecond=0),
        end.replace(second=0, microsecond=0),
        break_start.replace(second=0, microsecond=0) if break_start else None,
        break_end.replace(second=0, microsecond=0) if break_end else None,
    )


async def panel(
    page: Page,
    db: AsyncSession,
    owner: User | Team,
    form: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """A seção Expediente do painel de um grupo ou de uma pessoa: as vigências, o que vale hoje
    e de onde vem (`Calendar.source`), o aviso de quem está em dois ou mais grupos com
    expediente e o formulário (o que foi digitado, quando volta com erro)."""
    day = today()
    calendar = await load_calendar(db)
    if isinstance(owner, User):
        found = await vigencies(db, user_id=owner.id)
        source = calendar.source(owner.id, day)
        schedule, kind, team_id = source.schedule, source.kind, source.team_id
        conflict = source.conflict
        following = None
    else:
        found = await vigencies(db, team_id=owner.id)
        i = _current(found, day)
        own = found[i][1] if i is not None else None
        schedule = own or calendar.source(None, day).schedule
        kind, team_id, conflict = ("own" if own else "installation"), None, ()
        # Quem segue o do grupo hoje: está só nele, entre os grupos com expediente, e não tem
        # um próprio (os que estão em dois ficam com o da instalação e aparecem no painel deles).
        following = (
            sum(
                1
                for user_id, teams in calendar.member_of.items()
                if owner.id in teams and calendar.source(user_id, day).team_id == owner.id
            )
            if own
            else None
        )
    names: dict[int, str] = {}
    if team_id is not None or conflict:
        ids = [t for t in (team_id, *conflict) if t is not None]
        names = dict((await db.execute(select(Team.id, Team.name).where(Team.id.in_(ids)))).all())
    origin = {
        "own": page.t("expediente.origem.proprio", expediente=text(page, schedule)),
        "team": page.t(
            "expediente.origem.grupo",
            grupo=names.get(team_id or 0, ""),
            expediente=text(page, schedule),
        ),
        "installation": page.t("expediente.origem.instalacao", expediente=text(page, schedule)),
    }[kind]
    return {
        "rows": rows(page, found),
        "today": origin,
        "conflict": page.t(
            "expediente.conflito", grupos=", ".join(sorted(names[t] for t in conflict))
        )
        if conflict
        else None,
        # membrosSeguem0, 1 e 2 (dois ou mais).
        "following": None
        if following is None
        else page.t(f"expediente.membrosSeguem{min(following, 2)}", n=following),
        "form": form or form_values(schedule),
        "error": error,
    }


async def conflicts(db: AsyncSession) -> set[uuid.UUID]:
    """Os `public_id` de quem está hoje em dois ou mais grupos com expediente e não tem um
    próprio: a lista de usuários marca essas pessoas."""
    calendar = await load_calendar(db)
    day = today()
    ids = [u for u in calendar.member_of if calendar.source(u, day).conflict]
    if not ids:
        return set()
    return set(await db.scalars(select(User.public_id).where(User.id.in_(ids))))


async def installation(page: Page, db: AsyncSession) -> list[dict[str, Any]]:
    """As vigências da instalação; sem nenhuma gravada, o padrão desde sempre."""
    return rows(page, await vigencies(db) or [(date.min, DEFAULT_SCHEDULE)])
