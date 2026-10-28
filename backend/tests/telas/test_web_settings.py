"""Tela do servidor das Configurações (ADR 0011)."""

import re
from datetime import datetime, time
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.modules.catalog.models import TicketStatus
from chamados.modules.system.models import SystemSetting, WorkSchedule
from chamados.modules.system.work_hours import TZ
from tests.conftest import consultas, criar_usuario, entrar

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
URL = "/admin/configuracoes"


def _form(client: TestClient, **dados: Any) -> dict[str, Any]:
    return {"csrf_token": client.cookies["tf_csrf"], **dados}


def _aviso(html: str) -> str:
    achado = re.search(r'data-aviso="\w+".*?<p class="font-semibold">(.*?)</p>', html, re.S)
    return achado.group(1) if achado else ""


def _admin(client: TestClient, db: Session) -> None:
    criar_usuario(db, "admin@exemplo.com", "admin", nome="Admin")
    entrar(client, "admin@exemplo.com")


def _valor(db: Session, chave: str) -> Any:
    db.expire_all()
    return db.scalar(select(SystemSetting.value).where(SystemSetting.key == chave))


def test_so_admin(client: TestClient, db: Session) -> None:
    criar_usuario(db, grupos={"TI": "supervisor"})
    entrar(client)
    assert client.get(URL).status_code == 403
    cores = {"brand": "#2563EB", "neutral": "#64748B", "background": "#FFFFFF"}
    assert client.post(URL, data=_form(client, default_locale="en", **cores)).status_code == 403
    assert client.post(f"{URL}/status/novo", data=_form(client, name="X")).status_code == 403
    assert _valor(db, "locale") is None


def test_previa_das_cores(client: TestClient, db: Session) -> None:
    _admin(client, db)
    r = client.get(URL)
    assert r.status_code == 200
    assert 'aria-pressed="true"' in r.text  # a combinação padrão
    # A prévia só é pedida com as três cores válidas (não volta às gravadas a cada tecla).
    assert 'hx-trigger="input changed[this.checkValidity()] delay:200ms"' in r.text
    # A prévia segue as cores digitadas (o HTMX pede a página e troca só #previa).
    r = client.get(URL, params={"brand": "#FDE047", "neutral": "#A3A3A3", "background": "#FFFFFF"})
    assert "--tf-brand:#FDE047" in r.text
    assert "Tom ajustado para leitura:" in r.text  # o amarelo claro não dá para ler
    # Cor incompleta: a prévia fica com as cores gravadas.
    assert "--tf-brand:#F97316" in client.get(URL, params={"brand": "#FDE0"}).text


def test_idioma_e_cores(client: TestClient, db: Session) -> None:
    _admin(client, db)
    cores = {"brand": "#2563eb", "neutral": "#64748B", "background": "#FFFFFF"}
    r = client.post(URL, data=_form(client, default_locale="en", **cores))
    assert _aviso(r.text) == "Alterações salvas"  # montado antes da troca
    assert '<html lang="en">' in r.text  # a tela já volta no idioma novo
    assert _valor(db, "locale") == "en"
    assert _valor(db, "colors") == {k: v.upper() for k, v in cores.items()}
    # As cores padrão voltam a ser "nenhuma personalização".
    padrao = {"brand": "#F97316", "neutral": "#737373", "background": "#FFFFFF"}
    client.post(URL, data=_form(client, default_locale="pt-BR", **padrao))
    assert _valor(db, "colors") is None
    r = client.post(URL, data=_form(client, default_locale="pt-BR", **{**padrao, "brand": "azul"}))
    assert _aviso(r.text) == "Use o formato #RRGGBB."


def test_logotipo(client: TestClient, db: Session) -> None:
    _admin(client, db)
    envio = _form(client)
    r = client.post(f"{URL}/logo", data=envio, files={"logo": ("logo.gif", b"GIF89a", "image/gif")})
    assert _aviso(r.text) == "Envie uma imagem PNG, JPEG ou WebP."
    grande = PNG + b"\0" * 256 * 1024
    r = client.post(f"{URL}/logo", data=envio, files={"logo": ("logo.png", grande, "image/png")})
    assert _aviso(r.text) == "A imagem passa de 256 KB."
    r = client.post(f"{URL}/logo", data=envio, files={"logo": ("logo.png", PNG, "image/png")})
    assert _aviso(r.text) == "Logotipo atualizado"
    assert '<img src="/api/v1/branding/logo?v=' in r.text
    r = client.post(f"{URL}/logo/remover", data=envio)
    assert _aviso(r.text) == "Logotipo removido"
    assert _valor(db, "logo") is None


def test_status(client: TestClient, db: Session) -> None:
    _admin(client, db)
    r = client.post(f"{URL}/status/novo", data=_form(client, name="Em análise", kind="open"))
    assert _aviso(r.text) == "Status criado"
    novo = db.scalar(select(TicketStatus).where(TicketStatus.name == "Em análise"))
    assert novo is not None
    assert f"?renomear={novo.id}" in r.text

    r = client.post(f"{URL}/status/{novo.id}", data=_form(client, name="Analisando"))
    assert _aviso(r.text) == "Alterações salvas"
    # Mesmo nome: nada a gravar, nem aviso.
    r = client.post(f"{URL}/status/{novo.id}", data=_form(client, name="Analisando"))
    assert _aviso(r.text) == ""
    # O último sobe um lugar.
    antes = [s.id for s in db.scalars(select(TicketStatus).order_by(TicketStatus.sort_order))]
    client.post(f"{URL}/status/{novo.id}/mover", data=_form(client, para="cima"))
    db.expire_all()
    depois = [s.id for s in db.scalars(select(TicketStatus).order_by(TicketStatus.sort_order))]
    assert depois == [*antes[:-2], antes[-1], antes[-2]]

    r = client.post(f"{URL}/status/{novo.id}/remover", data=_form(client))
    assert _aviso(r.text) == "Status Analisando removido"
    # O único de um comportamento não sai: a API recusa e a tela mostra o motivo.
    cancelado = db.scalar(select(TicketStatus).where(TicketStatus.kind == "canceled"))
    assert cancelado is not None
    r = client.post(f"{URL}/status/{cancelado.id}/remover", data=_form(client))
    assert 'data-aviso="error"' in r.text


def test_expediente(client: TestClient, db: Session) -> None:
    _admin(client, db)
    hoje = datetime.now(TZ).date()
    # Sem vigência gravada, a lista mostra o padrão desde sempre.
    r = client.get(URL)
    assert "Desde sempre</span>" in r.text and "Seg–Sex 08:00–12:00, 13:30–18:00" in r.text
    assert f'name="valid_from" type="date" value="{hoje.isoformat()}"' in r.text
    assert 'name="break_start" type="time" value="12:00"' in r.text
    assert 'name="break_end" type="time" value="13:30"' in r.text
    dados = {
        "valid_from": hoje.isoformat(),
        "weekdays": ["0", "1", "2", "3"],
        "start": "09:00",
        "end": "17:30",
        "holidays": ["2026-12-25", "2026-11-20", "2026-12-25"],
    }
    r = client.post(f"{URL}/expediente", data=_form(client, **dados))
    assert _aviso(r.text) == "Alterações salvas"
    # O horário vira uma vigência da instalação a partir de hoje; os feriados ficam na chave.
    assert _valor(db, "work_hours") == {"holidays": ["2026-11-20", "2026-12-25"]}
    vigencia = db.scalars(select(WorkSchedule)).one()
    assert (vigencia.weekdays, vigencia.start, vigencia.end) == (
        [0, 1, 2, 3],
        time(9),
        time(17, 30),
    )
    assert vigencia.valid_from == hoje
    assert "25/12/2026" in r.text
    assert "Seg–Qui 09:00–17:30" in r.text
    r = client.post(f"{URL}/expediente", data=_form(client, **{**dados, "end": "08:00"}))
    assert _aviso(r.text) == "O fim precisa ser depois do início."
    for intervalo in ({"break_start": "12:00"}, {"break_start": "17:00", "break_end": "18:00"}):
        r = client.post(f"{URL}/expediente", data=_form(client, **{**dados, **intervalo}))
        assert _aviso(r.text).startswith("O intervalo precisa"), intervalo
    r = client.post(f"{URL}/expediente", data=_form(client, **{**dados, "valid_from": "x"}))
    assert _aviso(r.text) == "Informe uma data válida."
    # Uma vigência futura entra na lista, sem a marca de "Vale hoje".
    # Igual à anterior: nada a gravar.
    client.post(f"{URL}/expediente", data=_form(client, **{**dados, "valid_from": "2099-01-01"}))
    assert len(db.scalars(select(WorkSchedule)).all()) == 1
    futura = {**dados, "valid_from": "2099-01-01", "weekdays": ["0"]}
    r = client.post(f"{URL}/expediente", data=_form(client, **futura))
    assert "A partir de 01/01/2099" in r.text
    assert r.text.count(">Vale hoje</span>") == 1
    # Com intervalo: a vigência de hoje passa a tê-lo.
    r = client.post(
        f"{URL}/expediente",
        data=_form(client, **{**dados, "break_start": "12:00", "break_end": "13:00"}),
    )
    assert "Seg–Qui 09:00–12:00, 13:00–17:30" in r.text
    db.expire_all()
    vigencia = db.scalars(select(WorkSchedule).where(WorkSchedule.valid_from == hoje)).one()
    assert (vigencia.break_start, vigencia.break_end) == (time(12), time(13))


def test_marca_lida_numa_consulta(client: TestClient, db: Session) -> None:
    """Toda tela lê o idioma, as cores e o logotipo: numa consulta só, sem a imagem."""
    _admin(client, db)
    cores = {"brand": "#2563EB", "neutral": "#64748B", "background": "#FFFFFF"}
    client.post(URL, data=_form(client, default_locale="pt-BR", **cores))
    client.post(f"{URL}/logo", data=_form(client), files={"logo": ("logo.png", PNG, "image/png")})
    with consultas(client) as sql:
        r = client.get("/chamados")
    assert len([q for q in sql if "FROM settings" in q]) == 1
    assert "/api/v1/branding/logo?v=" in r.text
    assert "--tf-primary:" in r.text  # a folha das cores personalizadas
